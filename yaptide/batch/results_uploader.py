"""Uploads the merged results of an HPC simulation from the cluster straight to the backend's object storage.

Runs after results_merger.py (the collect job at the end, a task for partial results along the way), with the
standard library and result_format.py beside it. The output directory holds the merged pages (result_format) and
their manifest; it may hold convertmc's JSON files instead, on a cluster without a Python that has pymchelper, which
are turned into pages here first. For every object of every page it asks the backend for a signed upload link,
uploads it, then tells the backend what it uploaded; the backend checks the pages are in storage and lists any
missing one, which is uploaded again. A backend without object storage gets the final results the old way, as JSON
in one request.
"""

import argparse
import json
import logging
import ssl
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple
from http.client import HTTPException
from urllib import error, request

try:
    from yaptide.batch import result_format
except ImportError:  # on a cluster, next to this script
    import result_format

# the manifest results_merger.py writes next to the pages
MANIFEST = "results.json"
# attempts with doubling pauses, 5 s up to 2 min: 5 + 10 + ... + 120 s, about 15 min in all - longer than a restart
# of the backend or the storage, and well within the collect job's time limit
ATTEMPTS = 12
RETRY_SECONDS = 5
MAX_PAUSE_SECONDS = 120
# rounds of new links (when they expired), and of uploading again what the storage is missing
ROUNDS = 6
# the TLS certificate chain of the backend is not always complete for the cluster's OpenSSL, so it is not verified,
# as in the other scripts sending to the backend
CONTEXT = ssl.create_default_context()
CONTEXT.check_hostname = False
CONTEXT.verify_mode = ssl.CERT_NONE  # skipcq: PTC-W6001 # see above


def flat(values) -> list:
    """The values of a JSON page, flat: convertmc writes a page of dimension 0 as [value]"""
    result = []
    for value in values:
        if isinstance(value, list):
            result.extend(flat(value))
        else:
            result.append(value)
    return result


def write_page(pages_dir: Path, name: str, page: dict, values: list) -> dict:
    """Writes a page's objects (result_format) under pages_dir; its entry of the manifest"""
    number = int(page["metadata"]["page_number"])
    objects = {}
    for object_name, body in result_format.page_files(page, values).items():
        path = pages_dir / name / str(number) / object_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        objects[object_name] = {"size": len(body), "md5": result_format.body_md5(body)}
    return {
        "page_number": number,
        "name": str(page["metadata"].get("name", "")),
        "dimensions": int(page["dimensions"]),
        "files": objects,
    }


def from_convertmc(output_dir: Path) -> Tuple[dict, Path]:
    """convertmc's JSON files (one per estimator, named by it) turned into pages, one estimator at a time"""
    pages_dir = output_dir / "pages"
    estimators = []
    for path in sorted(output_dir.glob("*.json")):
        estimator = json.loads(path.read_text())
        pages = []
        for page in estimator["pages"]:
            data = dict(page["data"])
            values = flat(data.pop("values"))
            pages.append(write_page(pages_dir, path.stem, dict(page, data=data), values))
        estimators.append({"name": path.stem, "metadata": estimator["metadata"], "pages": pages})
    return {"format": result_format.FORMAT, "primaries": 0, "estimators": estimators}, pages_dir


def read_results(output_dir: Path) -> Tuple[dict, Path]:
    """The manifest of the merged pages and the directory holding them"""
    if (output_dir / MANIFEST).exists():
        return json.loads((output_dir / MANIFEST).read_text()), output_dir
    return from_convertmc(output_dir)


def pause(attempt: int) -> None:
    """Waits before the next attempt"""
    time.sleep(min(RETRY_SECONDS * 2**attempt, MAX_PAUSE_SECONDS))


def transient(code: int) -> bool:
    """Whether an error answer may go away, e.g. while the backend or the storage restarts; 501 is the backend
    without object storage - an answer, not a failure to retry
    """
    return code == 429 or (code >= 500 and code != 501)


def post(url: str, payload: dict) -> Tuple[int, dict]:
    """POSTs JSON to the backend, retrying when it cannot be reached; returns the status and the answer"""
    data = json.dumps(payload).encode()
    for attempt in range(ATTEMPTS):
        req = request.Request(url, data, {"Content-Type": "application/json"}, method="POST")
        try:
            with request.urlopen(req, context=CONTEXT, timeout=60) as response:  # skipcq: BAN-B310
                return response.status, json.loads(response.read() or b"{}")
        except error.HTTPError as http_error:
            if not transient(http_error.code):
                return http_error.code, json.loads(http_error.read() or b"{}")
            logging.warning("%s answered %d", url, http_error.code)
        except (OSError, HTTPException) as connection_error:
            # unreachable, or the connection dropped (e.g. a restart of the backend)
            logging.warning("%s unreachable: %s", url, connection_error)
        if attempt < ATTEMPTS - 1:
            pause(attempt)
    return 0, {}


# what put() can end with
STORED, LINK_EXPIRED, REFUSED = "stored", "link expired", "refused"


