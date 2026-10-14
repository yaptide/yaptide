"""Result pages in S3-compatible object storage (Garage on yap-dev); the database keeps only where they are.

Without RESULTS_S3_BUCKET set, pages stay in the database as before (tests, local runs, older deployments).
"""

import base64
import gzip
import json
import os
from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# the page JSON the UI reads, gzipped; a format kept per page lets other formats (binary, chunked) live alongside
PAGE_FORMAT = "page-json-gzip-v1"
# the UI fetches a page right after asking for it
URL_SECONDS = 15 * 60
# a cluster job uploads its pages right after asking for the links, and asks again when they expire; short, so a
# link cannot replace a page long after the results were stored
UPLOAD_URL_SECONDS = 15 * 60


def configured() -> bool:
    """True when results go to object storage"""
    return bool(os.environ.get("RESULTS_S3_BUCKET"))


@lru_cache(maxsize=2)
def _client(endpoint: str):
    """S3 client for the given endpoint: the internal one for reads and writes, the public one for browser links"""
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ.get("RESULTS_S3_ACCESS_KEY"),
        aws_secret_access_key=os.environ.get("RESULTS_S3_SECRET_KEY"),
        region_name=os.environ.get("RESULTS_S3_REGION", "garage"),
        config=Config(
            s3={"addressing_style": "path"},
            signature_version="s3v4",
            # over https boto3 >= 1.36 sends streaming checksums (aws-chunked), which clash with Content-Encoding: gzip
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            # the results upload waits for the storage within a web request: fail fast instead of ~9 s per page
            connect_timeout=2,
            read_timeout=10,
            # two attempts in total ("max_attempts" would count retries only, three attempts)
            retries={"total_max_attempts": 2},
        ),
    )


def _internal():
    """Client reaching the storage directly, inside the compose network"""
    return _client(os.environ["RESULTS_S3_ENDPOINT"])


def page_key(sim_id: int, estimator_file_name: str, page_number: int) -> str:
    """Object key of a result page; the same page always gets the same key, so a repeated upload replaces it"""
    return f"simulations/{sim_id}/{estimator_file_name}/{page_number}.json"


def put_page(key: str, page: dict) -> int:
    """Stores a page as gzipped JSON the browser decompresses itself; returns the stored size in bytes"""
    body = gzip.compress(json.dumps(page).encode())
    _internal().put_object(
        Bucket=os.environ["RESULTS_S3_BUCKET"],
        Key=key,
        Body=body,
        ContentType="application/json",
        ContentEncoding="gzip",
    )
    return len(body)


def page_url(key: str) -> str:
    """Signed link the browser fetches the page from, through nginx at the backend's public address"""
    return public_client().generate_presigned_url(
        "get_object", Params={"Bucket": os.environ["RESULTS_S3_BUCKET"], "Key": key}, ExpiresIn=URL_SECONDS
    )


def delete_simulation(sim_id: int) -> None:
    """Removes every stored page of a simulation"""
    bucket = os.environ["RESULTS_S3_BUCKET"]
    client = _internal()
    for listing in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=f"simulations/{sim_id}/"):
        keys = [{"Key": item["Key"]} for item in listing.get("Contents", [])]
        if keys:
            errors = client.delete_objects(Bucket=bucket, Delete={"Objects": keys, "Quiet": True}).get("Errors")
            if errors:
                raise RuntimeError(f"storage kept {len(errors)} objects of simulation {sim_id}: {errors[0]}")


def public_client():
    """Client signing links for the browser and the clusters, at the backend's public address"""
    return _client(os.environ.get("RESULTS_S3_PUBLIC_ENDPOINT") or os.environ["BACKEND_EXTERNAL_URL"])


def upload_url(key: str, size: int, md5: str) -> str:
    """Signed link a cluster job uploads one gzipped page with; the storage rejects any other size or content

    md5 is the base64 MD5 of the body, as the Content-MD5 header carries it.
    """
    params = {
        "Bucket": os.environ["RESULTS_S3_BUCKET"],
        "Key": key,
        "ContentLength": size,
        "ContentMD5": md5,
        "ContentType": "application/json",
        "ContentEncoding": "gzip",
    }
    return public_client().generate_presigned_url("put_object", Params=params, ExpiresIn=UPLOAD_URL_SECONDS)


def stored_matches(key: str, size: int, md5: str) -> bool:
    """Whether the object is in storage with this size and MD5 (base64), i.e. its upload completed"""
    try:
        head = _internal().head_object(Bucket=os.environ["RESULTS_S3_BUCKET"], Key=key)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return False
        raise
    # the ETag of an object uploaded in one piece is its MD5, in hex
    return head["ContentLength"] == size and head["ETag"].strip('"') == base64.b64decode(md5).hex()
