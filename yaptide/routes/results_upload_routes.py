"""Results of HPC jobs go straight from the cluster to object storage; the backend hands out links and checks them

The collect job asks for one signed upload link per page (POST /results/uploads), and per full resolution file of an
estimator whose pages were downsampled, uploads them, then reports what it uploaded (POST /results/done). The backend
checks every page (and file) is in storage before it stores the results and marks the simulation completed; one
missing is listed in the answer, for the job to upload again.
"""

import base64

from flask import request
from flask_restful import Resource

from yaptide.batch.results_uploader import MAX_FULL_RESOLUTION_BYTES
from yaptide.persistence import result_storage
from yaptide.persistence.database import db
from yaptide.persistence.db_methods import fetch_simulation_by_sim_id, update_simulation_state
from yaptide.persistence.models import SimulationModel
from yaptide.routes.common_sim_routes import lock_results, store_results
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


def valid_page(page: dict) -> bool:
    """A page entry: its estimator's name, its number, size and MD5"""
    return (
        isinstance(page, dict)
        and valid_name(page.get("estimator"))
        # bool is an int too, and would become a key like .../True.json
        and type(page.get("page_number")) is int
        and page["page_number"] >= 0
        and type(page.get("size")) is int
        and page["size"] > 0
        and valid_md5(page.get("md5"))
    )


def valid_full_resolution(entry: dict) -> bool:
    """A full resolution entry: its estimator's name, size (within what a link may upload) and MD5"""
    return (
        isinstance(entry, dict)
        and valid_name(entry.get("estimator"))
        and type(entry.get("size")) is int
        and 0 < entry["size"] <= MAX_FULL_RESOLUTION_BYTES
        and valid_md5(entry.get("md5"))
    )


class ResultsUploadsResource(Resource):
    """Signed upload links for the pages of an HPC simulation's results"""

    @staticmethod
    def post():
        """Body: simulation_id, update_key and pages - estimator, page_number, size and md5 (base64) of each; and
        full_resolution - estimator, size and md5 of each full resolution file (optional)
        """
        payload = request.get_json(force=True)
        simulation, error = authorized_simulation(payload)
        if error:
            return error
        pages = payload.get("pages")
        full = payload.get("full_resolution", [])
        if (
            not isinstance(pages, list)
            or not isinstance(full, list)
            or not 0 < len(pages) + len(full) <= MAX_PAGES
            or not all(valid_page(p) for p in pages)
            or not all(valid_full_resolution(f) for f in full)
        ):
            return yaptide_response(message="pages: estimator, page_number, size and md5 of each", code=400)
        # partial results the engine merges go to the same pages: one being stored is waited for, and none is stored
        # after this (it takes a RUNNING simulation), so it cannot replace a page uploaded with these links
        lock_results(simulation)
        if simulation.job_state == EntityState.RUNNING.value:
            update_simulation_state(simulation, {"job_state": EntityState.MERGING_RUNNING.value})
        db.session.commit()
        uploads = [
            {
                "estimator": page["estimator"],
                "page_number": page["page_number"],
                "url": result_storage.upload_url(
                    result_storage.page_key(simulation.id, page["estimator"], page["page_number"]),
                    page["size"],
                    page["md5"],
                ),
            }
            for page in pages
        ]
        full_uploads = [
            {
                "estimator": entry["estimator"],
                "url": result_storage.upload_url(
                    result_storage.full_resolution_key(simulation.id, entry["estimator"]),
                    entry["size"],
                    entry["md5"],
                    page=False,
                ),
            }
            for entry in full
        ]
        content = {"uploads": uploads, "full_resolution_uploads": full_uploads}
        return yaptide_response(message="Upload links", code=200, content=content)


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


def check_pages(simulation_id: int, estimator: dict) -> tuple[list[dict], list[dict]]:
    """The estimator's pages found in storage, as store_results takes them, and the ones missing there

    Raises ValueError for an invalid page entry.
    """
    stored, missing = [], []
    for page in estimator["pages"]:
        entry = {**page, "estimator": estimator["name"]} if isinstance(page, dict) else None
        if not valid_page(entry):
            raise ValueError("Invalid page entry")
        key = result_storage.page_key(simulation_id, entry["estimator"], entry["page_number"])
        if not result_storage.stored_matches(key, entry["size"], entry["md5"]):
            missing.append({"estimator": entry["estimator"], "page_number": entry["page_number"]})
            continue
        stored.append(
            {
                "metadata": {"page_number": entry["page_number"], "name": page.get("name", "")},
                "dimensions": page.get("dimensions", 0),
                "stored": {"key": key, "size": entry["size"]},
            }
        )
    return stored, missing


class ResultsDoneResource(Resource):
    """The cluster job uploaded the results: checked, stored and the simulation completed"""

    @staticmethod
    def post():
        """Body: simulation_id, update_key and estimators - name, metadata and pages (page_number, name,
        dimensions, size, md5) of each, and full_resolution (size, md5) of one with it, as the job uploaded them
        """
        payload = request.get_json(force=True)
        simulation, error = authorized_simulation(payload)
        if error:
            return error
        estimators = payload.get("estimators")
        if not valid_estimators(estimators):
            return yaptide_response(message="estimators: name and pages of each", code=400)
        missing, results, full_resolution = [], [], set()
        for estimator in sorted(estimators, key=lambda estimator: estimator["name"]):
            try:
                pages, missing_pages = check_pages(simulation.id, estimator)
            except ValueError as invalid:
                return yaptide_response(message=str(invalid), code=400)
            missing.extend(missing_pages)
            result = {"name": estimator["name"], "metadata": estimator.get("metadata", {}), "pages": pages}
            full = estimator.get("full_resolution")
            if full is not None:
                entry = {**full, "estimator": estimator["name"]} if isinstance(full, dict) else None
                if not valid_full_resolution(entry):
                    return yaptide_response(message="Invalid full resolution entry", code=400)
                key = result_storage.full_resolution_key(simulation.id, estimator["name"])
                if result_storage.stored_matches(key, entry["size"], entry["md5"]):
                    full_resolution.add(estimator["name"])
                else:
                    missing.append({"estimator": estimator["name"], "full_resolution": True})
            results.append(result)
        if missing:
            return yaptide_response(message="Pages missing in storage", code=409, content={"missing": missing})
        store_results(simulation, results, frozenset(full_resolution))
        return yaptide_response(message="Results saved", code=202)
