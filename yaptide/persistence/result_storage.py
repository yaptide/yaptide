"""Result pages in S3-compatible object storage (the garage service of docker-compose.yml); the database keeps only
where they are (PageObjectModel).

Each page is a Zarr v3 array (yaptide/batch/result_format.py) under a prefix of its own that changes every time the
page is stored again (a revision), so a page being replaced is never half written for a reader: the database points
at the new prefix only once all of its objects are in storage, and the old prefix is removed afterwards.

A bucket is required: RESULTS_S3_BUCKET, RESULTS_S3_ENDPOINT, RESULTS_S3_ACCESS_KEY and RESULTS_S3_SECRET_KEY.
"""

import base64
import hashlib
import logging
import os
import secrets
from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from yaptide.batch import result_format

# a page as a Zarr v3 array, its objects under a prefix (PageObjectModel.key ends with "/")
ZARR_FORMAT = result_format.FORMAT
# the UI fetches a page right after asking for it; a link that leaks stops working this long after
URL_SECONDS = 15 * 60
# the settings without which no results can be stored
REQUIRED_SETTINGS = ("RESULTS_S3_BUCKET", "RESULTS_S3_ENDPOINT", "RESULTS_S3_ACCESS_KEY", "RESULTS_S3_SECRET_KEY")


def missing_settings() -> list[str]:
    """The required settings of the results bucket that are not set"""
    return [name for name in REQUIRED_SETTINGS if not os.environ.get(name)]


def bucket() -> str:
    """The results bucket"""
    return os.environ["RESULTS_S3_BUCKET"]


@lru_cache(maxsize=3)
def _client(endpoint: str, read_timeout: int = 10, attempts: int = 2):
    """S3 client for the given endpoint: the internal one for reads and writes, the public one for browser links;
    the defaults fail fast, for a web request waiting on the storage
    """
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ.get("RESULTS_S3_ACCESS_KEY"),
        aws_secret_access_key=os.environ.get("RESULTS_S3_SECRET_KEY"),
        region_name=os.environ.get("RESULTS_S3_REGION", "garage"),
        config=Config(
            s3={"addressing_style": "path"},
            signature_version="s3v4",
            # over https boto3 >= 1.36 sends streaming checksums (aws-chunked), which not every S3 server reads
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            connect_timeout=2,
            read_timeout=read_timeout,
            # attempts in total ("max_attempts" would count retries only, one more)
            retries={"total_max_attempts": attempts},
        ),
    )


def _internal():
    """Client reaching the storage directly, inside the compose network"""
    return _client(os.environ["RESULTS_S3_ENDPOINT"])


def _patient():
    """Like _internal, for removals of many objects: a busy storage gets time and more attempts (removing again what
    is gone already is harmless)
    """
    return _client(os.environ["RESULTS_S3_ENDPOINT"], read_timeout=120, attempts=5)


def public_client():
    """Client signing links for the browser, at the backend's public address (nginx passes /yaptide-results/ on)"""
    return _client(os.environ.get("RESULTS_S3_PUBLIC_ENDPOINT") or os.environ["BACKEND_EXTERNAL_URL"])


# result pages, the only copy of the results: see delete_simulation
PAGE_PREFIX = "simulations/"


def new_revision() -> str:
    """A name for the pages of one store, apart from the pages of every other store of the simulation"""
    return secrets.token_hex(8)


def page_prefix(sim_id: int, estimator_file_name: str, page_number: int, revision: str) -> str:
    """Prefix of the objects of a page, one for each revision"""
    return f"{PAGE_PREFIX}{sim_id}/{estimator_file_name}/{page_number}/{revision}/"


def body_md5(body: bytes) -> str:
    """MD5 of an object's body in base64, as the Content-MD5 header carries it"""
    # the checksum S3 asks for, not a security measure
    return base64.b64encode(hashlib.md5(body, usedforsecurity=False).digest()).decode()  # skipcq: PTC-W1003


def put_page_files(prefix: str, files: dict[str, bytes]) -> int:
    """Stores the objects of a page under the prefix; returns their size in bytes. The storage rejects a body that
    arrives changed (Content-MD5).
    """
    for name, body in files.items():
        _internal().put_object(
            Bucket=bucket(),
            Key=prefix + name,
            Body=body,
            ContentMD5=body_md5(body),
            ContentType=result_format.content_type(name),
        )
    return sum(len(body) for body in files.values())


def get_page_files(prefix: str) -> dict[str, bytes]:
    """The objects of a page: name -> body; a page without values has no shard"""
    files = {}
    for name in result_format.FILES:
        try:
            files[name] = _internal().get_object(Bucket=bucket(), Key=prefix + name)["Body"].read()
        except ClientError as error:
            if name == result_format.METADATA_FILE or not _not_found(error):
                raise
    return files


def page_url(key: str) -> str:
    """Signed link the browser fetches an object from, through nginx at the backend's public address"""
    return public_client().generate_presigned_url(
        "get_object", Params={"Bucket": bucket(), "Key": key}, ExpiresIn=URL_SECONDS
    )


def page_file_urls(prefix: str) -> dict[str, str]:
    """Signed links the browser fetches the objects of a page from: name -> link; a page without values has no
    shard, its link answers 404, which a Zarr reader takes as a page of the fill value
    """
    return {name: page_url(prefix + name) for name in result_format.FILES}


def stored_matches(key: str, size: int, md5: str) -> bool:
    """Whether the object is in storage with this size and MD5 (base64), i.e. its upload completed"""
    try:
        head = _internal().head_object(Bucket=bucket(), Key=key)
    except ClientError as error:
        if _not_found(error):
            return False
        raise
    # the ETag of an object uploaded in one piece is its MD5, in hex
    return head["ContentLength"] == size and head["ETag"].strip('"') == base64.b64decode(md5).hex()


def _not_found(error: ClientError) -> bool:
    """Whether the storage answered that the object does not exist"""
    return error.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound")


# keys removed in one request: with S3's maximum of 1000 a busy storage took longer than the client waits
DELETE_BATCH = 500


def _delete_listed(client, prefix: str) -> None:
    """Removes every object under the prefix in the bucket, DELETE_BATCH at a time, each batch as it is listed"""
    listings = client.get_paginator("list_objects_v2").paginate(
        Bucket=bucket(), Prefix=prefix, PaginationConfig={"PageSize": DELETE_BATCH}
    )
    for listing in listings:
        keys = [{"Key": item["Key"]} for item in listing.get("Contents", [])]
        if keys:
            errors = client.delete_objects(Bucket=bucket(), Delete={"Objects": keys, "Quiet": True}).get("Errors")
            if errors:
                raise RuntimeError(f"storage kept {len(errors)} objects under {prefix}: {errors[0]}")


def delete_pages(prefixes: list[str]) -> None:
    """Removes stored pages no page points at any more (replaced by a later store, or refused); a failure only
    leaves them until the simulation is deleted
    """
    for prefix in prefixes:
        try:
            _delete_listed(_internal(), prefix)
        except Exception:  # skipcq: PYL-W0703
            logging.exception("Removing the stored page %s failed", prefix)


def delete_simulation(sim_id: int) -> None:
    """Removes the stored result pages of a deleted simulation, in batches; slow for a large one"""
    _delete_listed(_patient(), f"{PAGE_PREFIX}{sim_id}/")
