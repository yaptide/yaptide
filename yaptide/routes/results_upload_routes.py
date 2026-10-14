"""Results of HPC jobs go straight from the cluster to object storage; the backend hands out links and checks them

The collect job asks for one signed upload link per page (POST /results/uploads), uploads the gzipped pages, then
reports what it uploaded (POST /results/done). The backend checks every page is in storage before it stores the
results and marks the simulation completed; a page missing is listed in the answer, for the job to upload again.
"""

from flask import request
from flask_restful import Resource

from yaptide.persistence import result_storage
from yaptide.persistence.db_methods import fetch_simulation_by_sim_id
from yaptide.persistence.models import SimulationModel
from yaptide.routes.common_sim_routes import store_results
from yaptide.routes.utils.response_templates import yaptide_response
from yaptide.routes.utils.tokens import decode_auth_token
from yaptide.routes.utils.utils import FINAL_STATES
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


def valid_page(page: dict) -> bool:
    """A page entry: a plain estimator name (it becomes a part of the object key), its number, size and MD5"""
    return (
        isinstance(page, dict)
        and isinstance(page.get("estimator"), str)
        and is_plain_filename(page["estimator"])
        and page["estimator"] != "."
        and isinstance(page.get("page_number"), int)
        and isinstance(page.get("size"), int)
        and page["size"] > 0
        and isinstance(page.get("md5"), str)
    )


class ResultsUploadsResource(Resource):
    """Signed upload links for the pages of an HPC simulation's results"""

    @staticmethod
    def post():
        """Body: simulation_id, update_key and pages - estimator, page_number, size and md5 (base64) of each"""
        payload = request.get_json(force=True)
        simulation, error = authorized_simulation(payload)
        if error:
            return error
        pages = payload.get("pages")
        if not isinstance(pages, list) or not pages or not all(valid_page(page) for page in pages):
            return yaptide_response(message="pages: estimator, page_number, size and md5 of each", code=400)
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
        return yaptide_response(message="Upload links", code=200, content={"uploads": uploads})


class ResultsDoneResource(Resource):
    """The cluster job uploaded the results: checked, stored and the simulation completed"""

    @staticmethod
    def post():
        """Body: simulation_id, update_key and estimators - name, metadata and pages (page_number, name,
        dimensions, size, md5) of each, as the job uploaded them
        """
        payload = request.get_json(force=True)
        simulation, error = authorized_simulation(payload)
        if error:
            return error
        estimators = payload.get("estimators")
        if not isinstance(estimators, list) or not estimators:
            return yaptide_response(message="estimators are required", code=400)
        missing, results = [], []
        for estimator in sorted(estimators, key=lambda estimator: estimator.get("name", "")):
            pages = []
            for page in estimator.get("pages", []):
                entry = {**page, "estimator": estimator.get("name")}
                if not valid_page(entry):
                    return yaptide_response(message="Invalid page entry", code=400)
                key = result_storage.page_key(simulation.id, entry["estimator"], entry["page_number"])
                if not result_storage.stored_matches(key, entry["size"], entry["md5"]):
                    missing.append({"estimator": entry["estimator"], "page_number": entry["page_number"]})
                    continue
                pages.append(
                    {
                        "metadata": {"page_number": entry["page_number"], "name": page.get("name", "")},
                        "dimensions": page.get("dimensions", 0),
                        "stored": {"key": key, "size": entry["size"]},
                    }
                )
            results.append({"name": estimator["name"], "metadata": estimator.get("metadata", {}), "pages": pages})
        if missing:
            return yaptide_response(message="Pages missing in storage", code=409, content={"missing": missing})
        store_results(simulation, results)
        return yaptide_response(message="Results saved", code=202)
