"""Result pages in S3-compatible object storage (Garage on yap-dev); the database keeps only where they are.

Without RESULTS_S3_BUCKET set, pages stay in the database as before (tests, local runs, older deployments).
The result files of direct simulation tasks pass to the merges through the storage too, so a merge may run on
another machine than the tasks; without a bucket they pass through a local directory instead (one machine only).
"""

import base64
import gzip
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlencode
from xml.etree import ElementTree  # skipcq: BAN-B405

import boto3
import urllib3
from botocore.auth import S3SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.config import Config
from botocore.credentials import Credentials
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
            # over https boto3 >= 1.36 sends streaming checksums (aws-chunked), which clash with Content-Encoding: gzip
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
    """Like _internal, for removals nobody waits for: a busy storage gets time and more attempts (removing again what
    is gone already is harmless)
    """
    return _client(os.environ["RESULTS_S3_ENDPOINT"], read_timeout=120, attempts=5)


# result pages, the only copy of the results: see delete_simulation
PAGE_PREFIX = "simulations/"


def page_key(sim_id: int, estimator_file_name: str, page_number: int) -> str:
    """Object key of a result page; the same page always gets the same key, so a repeated upload replaces it"""
    return f"{PAGE_PREFIX}{sim_id}/{estimator_file_name}/{page_number}.json"


def full_resolution_key(sim_id: int, estimator_file_name: str) -> str:
    """Object key of an estimator's full resolution (a .bdo file), kept when its pages were downsampled for the UI;
    with the result pages, removed with them. Named after the estimator, the name a download gets.
    """
    return f"{PAGE_PREFIX}{sim_id}/{estimator_file_name}/{estimator_file_name.rstrip('_')}.bdo"


def put_page(key: str, page: dict) -> int:
    """Stores a page as gzipped JSON the browser decompresses itself; returns the stored size in bytes"""
    body = gzip.compress(json.dumps(page).encode())
    put_gzipped_page(key, body)
    return len(body)


def body_md5(body: bytes) -> str:
    """MD5 of an object's body in base64, as the Content-MD5 header carries it"""
    # the checksum S3 asks for, not a security measure
    return base64.b64encode(hashlib.md5(body, usedforsecurity=False).digest()).decode()  # skipcq: PTC-W1003


def put_gzipped_page(key: str, body: bytes) -> None:
    """Stores a page already gzipped (as the database kept it); the storage rejects a body that arrives changed"""
    _internal().put_object(
        Bucket=os.environ["RESULTS_S3_BUCKET"],
        Key=key,
        Body=body,
        ContentMD5=body_md5(body),
        ContentType="application/json",
        ContentEncoding="gzip",
    )


def get_gzipped_page(key: str) -> bytes:
    """The stored body of a page, still gzipped"""
    return _internal().get_object(Bucket=os.environ["RESULTS_S3_BUCKET"], Key=key)["Body"].read()


def page_url(key: str) -> str:
    """Signed link the browser fetches the page from, through nginx at the backend's public address"""
    return public_client().generate_presigned_url(
        "get_object", Params={"Bucket": os.environ["RESULTS_S3_BUCKET"], "Key": key}, ExpiresIn=URL_SECONDS
    )


# result files of direct simulation tasks on their way to the merges, removed after the final merge; the saves of
# HPC tasks on their way to the partial merges, removed once the simulation stops running
WORK_PREFIX = "work/"
# what HPC jobs report and tasks leave, of no use once their simulation is gone: the engine's look for orphans removes
# these; never the result pages (PAGE_PREFIX), only a delete of their simulation removes them
EPHEMERAL_PREFIXES = ("hpc/", WORK_PREFIX)
# keys removed in one request: with S3's maximum of 1000 a busy storage took longer than the client waits
DELETE_BATCH = 500


def delete_simulation(sim_id: int, pages: bool) -> None:
    """Removes the stored objects of a deleted simulation, its result pages too only when pages is set; slow for a
    large one, so the engine does it in the background
    """
    for prefix in (PAGE_PREFIX, *EPHEMERAL_PREFIXES) if pages else EPHEMERAL_PREFIXES:
        _delete_listed(_patient(), f"{prefix}{sim_id}/")


