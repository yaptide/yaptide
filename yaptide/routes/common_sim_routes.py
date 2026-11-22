import logging
from collections import Counter
from datetime import datetime
from typing import List

from flask import request, current_app as app
from flask_restful import Resource
from marshmallow import Schema, fields
from sqlalchemy import text

from yaptide.persistence.db_methods import (
    add_object_to_db,
    fetch_estimator_by_sim_id_and_est_name,
    fetch_estimator_id_by_sim_id_and_est_name,
    fetch_estimators_by_sim_id,
    fetch_input_by_sim_id,
    fetch_logfiles_by_sim_id,
    fetch_page_by_est_id_and_page_number,
    fetch_pages_by_est_id_and_page_numbers,
    fetch_pages_by_estimator_id,
    fetch_simulation_by_job_id,
    fetch_simulation_by_sim_id,
    fetch_simulation_id_by_job_id,
    fetch_tasks_by_sim_id,
    make_commit_to_db,
    update_simulation_state,
)
from yaptide.batch import result_format
from yaptide.persistence import result_storage
from yaptide.persistence.database import db
from yaptide.persistence.models import (
    EstimatorModel,
    LogfilesModel,
    PageModel,
    PageObjectModel,
    SimulationModel,
    UserModel,
)
from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response
from yaptide.routes.utils.utils import check_if_job_is_owned_and_exist
from yaptide.routes.utils.tokens import decode_auth_token
from yaptide.utils.enums import EntityState, InputType, SimulationType


class JobsResource(Resource):
    """Class responsible for managing common jobs"""

    class APIParametersSchema(Schema):
        """Class specifies API parameters for GET and DELETE request"""

        job_id = fields.String()

    @staticmethod
    @requires_auth()
    def get(user: UserModel):
        """Method returning info about job"""
        schema = JobsResource.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)

        # get job_id from request parameters and check if user owns this job
        job_id = param_dict["job_id"]
        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        simulation = fetch_simulation_by_job_id(job_id=job_id)
        if simulation.job_state == EntityState.UNKNOWN.value:
            return yaptide_response(
                message="Job state is unknown", code=200, content={"job_state": simulation.job_state}
            )

        tasks = fetch_tasks_by_sim_id(sim_id=simulation.id)

        job_tasks_status = [task.get_status_dict() for task in tasks]
        job_tasks_status = sorted(job_tasks_status, key=lambda x: x["task_id"])

        if simulation.job_state in (
            EntityState.COMPLETED.value,
            EntityState.FAILED.value,
            EntityState.MERGING_QUEUED.value,
            EntityState.MERGING_RUNNING.value,
        ):
            return yaptide_response(
                message=f"Job state: {simulation.job_state}",
                code=200,
                content={
                    "job_state": simulation.job_state,
                    "job_tasks_status": job_tasks_status,
                },
            )

        job_info = {"job_state": simulation.job_state}
        status_counter = Counter([task["task_state"] for task in job_tasks_status])
        if status_counter[EntityState.PENDING.value] == len(job_tasks_status):
            job_info["job_state"] = EntityState.PENDING.value
        elif status_counter[EntityState.FAILED.value] == len(job_tasks_status):
            job_info["job_state"] = EntityState.FAILED.value
        elif status_counter[EntityState.RUNNING.value] > 0:
            job_info["job_state"] = EntityState.RUNNING.value
        elif job_id.endswith("BATCH") and status_counter[EntityState.COMPLETED.value] == len(job_tasks_status):
            job_info["job_state"] = EntityState.MERGING_QUEUED.value

        update_simulation_state(simulation=simulation, update_dict=job_info)

        job_info["job_tasks_status"] = job_tasks_status

        return yaptide_response(message=f"Job state: {job_info['job_state']}", code=200, content=job_info)

    @staticmethod
    def post():
        """Handles requests for updating simulation informations in db"""
        payload_dict: dict = request.get_json(force=True)
        sim_id: int = payload_dict["sim_id"]
        app.logger.info(f"sim_id {sim_id}")
        simulation = fetch_simulation_by_sim_id(sim_id=sim_id)

        if not simulation:
            app.logger.info(f"sim_id {sim_id} simulation not found ")
            return yaptide_response(message=f"Simulation {sim_id} does not exist", code=501)

        decoded_token = decode_auth_token(payload_dict["update_key"], payload_key_to_return="simulation_id")
        if decoded_token != sim_id:
            return yaptide_response(message="Invalid update key", code=400)

        update_simulation_state(simulation, payload_dict)
        if payload_dict.get("log"):
            logfiles = LogfilesModel(simulation_id=simulation.id)
            logfiles.data = payload_dict["log"]
            add_object_to_db(logfiles)

        return yaptide_response(message="Task updated", code=202)


