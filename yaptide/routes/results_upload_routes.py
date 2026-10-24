"""Results of HPC jobs go straight from the cluster to object storage; the backend hands out links and checks them

The cluster merges the tasks' results into pages itself (yaptide/batch/results_merger.py): the collect job at the end,
the tasks along the way for partial results ("partial": true, with the primaries merged). It asks for one signed upload
link per object of each page (POST /results/uploads), uploads them, then reports what it uploaded (POST
/results/done). The backend checks every object is in storage before it stores the results; final results mark the
simulation completed, partial ones are stored only while it runs. A page missing is listed in the answer, for the job to
upload again.

A page in ZARR_FORMAT lists its objects ("files": name -> size and md5) and goes under a revision the first answer
names (the job sends it back to ask for links again); a job submitted before lists a gzipped JSON page with its size
and md5 instead.
"""

import base64

from flask import request
from flask_restful import Resource

from yaptide.batch import result_format
from yaptide.persistence import result_storage
from yaptide.persistence.database import db
from yaptide.persistence.db_methods import fetch_simulation_by_sim_id, update_simulation_state
from yaptide.persistence.models import SimulationModel
from yaptide.routes.common_sim_routes import lock_results, store_partial_results, store_results
from yaptide.routes.utils.response_templates import yaptide_response
from yaptide.routes.utils.tokens import decode_auth_token
from yaptide.routes.utils.utils import FINAL_STATES
from yaptide.utils.enums import EntityState
from yaptide.utils.sim_utils import is_plain_filename


def authorized_simulation(payload: dict):
    """The simulation the update key in the payload was issued for, or the error response"""
    if not isinstance(payload, dict) or not {"simulation_id", "update_key"} <= set(payload):
        return None, yaptide_response(message="simulation_id and update_key are required", code=400)
    simulation: SimulationModel = fetch_simulation_by_sim_id(sim_id=payload["simulation_id"])
    if simulation is None:
        return None, yaptide_response(message="Simulation does not exist", code=400)
    if decode_auth_token(payload["update_key"], payload_key_to_return="simulation_id") != simulation.id:
        return None, yaptide_response(message="Invalid update key", code=400)
    if simulation.job_state in FINAL_STATES:
        return None, yaptide_response(message=f"Simulation is {simulation.job_state}", code=409)
    if not result_storage.configured():
        # the job sends its results the old way, through POST /results
        return None, yaptide_response(message="No results storage on this server", code=501)
    return simulation, None


# pages of one simulation in one request; far more than any result so far, few enough to answer in seconds
MAX_PAGES = 10_000


def valid_name(name) -> bool:
    """A plain estimator name: it becomes a part of the object key"""
    return isinstance(name, str) and is_plain_filename(name) and name != "."


def valid_md5(md5) -> bool:
    """The base64 MD5 of a page, as the Content-MD5 header carries it"""
    try:
        return isinstance(md5, str) and len(base64.b64decode(md5, validate=True)) == 16
    except ValueError:  # binascii.Error is one
        return False


def valid_object(entry) -> bool:
    """Size and MD5 of an uploaded object"""
    return (
        isinstance(entry, dict) and type(entry.get("size")) is int and entry["size"] > 0 and valid_md5(entry.get("md5"))
    )


def valid_files(files) -> bool:
    """The objects of a page in ZARR_FORMAT: its metadata, and its shard unless it has no values"""
    return (
        isinstance(files, dict)
        and result_format.METADATA_FILE in files
        and set(files) <= set(result_format.FILES)
        and all(valid_object(entry) for entry in files.values())
    )


def valid_page(page: dict) -> bool:
    """A page entry: its estimator's name, its number, and its objects (ZARR_FORMAT) or its size and MD5 (a gzipped
    JSON page)
    """
    return (
        isinstance(page, dict)
        and valid_name(page.get("estimator"))
        # bool is an int too, and would become a key like .../True.json
        and type(page.get("page_number")) is int
        and page["page_number"] >= 0
        and (valid_files(page["files"]) if "files" in page else valid_object(page))
    )


def revision_of(payload: dict):
    """The revision the job sent back, a new one if none; None for an invalid one"""
    revision = payload.get("revision")
    if revision is None:
        return result_storage.new_revision()
    if isinstance(revision, str) and result_storage.REVISION_PATTERN.fullmatch(revision):
        return revision
    return None


def page_objects(simulation_id: int, page: dict, revision: str) -> dict[str, str]:
    """Where the objects of a page entry go: name -> key; a gzipped JSON page is one object, named ""."""
    if "files" not in page:
        return {"": result_storage.page_key(simulation_id, page["estimator"], page["page_number"])}
    prefix = result_storage.page_prefix(simulation_id, page["estimator"], page["page_number"], revision)
    return {name: prefix + name for name in page["files"]}


def upload_links(simulation_id: int, page: dict, revision: str) -> dict:
    """The upload links of a page entry"""
    keys = page_objects(simulation_id, page, revision)
    link = {"estimator": page["estimator"], "page_number": page["page_number"]}
    if "files" not in page:
        return dict(link, url=result_storage.upload_url(keys[""], page["size"], page["md5"]))
    files = {
        name: result_storage.upload_url(
            key, page["files"][name]["size"], page["files"][name]["md5"], result_format.content_type(name)
        )
        for name, key in keys.items()
    }
    return dict(link, files=files)