def put(url: str, path: Path, md5: str) -> str:
    """Uploads one object of a page to its signed link, retrying when the storage cannot be reached"""
    headers = {"Content-MD5": md5, "Content-Type": result_format.content_type(path.name)}
    for attempt in range(ATTEMPTS):
        req = request.Request(url, path.read_bytes(), headers, method="PUT")
        try:
            with request.urlopen(req, context=CONTEXT, timeout=300) as response:  # skipcq: BAN-B310
                return STORED if response.status == 200 else REFUSED
        except error.HTTPError as http_error:
            if http_error.code == 403:
                # links last minutes; a long upload gets new ones
                return LINK_EXPIRED
            if not transient(http_error.code):
                logging.error("Upload refused: %d %s", http_error.code, http_error.read()[:500])
                return REFUSED
            logging.warning("Upload answered %d", http_error.code)
        except (OSError, HTTPException) as connection_error:
            logging.warning("Upload failed: %s", connection_error)
        if attempt < ATTEMPTS - 1:
            pause(attempt)
    return REFUSED


# what upload() can end with
UPLOADED, NO_STORAGE, FAILED, AGAIN, NOT_RUNNING = "uploaded", "no storage", "failed", "again", "not running"


class Upload:
    """The merged results being uploaded: their manifest, where the pages are, and the revision the backend named"""

    def __init__(self, manifest: dict, pages_dir: Path, args):
        """args: sim_id, update_key, backend_url and partial"""
        self.manifest = manifest
        self.pages_dir = pages_dir
        self.args = args
        self.revision: Optional[str] = None

    def payload(self, **content) -> dict:
        """A request body to the backend"""
        payload = {"simulation_id": self.args.sim_id, "update_key": self.args.update_key, **content}
        if self.revision:
            payload["revision"] = self.revision
        if getattr(self.args, "partial", False):
            payload.update(partial=True, primaries=int(self.manifest.get("primaries", 0)))
        return payload

    def entries(self, wanted: set) -> List[dict]:
        """The pages to upload: estimator, page number and objects of each"""
        return [
            {"estimator": estimator["name"], "page_number": page["page_number"], "files": page["files"]}
            for estimator in self.manifest["estimators"]
            for page in estimator["pages"]
            if (estimator["name"], page["page_number"]) in wanted
        ]

    def upload(self, wanted: set) -> str:
        """Uploads the wanted pages ((estimator, page number) pairs)"""
        entries = self.entries(wanted)
        status, answer = post(f"{self.args.backend_url}/results/uploads", self.payload(pages=entries))
        if status == 501:
            return NO_STORAGE
        if status == 409 and getattr(self.args, "partial", False):
            return NOT_RUNNING
        if status != 200:
            logging.error("Upload links refused: %d %s", status, answer)
            return FAILED
        self.revision = answer.get("revision")
        for link in answer["uploads"]:
            page_id = (link["estimator"], link["page_number"])
            files = next(entry["files"] for entry in entries if (entry["estimator"], entry["page_number"]) == page_id)
            for name, url in link["files"].items():
                path = self.pages_dir / link["estimator"] / str(link["page_number"]) / name
                stored = put(url, path, files[name]["md5"])
                if stored == LINK_EXPIRED:
                    return AGAIN
                if stored == REFUSED:
                    return FAILED
            wanted.discard(page_id)
        return UPLOADED

    def done(self) -> Tuple[int, dict]:
        """Tells the backend what was uploaded"""
        return post(f"{self.args.backend_url}/results/done", self.payload(estimators=self.manifest["estimators"]))

    def json_estimators(self) -> List[dict]:
        """The estimators with their pages as JSON, for a backend without object storage"""
        estimators = []
        for estimator in self.manifest["estimators"]:
            pages = []
            for page in estimator["pages"]:
                page_dir = self.pages_dir / estimator["name"] / str(page["page_number"])
                files = {name: (page_dir / name).read_bytes() for name in page["files"]}
                pages.append(result_format.json_page(*result_format.read_page(files)))
            estimators.append({"name": estimator["name"], "metadata": estimator["metadata"], "pages": pages})
        return estimators


def send_old_way(upload: Upload, args) -> bool:
    """A backend without object storage takes the final results in one request, as before"""
    status, _ = post(
        f"{args.backend_url}/results",
        {"simulation_id": args.sim_id, "update_key": args.update_key, "estimators": upload.json_estimators()},
    )
    return status == 202


def main(args) -> int:
    """Uploads the results and reports them done; a failure exits non-zero, the collect job then reports FAILED.
    Partial results the backend no longer takes (the simulation ended) are no failure.
    """
    manifest, pages_dir = read_results(Path(args.output_dir))
    if not manifest["estimators"]:
        logging.error("No results in %s", args.output_dir)
        return 1
    upload = Upload(manifest, pages_dir, args)
    partial = getattr(args, "partial", False)
    wanted = {
        (estimator["name"], page["page_number"]) for estimator in manifest["estimators"] for page in estimator["pages"]
    }
    for _ in range(ROUNDS):
        uploaded = upload.upload(wanted)
        for _ in range(ROUNDS):
            if uploaded != AGAIN:
                break
            # what is left of wanted, with new links
            uploaded = upload.upload(wanted)
        if uploaded == AGAIN:
            # every new link refused too (e.g. a clock far off on this node)
            return 1
        if uploaded == NOT_RUNNING:
            return 0
        if uploaded == NO_STORAGE:
            if partial:
                logging.info("No object storage on the backend: no partial results")
                return 0
            return 0 if send_old_way(upload, args) else 1
        if uploaded == FAILED:
            return 1
        status, answer = upload.done()
        if status == 202:
            return 0
        if status == 409 and "missing" not in answer and partial:
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
    parser.add_argument("--attempts", type=int, default=ATTEMPTS)
    parser.add_argument("--partial", action="store_true", help="partial results of a running simulation")
    parsed = parser.parse_args()
    ATTEMPTS = parsed.attempts
    sys.exit(main(parsed))