def page_content(page: PageModel) -> dict:
    """A page as the UI gets it: signed links to it in object storage, or the page itself for one stored before the
    bucket and not moved there yet (db_manage copy-pages-to-storage)

    A page in object storage comes with a link for each of its objects ("files": zarr.json and the shard c/0); "url"
    is the link of its zarr.json.
    """
    stored = page.stored_object
    if stored:
        files = result_storage.page_file_urls(stored.key)
        return {
            "page_number": page.page_number,
            "name": page.page_name,
            "dimensions": page.page_dimension,
            "format": stored.format,
            "url": files[result_format.METADATA_FILE],
            "files": files,
        }
    return page.data


def get_single_estimator(sim_id: int, estimator_name: str):
    """Retrieve a single estimator by simulation ID and estimator name"""
    estimator = fetch_estimator_by_sim_id_and_est_name(sim_id=sim_id, est_name=estimator_name)

    if not estimator:
        return yaptide_response(message="Estimator not found", code=404)

    pages = fetch_pages_by_estimator_id(est_id=estimator.id)
    estimator_dict = {
        "metadata": estimator.data,
        "name": estimator.name,
        "pages": [page_content(page) for page in pages],
    }
    return yaptide_response(
        message=f"Estimator '{estimator_name}' for simulation: {sim_id}", code=200, content=estimator_dict
    )


def get_all_estimators(sim_id: int):
    """Retrieve all estimators for a given simulation ID, each of an editor simulation with the uuid of the editor
    output it was scored by (none for an estimator no output writes)
    """
    estimators = fetch_estimators_by_sim_id(sim_id=sim_id)
    if len(estimators) == 0:
        return yaptide_response(message="Results are unavailable", code=404)

    logging.debug("Returning results from database")
    outputs = editor_outputs_by_file(fetch_simulation_by_sim_id(sim_id=sim_id))
    result_estimators = []
    for estimator in estimators:
        estimator_dict = {
            "metadata": estimator.data,
            "name": estimator.name,
            "pages": [page_content(page) for page in estimator.pages],
        }
        output = outputs.get(estimator_key(estimator.file_name))
        if output and output.get("uuid"):
            estimator_dict["output_uuid"] = output["uuid"]
        result_estimators.append(estimator_dict)
    return yaptide_response(
        message=f"Results for simulation: {sim_id}", code=200, content={"estimators": result_estimators}
    )


def store_json_page(sim_id: int, estimator: EstimatorModel, page_dict: dict, revision: str) -> PageObjectModel:
    """Stores a page that came with its values (POST /results of a merge) in object storage as Zarr"""
    data = dict(page_dict["data"])
    values = data.pop("values")
    prefix = result_storage.page_prefix(
        sim_id, estimator.file_name, int(page_dict["metadata"]["page_number"]), revision
    )
    size = result_storage.put_page_files(prefix, result_format.page_files(dict(page_dict, data=data), values))
    return PageObjectModel(key=prefix, size=size, format=result_storage.ZARR_FORMAT)