def valid_partial(payload: dict) -> bool:
    """Whether partial results come with the primaries merged"""
    if not payload.get("partial"):
        return True
    primaries = payload.get("primaries")
    return type(primaries) is int and primaries >= 0


class ResultsUploadsResource(Resource):
    """Signed upload links for the pages of an HPC simulation's results"""

    @staticmethod
    def post():
        """Body: simulation_id, update_key, partial (optional), revision (optional, as the first answer named it) and
        pages - estimator, page_number and the files of each (name -> size and md5, base64), or size and md5 of a
        gzipped JSON page
        """
        payload = request.get_json(force=True)
        simulation, error = authorized_simulation(payload)
        if error:
            return error
        pages = payload.get("pages")
        if not isinstance(pages, list) or not 0 < len(pages) <= MAX_PAGES or not all(valid_page(p) for p in pages):
            return yaptide_response(message="pages: estimator, page_number and files of each", code=400)
        revision = revision_of(payload)
        if revision is None:
            return yaptide_response(message="Invalid revision", code=400)
        if payload.get("partial"):
            # stored only while the simulation runs (POST /results/done): no state changes here
            if simulation.job_state != EntityState.RUNNING.value:
                return yaptide_response(message=f"Simulation is {simulation.job_state}", code=409)
        else:
            # partial results stored meanwhile are waited for, and none is stored after this (they take a RUNNING
            # simulation), so they cannot replace the final ones
            lock_results(simulation)
            if simulation.job_state == EntityState.RUNNING.value:
                update_simulation_state(simulation, {"job_state": EntityState.MERGING_RUNNING.value})
            db.session.commit()
        uploads = [upload_links(simulation.id, page, revision) for page in pages]
        return yaptide_response(message="Upload links", code=200, content={"uploads": uploads, "revision": revision})


def valid_estimators(estimators) -> bool:
    """A list of estimators, each with a plain name and a list of pages, not too many pages in all"""
    return (
        isinstance(estimators, list)
        and bool(estimators)
        and all(
            isinstance(e, dict) and valid_name(e.get("name")) and isinstance(e.get("pages"), list) for e in estimators
        )
        and sum(len(estimator["pages"]) for estimator in estimators) <= MAX_PAGES
    )


def check_pages(simulation_id: int, estimator: dict, revision: str) -> tuple[list[dict], list[dict]]:
    """The estimator's pages found in storage, as store_results takes them, and the ones missing there

    Raises ValueError for an invalid page entry.
    """
    stored, missing = [], []
    for page in estimator["pages"]:
        entry = {**page, "estimator": estimator["name"]} if isinstance(page, dict) else None
        if not valid_page(entry) or ("files" in entry and revision is None):
            raise ValueError("Invalid page entry")
        keys = page_objects(simulation_id, entry, revision)
        objects = entry.get("files") or {"": entry}
        if not all(
            result_storage.stored_matches(key, objects[name]["size"], objects[name]["md5"])
            for name, key in keys.items()
        ):
            missing.append({"estimator": entry["estimator"], "page_number": entry["page_number"]})
            continue
        if "files" in entry:
            pointer = {
                "key": result_storage.page_prefix(simulation_id, entry["estimator"], entry["page_number"], revision),
                "size": sum(item["size"] for item in entry["files"].values()),
                "format": result_storage.ZARR_FORMAT,
            }
        else:
            pointer = {"key": keys[""], "size": entry["size"], "format": result_storage.PAGE_FORMAT}
        stored.append(
            {
                "metadata": {"page_number": entry["page_number"], "name": page.get("name", "")},
                "dimensions": page.get("dimensions", 0),
                "stored": pointer,
            }
        )
    return stored, missing


class ResultsDoneResource(Resource):
    """The cluster job uploaded the results: checked, stored and the simulation completed"""

    @staticmethod
    def post():
        """Body: simulation_id, update_key, revision (of pages in ZARR_FORMAT), partial and primaries (optional) and
        estimators - name, metadata and pages (page_number, name, dimensions and files, or size and md5) of each, as
        the job uploaded them
        """
        payload = request.get_json(force=True)
        simulation, error = authorized_simulation(payload)
        if error:
            return error
        estimators = payload.get("estimators")
        if not valid_estimators(estimators):
            return yaptide_response(message="estimators: name and pages of each", code=400)
        if not valid_partial(payload):
            return yaptide_response(message="partial results need the primaries merged", code=400)
        revision = payload.get("revision")
        if revision is not None and not result_storage.REVISION_PATTERN.fullmatch(str(revision)):
            return yaptide_response(message="Invalid revision", code=400)
        missing, results = [], []
        for estimator in sorted(estimators, key=lambda estimator: estimator["name"]):
            try:
                pages, missing_pages = check_pages(simulation.id, estimator, revision)
            except ValueError as invalid:
                return yaptide_response(message=str(invalid), code=400)
            missing.extend(missing_pages)
            results.append({"name": estimator["name"], "metadata": estimator.get("metadata", {}), "pages": pages})
        if missing:
            return yaptide_response(message="Pages missing in storage", code=409, content={"missing": missing})
        if payload.get("partial"):
            if not store_partial_results(simulation, results, payload["primaries"]):
                return yaptide_response(message=f"Simulation is {simulation.job_state}", code=409)
            return yaptide_response(message="Partial results saved", code=202)
        store_results(simulation, results)
        return yaptide_response(message="Results saved", code=202)
