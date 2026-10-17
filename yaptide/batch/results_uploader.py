"""Uploads the merged results of an HPC simulation from the cluster straight to the backend's object storage.

Runs at the end of the collect job, with the standard library only. For every page of every estimator in the
output directory (convertmc's JSON files) it asks the backend for a signed upload link, uploads the gzipped page,
then tells the backend what it uploaded; the backend checks the pages are in storage and lists any missing one,
which is uploaded again. A backend without object storage gets the results the old way, in one request.
"""

import argparse
import base64
import gzip
import hashlib
import io
import json
import logging
import ssl
import sys
import time
from pathlib import Path
from typing import List, Tuple
from http.client import HTTPException
from urllib import error, request

# attempts with growing pauses: 10 + 20 + ... + 50 s, longer than a restart of the backend
ATTEMPTS = 6
RETRY_SECONDS = 10
# the TLS certificate chain of the backend is not always complete for the cluster's OpenSSL, so it is not verified,
# as in the other scripts sending to the backend
CONTEXT = ssl.create_default_context()
CONTEXT.check_hostname = False
CONTEXT.verify_mode = ssl.CERT_NONE  # skipcq: PTC-W6001 # see above


def page_body(page: dict) -> bytes:
    """The page as the UI reads it from storage: gzipped JSON, the same bytes every time (no timestamp)"""
    # GzipFile, not gzip.compress(mtime=...): the Python on a cluster can be older than 3.8
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as gzipped:
        gzipped.write(json.dumps(page).encode())
    return buffer.getvalue()


def read_estimators(output_dir: Path) -> List[dict]:
    """Estimators as convertmc wrote them, one JSON file each, named by the file"""
    estimators = []
    for path in sorted(output_dir.glob("*.json")):
        estimator = json.loads(path.read_text())
        estimator["name"] = path.stem
        estimators.append(estimator)
    return estimators


def manifest(estimators: List[dict]) -> List[dict]:
    """What will be uploaded: every page with its size and MD5, without the page data"""
    result = []
    for estimator in estimators:
        pages = []
        for page in estimator["pages"]:
            body = page_body(page)
            pages.append(
                {
                    "page_number": int(page["metadata"]["page_number"]),
                    "name": str(page["metadata"].get("name", "")),
                    "dimensions": int(page["dimensions"]),
                    "size": len(body),
                    # the Content-MD5 S3 checks the upload with, not a security measure
                    "md5": base64.b64encode(hashlib.md5(body).digest()).decode(),  # skipcq: PTC-W1003
                }
            )
        result.append({"name": estimator["name"], "metadata": estimator["metadata"], "pages": pages})
    return result


def post(url: str, payload: dict) -> Tuple[int, dict]:
    """POSTs JSON to the backend, retrying when it cannot be reached; returns the status and the answer"""
    data = json.dumps(payload).encode()
    for attempt in range(ATTEMPTS):
        req = request.Request(url, data, {"Content-Type": "application/json"}, method="POST")
        try:
            with request.urlopen(req, context=CONTEXT, timeout=60) as response:  # skipcq: BAN-B310
                return response.status, json.loads(response.read() or b"{}")
        except error.HTTPError as http_error:
            # 501: the backend has no object storage - an answer, not a failure to retry
            if http_error.code < 500 or http_error.code == 501:
                return http_error.code, json.loads(http_error.read() or b"{}")
            logging.warning("%s answered %d", url, http_error.code)
        except (OSError, HTTPException) as connection_error:
            # unreachable, or the connection dropped (e.g. a restart of the backend)
            logging.warning("%s unreachable: %s", url, connection_error)
        if attempt < ATTEMPTS - 1:
            time.sleep(RETRY_SECONDS * (attempt + 1))
    return 0, {}


# what put() can end with
STORED, LINK_EXPIRED, REFUSED = "stored", "link expired", "refused"