def stored_simulations() -> set[int]:
    """Ids of the simulations with objects under EPHEMERAL_PREFIXES, from the directories' names (a request per 1000
    of them)
    """
    ids = set()
    for prefix in EPHEMERAL_PREFIXES:
        listings = (
            _internal()
            .get_paginator("list_objects_v2")
            .paginate(Bucket=os.environ["RESULTS_S3_BUCKET"], Prefix=prefix, Delimiter="/")
        )
        for listing in listings:
            for directory in listing.get("CommonPrefixes", []):
                # anything else there is no simulation's
                match = re.fullmatch(re.escape(prefix) + r"(\d{1,10})/", directory["Prefix"])
                if match:
                    ids.add(int(match.group(1)))
    return ids


def _delete_listed(client, prefix: str) -> None:
    """Removes every object under the prefix in the bucket, DELETE_BATCH at a time, each batch as it is listed"""
    bucket = os.environ["RESULTS_S3_BUCKET"]
    listings = client.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=prefix, PaginationConfig={"PageSize": DELETE_BATCH}
    )
    for listing in listings:
        keys = [{"Key": item["Key"]} for item in listing.get("Contents", [])]
        if keys:
            errors = client.delete_objects(Bucket=bucket, Delete={"Objects": keys, "Quiet": True}).get("Errors")
            if errors:
                raise RuntimeError(f"storage kept {len(errors)} objects under {prefix}: {errors[0]}")


def public_client():
    """Client signing links for the browser and the clusters, at the backend's public address"""
    return _client(os.environ.get("RESULTS_S3_PUBLIC_ENDPOINT") or os.environ["BACKEND_EXTERNAL_URL"])


def upload_url(key: str, size: int, md5: str, page: bool = True) -> str:
    """Signed link a cluster job uploads one gzipped page (or, not a page, a binary file) with; the storage rejects
    any other size or content

    md5 is the base64 MD5 of the body, as the Content-MD5 header carries it.
    """
    params = {"Bucket": os.environ["RESULTS_S3_BUCKET"], "Key": key, "ContentLength": size, "ContentMD5": md5}
    if page:
        params.update(ContentType="application/json", ContentEncoding="gzip")
    else:
        params["ContentType"] = "application/octet-stream"
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


# HPC jobs report progress and learn about a cancel through storage, with links signed at submit; a signature
# lasts at most 7 days, a job running longer asks the backend for new ones
JOB_LINK_SECONDS = 7 * 24 * 3600
# a task's progress report: a few numbers
MAX_PROGRESS_BYTES = 64 * 1024


def progress_prefix(sim_id: int) -> str:
    """Where the tasks of an HPC simulation put their progress, one object per task"""
    # apart from the result pages (simulations/...), which an estimator called "progress" would otherwise mix with
    return f"hpc/{sim_id}/progress/"


def cancel_key(sim_id: int) -> str:
    """The object whose presence tells an HPC simulation's tasks to stop"""
    return f"hpc/{sim_id}/cancel"