def prepare_create_or_update_pages_in_db(
    sim_id: int, estimator: EstimatorModel, estimator_dict: dict, new_pages: list[str], superseded: list[str]
) -> None:
    """Stores the pages in object storage and prepares their rows, without committing to the database.

    The prefixes of the pages stored go to new_pages (removed again if the rows are not committed), the prefixes of the
    stored pages they replace to superseded (removed once the new ones are committed).
    """
    revision = result_storage.new_revision()
    for page_dict in estimator_dict["pages"]:
        page = fetch_page_by_est_id_and_page_number(
            est_id=estimator.id, page_number=int(page_dict["metadata"]["page_number"])
        )
        page_existed = bool(page)
        if not page_existed:
            page = PageModel(
                page_number=int(page_dict["metadata"]["page_number"]),
                estimator_id=estimator.id,
                page_dimension=int(page_dict["dimensions"]),
                page_name=str(page_dict["metadata"]["name"]),
            )
        old_key = page.stored_object.key if page.stored_object else None
        # we always update the data
        page.stored_object = store_json_page(sim_id, estimator, page_dict, revision)
        page.compressed_data = None
        new_pages.append(page.stored_object.key)
        if old_key:
            superseded.append(old_key)
        if not page_existed:
            # if page was created, we add it to the session
            add_object_to_db(page, make_commit=False)


def lock_results(simulation: SimulationModel) -> None:
    """Waits for results of the simulation stored at the same time (a repeated request), which would both create the
    estimators and pages, then reads the simulation again
    """
    if db.engine.dialect.name == "postgresql":
        db.session.execute(text("SELECT pg_advisory_xact_lock(:simulation_id)"), {"simulation_id": simulation.id})
    db.session.refresh(simulation)


def estimator_key(file_name: str) -> str:
    """An estimator's result file without the trailing underscore the cluster's convertmc adds ("dose_" for dose)"""
    return file_name.rstrip("_")


def editor_outputs_by_file(simulation: SimulationModel) -> dict[str, dict]:
    """The editor's scoring outputs by the estimator key of the result file the converter makes each write to:
    SHIELD-HIT12A files are named after the output, FLUKA ones by the output unit, from 21 for each output the
    converter scores (with a mesh or cylinder detector). Empty for a simulation not from the editor.
    """
    if simulation.input_type != InputType.EDITOR.value:
        return {}
    try:
        input_json = simulation.inputs[0].data["input_json"]
        outputs = input_json["scoringManager"]["outputs"]
        if simulation.sim_type == SimulationType.FLUKA.value:
            detectors = {detector["uuid"]: detector for detector in input_json["detectorManager"]["detectors"]}
            # the detectors converter.fluka.helper_parsers.scoring_parser.parse_detector takes
            scored = [
                output
                for output in outputs
                if detectors.get(output.get("detectorUuid"), {}).get("geometryData", {}).get("geometryType")
                in ("Mesh", "Cyl")
            ]
            return {str(unit): output for unit, output in enumerate(scored, start=21)}
        return {estimator_key(output["name"]): output for output in outputs}
    except (IndexError, KeyError, TypeError):
        logging.warning("Simulation %d has no editor outputs, its estimators keep their file names", simulation.id)
        return {}