def put(url: str, body: bytes, md5: str) -> str:
    """Uploads one page to its signed link, retrying when the storage cannot be reached"""
    headers = {"Content-MD5": md5, "Content-Type": "application/json", "Content-Encoding": "gzip"}
    for attempt in range(ATTEMPTS):
        req = request.Request(url, body, headers, method="PUT")
        try:
            with request.urlopen(req, context=CONTEXT, timeout=300) as response:  # skipcq: BAN-B310
                return STORED if response.status == 200 else REFUSED
        except error.HTTPError as http_error:
            if http_error.code == 403:
                # links last minutes; a long upload gets new ones
                return LINK_EXPIRED
            if http_error.code < 500:
                logging.error("Upload refused: %d %s", http_error.code, http_error.read()[:500])
                return REFUSED
            logging.warning("Upload answered %d", http_error.code)
        except (OSError, HTTPException) as connection_error:
            logging.warning("Upload failed: %s", connection_error)
        if attempt < ATTEMPTS - 1:
            time.sleep(RETRY_SECONDS * (attempt + 1))
    return REFUSED


# what upload() can end with
UPLOADED, NO_STORAGE, FAILED, AGAIN = "uploaded", "no storage", "failed", "again"


def upload(estimators: List[dict], listed: List[dict], wanted: set, args) -> str:
    """Uploads the wanted pages ((estimator, page number) pairs)"""
    entries = [
        {"estimator": estimator["name"], **{key: page[key] for key in ("page_number", "size", "md5")}}
        for estimator in listed
        for page in estimator["pages"]
        if (estimator["name"], page["page_number"]) in wanted
    ]
    status, answer = post(
        f"{args.backend_url}/results/uploads",
        {"simulation_id": args.sim_id, "update_key": args.update_key, "pages": entries},
    )
    if status == 501:
        return NO_STORAGE
    if status != 200:
        logging.error("Upload links refused: %d %s", status, answer)
        return FAILED
    links = {(link["estimator"], link["page_number"]): link["url"] for link in answer["uploads"]}
    md5s = {(entry["estimator"], entry["page_number"]): entry["md5"] for entry in entries}
    for estimator in estimators:
        for page in estimator["pages"]:
            page_id = (estimator["name"], int(page["metadata"]["page_number"]))
            if page_id not in wanted:
                continue
            stored = put(links[page_id], page_body(page), md5s[page_id])
            if stored == LINK_EXPIRED:
                return AGAIN
            if stored == REFUSED:
                return FAILED
            wanted.discard(page_id)
    return UPLOADED


def send_old_way(estimators: List[dict], args) -> bool:
    """A backend without object storage takes the results in one request, as before"""
    status, _ = post(
        f"{args.backend_url}/results",
        {"simulation_id": args.sim_id, "update_key": args.update_key, "estimators": estimators},
    )
    return status == 202


def main(args) -> int:
    """Uploads the results and reports them done; a failure exits non-zero, the collect job then reports FAILED"""
    estimators = read_estimators(Path(args.output_dir))
    if not estimators:
        logging.error("No results in %s", args.output_dir)
        return 1
    listed = manifest(estimators)
    wanted = {(estimator["name"], page["page_number"]) for estimator in listed for page in estimator["pages"]}
    for _ in range(ATTEMPTS):
        uploaded = upload(estimators, listed, wanted, args)
        for _ in range(ATTEMPTS):
            if uploaded != AGAIN:
                break
            # what is left of wanted, with new links
            uploaded = upload(estimators, listed, wanted, args)
        if uploaded == AGAIN:
            # every new link refused too (e.g. a clock far off on this node)
            return 1
        if uploaded == NO_STORAGE:
            return 0 if send_old_way(estimators, args) else 1
        if uploaded == FAILED:
            return 1
        status, answer = post(
            f"{args.backend_url}/results/done",
            {"simulation_id": args.sim_id, "update_key": args.update_key, "estimators": listed},
        )
        if status == 202:
            return 0
        if status != 409 or "missing" not in answer:
            logging.error("Results refused: %d %s", status, answer)
            return 1
        # pages the storage does not have: uploaded again
        wanted = {(page["estimator"], page["page_number"]) for page in answer["missing"]}
    return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--sim_id", type=int, required=True)
    parser.add_argument("--update_key", required=True)
    parser.add_argument("--backend_url", required=True)
    sys.exit(main(parser.parse_args()))