def job_links(sim_id: int, saving_tasks: int = 0) -> dict:
    """Signed links the jobs of an HPC simulation use: a POST policy for progress objects under the simulation's
    progress prefix only (each at most MAX_PROGRESS_BYTES), a HEAD of its cancel object and, for each of the first
    saving_tasks tasks, a PUT of its saves (the work_key of the task, at most its share of HPC_SAVES_MAX_BYTES)
    """
    bucket = os.environ["RESULTS_S3_BUCKET"]
    prefix = progress_prefix(sim_id)
    client = public_client()
    post = client.generate_presigned_post(
        bucket,
        prefix + "${filename}",
        Conditions=[["starts-with", "$key", prefix], ["content-length-range", 1, MAX_PROGRESS_BYTES]],
        ExpiresIn=JOB_LINK_SECONDS,
    )
    cancel = client.generate_presigned_url(
        "head_object", Params={"Bucket": bucket, "Key": cancel_key(sim_id)}, ExpiresIn=JOB_LINK_SECONDS
    )
    # a PUT link per task, not a POST policy: the storage may read a POST body whole into memory before refusing it,
    # so nginx lets only small ones through; a PUT link is checked before any data is taken (nginx caps it at 2 GB,
    # the engine merges only saves within HPC_SAVES_MAX_BYTES)
    saves = {
        str(task_id): client.generate_presigned_url(
            "put_object", Params={"Bucket": bucket, "Key": work_key(sim_id, task_id)}, ExpiresIn=JOB_LINK_SECONDS
        )
        for task_id in range(1, saving_tasks + 1)
    }
    # the jobs ask for new links a day before these expire (Garage answers an expired link with 400, like a bad one)
    expires = int(time.time()) + JOB_LINK_SECONDS
    return {
        "progress": {"url": post["url"], "fields": post["fields"], "prefix": prefix},
        "cancel": cancel,
        # each task its share: the engine merges the saves of all tasks only within the limit, larger ones would be
        # sent for nothing
        "saves": {"urls": saves, "max_bytes": HPC_SAVES_MAX_BYTES // max(saving_tasks, 1)},
        "expires": expires,
    }


# reports read at once by one process; a report takes about 0.2 ms of CPU to read (on an M4, under the GIL), so
# a process reads at most a few thousand a second whatever the threads, and the engine spreads them over processes
REPORT_CONNECTIONS = 16
# the ListObjectsV2 answer
S3_XML = "{http://s3.amazonaws.com/doc/2006-03-01/}"


@lru_cache(maxsize=1)
def _report_reader() -> tuple[S3SigV4Auth, urllib3.PoolManager]:
    """Signer and connections for the progress reports: plain signed GETs take a fraction of the CPU of a boto3
    request (0.2 ms instead of 0.5 ms a report, a sixth of it for a listing), which bounds the reports read a second
    """
    credentials = Credentials(os.environ.get("RESULTS_S3_ACCESS_KEY"), os.environ.get("RESULTS_S3_SECRET_KEY"))
    signer = S3SigV4Auth(credentials, "s3", os.environ.get("RESULTS_S3_REGION", "garage"))
    # as the boto3 client: fail fast, two attempts in total
    http = urllib3.PoolManager(
        maxsize=REPORT_CONNECTIONS, timeout=urllib3.Timeout(connect=2, read=10), retries=urllib3.Retry(total=1)
    )
    return signer, http


def _signed_get(key: Optional[str] = None, query: Optional[dict] = None) -> bytes:
    """Body of a GET of an object, or of the bucket without a key; storage out of reach or answering anything but
    200 raises ConnectionError (an OSError)
    """
    signer, http = _report_reader()
    url = f"{os.environ['RESULTS_S3_ENDPOINT']}/{os.environ['RESULTS_S3_BUCKET']}" + (f"/{quote(key)}" if key else "")
    request = AWSRequest("GET", url + (f"?{urlencode(query, quote_via=quote)}" if query else ""))
    signer.add_auth(request)
    try:
        response = http.request("GET", request.url, headers=dict(request.headers))
    except urllib3.exceptions.HTTPError as error:
        raise ConnectionError(f"storage out of reach: {error}") from error
    if response.status != 200:
        raise ConnectionError(f"storage answered {response.status} for {key or query}")
    return response.data


def progress_reports(sim_id: int) -> dict[str, str]:
    """The progress objects of an HPC simulation: key -> ETag, which changes with every new report"""
    reports, query = {}, {"list-type": "2", "prefix": progress_prefix(sim_id)}
    while True:
        # the storage's own answer, not the jobs'
        listing = ElementTree.fromstring(_signed_get(query=query))  # skipcq: BAN-B314
        for item in listing.iter(S3_XML + "Contents"):
            reports[item.findtext(S3_XML + "Key")] = item.findtext(S3_XML + "ETag")
        query["continuation-token"] = listing.findtext(S3_XML + "NextContinuationToken")
        if not query["continuation-token"]:
            return reports


def read_report(key: str) -> dict:
    """A task's progress report"""
    return json.loads(_signed_get(key))


def put_cancel(sim_id: int) -> None:
    """Tells the tasks of an HPC simulation to stop; they check for this object"""
    _internal().put_object(Bucket=os.environ["RESULTS_S3_BUCKET"], Key=cancel_key(sim_id), Body=b"")


# the saves of an HPC simulation's tasks merged into partial results at once, in bytes, packed and unpacked, which
# bounds one task's save too: a simulation with larger results gets them only at the end
HPC_SAVES_MAX_BYTES = int(os.environ.get("RESULTS_HPC_SAVES_MAX_BYTES", 128 << 20))


# objects left under WORK_PREFIX (a crash, a failed delete) expire after this long; direct tasks run at most 10 hours,
# an HPC task replaces its save at every save (one expiring first only leaves the partial results without it)
WORK_EXPIRY_DAYS = 2
# objects under hpc/ (progress reports, cancels) expire after this long: the engine reads the last reports within
# minutes after the simulation ended and puts the cancel again while its jobs may still run; a report expiring under
# a task that ran this long without news only goes unread again, its next report brings it back
HPC_EXPIRY_DAYS = 14


def expire_objects() -> None:
    """Has the storage itself remove what is left under WORK_PREFIX and hpc/, as a backstop to the engine's deletes;
    sets every lifecycle rule of the bucket at once (a call replaces them all), so repeating it changes nothing
    """
    rules = [
        {"ID": name, "Filter": {"Prefix": prefix}, "Expiration": {"Days": days}, "Status": "Enabled"}
        for name, prefix, days in (("work", WORK_PREFIX, WORK_EXPIRY_DAYS), ("hpc", "hpc/", HPC_EXPIRY_DAYS))
    ]
    _internal().put_bucket_lifecycle_configuration(
        Bucket=os.environ["RESULTS_S3_BUCKET"], LifecycleConfiguration={"Rules": rules}
    )


def work_prefix(sim_id: int) -> str:
    """Where the tasks of a simulation put their result files for the merges"""
    return f"{WORK_PREFIX}{sim_id}/"


def work_key(sim_id: int, task_id: int) -> str:
    """A task's latest result files, one archive replaced at every save and at the end"""
    return f"{work_prefix(sim_id)}task_{task_id}.tar.gz"


def _local(key: str) -> Path:
    """Where an object is kept without a bucket"""
    # read every time: tempfile keeps the directory it found first, before a test or a worker set TMPDIR
    return Path(os.environ.get("TMPDIR") or tempfile.gettempdir()) / "yaptide_objects" / key


def put_file(key: str, path: Path) -> None:
    """Stores the file under the key, replacing the object at once (readers get the old or the new one, never a
    part), and removes the file
    """
    if configured():
        _internal().upload_file(str(path), os.environ["RESULTS_S3_BUCKET"], key)
        path.unlink()
        return
    target = _local(key)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    shutil.move(path, partial)
    os.replace(partial, target)


def get_file(key: str, path: Path) -> None:
    """Writes the object to the file; a missing object raises"""
    if configured():
        # one request, so the object cannot be replaced half way through (a download in parts could mix two)
        body = _internal().get_object(Bucket=os.environ["RESULTS_S3_BUCKET"], Key=key)["Body"]
        with open(path, "wb") as file:
            shutil.copyfileobj(body, file)
    else:
        shutil.copyfile(_local(key), path)


def stored_sizes(prefix: str) -> dict[str, int]:
    """The objects under the prefix in the bucket: key -> size in bytes"""
    sizes = {}
    for listing in (
        _internal().get_paginator("list_objects_v2").paginate(Bucket=os.environ["RESULTS_S3_BUCKET"], Prefix=prefix)
    ):
        for item in listing.get("Contents", []):
            sizes[item["Key"]] = item["Size"]
    return sizes


def delete_objects(prefix: str) -> None:
    """Removes the objects whose keys start with the prefix (a whole directory or one object without a bucket)"""
    if configured():
        # fast-failing: a cancelled task waits for it
        _delete_listed(_internal(), prefix)
        return
    local = _local(prefix)
    if local.is_dir():
        shutil.rmtree(local, ignore_errors=True)
    else:
        local.unlink(missing_ok=True)