def prepare_estimators_and_pages(
    simulation: SimulationModel, estimators: list[dict], new_pages: list[str], superseded: list[str]
) -> None:
    """Prepares the estimators and their pages in place of the stored ones, without committing; the pages go to
    object storage, their prefixes to new_pages, the prefixes of the pages they replace to superseded.

    An estimator is its result file: the editor output writing it gives the name, and the estimator stored for the
    same file before (named with or without the trailing underscore) is updated.
    """
    outputs = editor_outputs_by_file(simulation)
    order = {key: index for index, key in enumerate(outputs)}
    stored = {estimator_key(estimator.file_name): estimator for estimator in fetch_estimators_by_sim_id(simulation.id)}
    # created in the order of the editor outputs, which the results are listed in
    estimators = sorted(estimators, key=lambda estimator: order.get(estimator_key(estimator["name"]), len(order)))
    for estimator_dict in estimators:
        key = estimator_key(estimator_dict["name"])
        name = estimator_dict["name"]
        if key in outputs:
            name = outputs[key]["name"]
        elif outputs:
            logging.error(
                "Estimator %s of simulation %d is written by none of the editor outputs, it keeps its file name",
                estimator_dict["name"],
                simulation.id,
            )
        estimator = stored.get(key)
        if not estimator:
            estimator = EstimatorModel(simulation_id=simulation.id)
            add_object_to_db(estimator, make_commit=False)
        estimator.name = name
        estimator.file_name = estimator_dict["name"]
        estimator.data = estimator_dict["metadata"]
        # the id for the pages
        db.session.flush()
        prepare_create_or_update_pages_in_db(
            sim_id=simulation.id,
            estimator=estimator,
            estimator_dict=estimator_dict,
            new_pages=new_pages,
            superseded=superseded,
        )


def parse_page_numbers(param: str) -> List[int]:
    """Parses string of page ranges (e.g., '1-3,5') and returns a sorted list of page numbers"""
    pages = set()
    for part in param.split(","):
        if "-" in part:
            start, end = map(int, part.split("-"))
            pages.update(range(start, end + 1))
        else:
            pages.add(int(part))
    return sorted(pages)


def store_results(simulation: SimulationModel, estimators: list[dict]) -> bool:
    """Stores the merged results of a simulation: its pages in object storage, the estimators and where the pages
    are in the database. Whether they were stored; on a failure nothing of them is kept
    """
    lock_results(simulation)
    new_pages, superseded = [], []
    try:
        prepare_estimators_and_pages(simulation, estimators, new_pages, superseded)
        # estimators and pages together, so a failure in between does not leave estimators without pages
        make_commit_to_db()
    except Exception:  # skipcq: PYL-W0703
        db.session.rollback()
        logging.exception("Storing the results of simulation %d failed", simulation.id)
        result_storage.delete_pages(new_pages)
        return False
    result_storage.delete_pages(superseded)
    return True


class ResultsResource(Resource):
    """Class responsible for managing results"""

    @staticmethod
    def post():
        """
        Method for saving results
        Used by the jobs at the end of simulation
        Structure required by this method to work properly:
        {
            "simulation_id": <int>,
            "update_key": <string>,
            "estimators": <dict>
        }
        """
        payload_dict: dict = request.get_json(force=True)
        if {"simulation_id", "update_key", "estimators"} != set(payload_dict.keys()):
            return yaptide_response(message="Incomplete JSON data", code=400)

        sim_id = payload_dict["simulation_id"]
        simulation = fetch_simulation_by_sim_id(sim_id=sim_id)

        if not simulation:
            return yaptide_response(message="Simulation does not exist", code=400)

        decoded_token = decode_auth_token(payload_dict["update_key"], payload_key_to_return="simulation_id")
        if decoded_token != sim_id:
            return yaptide_response(message="Invalid update key", code=400)

        if not store_results(simulation, payload_dict["estimators"]):
            return yaptide_response(message="Storing results failed", code=500)

        logging.debug("Marking simulation as completed")
        update_dict = {"job_state": EntityState.COMPLETED.value, "end_time": datetime.utcnow().isoformat(sep=" ")}
        update_simulation_state(simulation=simulation, update_dict=update_dict)

        logging.debug("Marking simulation tasks as completed")

        return yaptide_response(message="Results saved", code=202)

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String()
        estimator_name = fields.String(load_default=None)
        page_number = fields.Integer(load_default=None)
        page_numbers = fields.String(load_default=None)

    @staticmethod
    @requires_auth()
    def get(user: UserModel):
        """Method returning job status and results.
        If `estimator_name` parameter is provided,
        the response will include results only for that specific estimator,
        otherwise it will return all estimators for the given job.
        If `page_number` or `page_numbers` are provided, the response will include only specific pages.
        """
        schema = ResultsResource.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)

        job_id = param_dict["job_id"]
        estimator_name = param_dict["estimator_name"]
        page_number = param_dict.get("page_number")
        page_numbers = param_dict.get("page_numbers")

        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        simulation_id = fetch_simulation_id_by_job_id(job_id=job_id)
        if not simulation_id:
            return yaptide_response(message="Simulation does not exist", code=404)

        # if estimator name is provided, return specific estimator
        if estimator_name is None:
            return get_all_estimators(sim_id=simulation_id)

        if page_number is None and page_numbers is None:
            return get_single_estimator(sim_id=simulation_id, estimator_name=estimator_name)

        estimator_id = fetch_estimator_id_by_sim_id_and_est_name(sim_id=simulation_id, est_name=estimator_name)
        if page_number is not None:
            page = fetch_page_by_est_id_and_page_number(est_id=estimator_id, page_number=page_number)
            result = {"page": page_content(page)}
            return yaptide_response(message="Page retrieved successfully", code=200, content=result)

        if page_numbers is not None:
            parsed_page_numbers = parse_page_numbers(page_numbers)
            pages = fetch_pages_by_est_id_and_page_numbers(est_id=estimator_id, page_numbers=parsed_page_numbers)
            result = {"pages": [page_content(page) for page in pages]}
            return yaptide_response(message="Pages retrieved successfully", code=200, content=result)
        return yaptide_response(message="Wrong parameters", code=400, content=errors)


class InputsResource(Resource):
    """Class responsible for returning simulation input"""

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String()

    @staticmethod
    @requires_auth()
    def get(user: UserModel):
        """Method returning simulation input"""
        schema = InputsResource.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)
        job_id = param_dict["job_id"]

        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        simulation = fetch_simulation_by_job_id(job_id=job_id)

        input_model = fetch_input_by_sim_id(sim_id=simulation.id)
        if not input_model:
            return yaptide_response(message="Input of simulation is unavailable", code=404)

        return yaptide_response(message="Input of simulation", code=200, content={"input": input_model.data})


class LogfilesResource(Resource):
    """Class responsible for managing logfiles"""

    @staticmethod
    def post():
        """
        Method for saving logfiles
        Used by the jobs when the simulation fails
        Structure required by this method to work properly:
        {
            "simulation_id": <int>,
            "update_key": <string>,
            "logfiles": <dict>
        }
        """
        payload_dict: dict = request.get_json(force=True)
        if {"simulation_id", "update_key", "logfiles"} != set(payload_dict.keys()):
            return yaptide_response(message="Incomplete JSON data", code=400)

        sim_id = payload_dict["simulation_id"]
        simulation = fetch_simulation_by_sim_id(sim_id=sim_id)

        if not simulation:
            return yaptide_response(message="Simulation does not exist", code=400)

        decoded_token = decode_auth_token(payload_dict["update_key"], payload_key_to_return="simulation_id")
        if decoded_token != sim_id:
            return yaptide_response(message="Invalid update key", code=400)

        logfiles = LogfilesModel(simulation_id=simulation.id)
        logfiles.data = payload_dict["logfiles"]
        add_object_to_db(logfiles)

        return yaptide_response(message="Log files saved", code=202)

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String()

    @staticmethod
    @requires_auth()
    def get(user: UserModel):
        """Method returning job status and results"""
        schema = ResultsResource.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        param_dict: dict = schema.load(request.args)

        job_id = param_dict["job_id"]
        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(job_id=job_id, user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)

        simulation = fetch_simulation_by_job_id(job_id=job_id)

        logfile = fetch_logfiles_by_sim_id(sim_id=simulation.id)
        if not logfile:
            return yaptide_response(message="Logfiles are unavailable", code=404)

        logging.debug("Returning logfiles from database")

        return yaptide_response(message="Logfiles", code=200, content={"logfiles": logfile.data})
