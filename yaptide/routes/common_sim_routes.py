import logging
from datetime import datetime, timezone
from typing import List

from flask import redirect, request, current_app as app
from flask_restful import Resource
from sqlalchemy import text
from marshmallow import Schema, fields

from yaptide.persistence.db_methods import (
    add_object_to_db,
    fetch_estimator_by_sim_id_and_est_name,
    fetch_estimators_by_sim_id,
    fetch_input_by_sim_id,
    fetch_logfiles_by_sim_id,
    fetch_page_by_est_id_and_page_number,
    fetch_pages_by_est_id_and_page_numbers,
    fetch_pages_by_estimator_id,
    fetch_simulation_by_job_id,
    fetch_simulation_by_sim_id,
    fetch_simulation_id_by_job_id,
    note_watching,
    make_commit_to_db,
    update_simulation_state,
)
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
from yaptide.routes.utils.utils import FINAL_STATES, check_if_job_is_owned_and_exist, job_status_content
from yaptide.routes.utils.tokens import decode_auth_token
from yaptide.utils.enums import EntityState, InputType, SimulationType


class JobsResource(Resource):
    """Class responsible for managing common jobs"""

    class APIParametersSchema(Schema):
        """Class specifies API parameters for GET and DELETE request"""

        job_id = fields.String()
        # the UI needs only the totals; the list of tasks stays the default for older clients
        tasks = fields.Boolean(load_default=True)

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

        # a read only: the state follows the tasks when they report, not when someone looks
        content = job_status_content(simulation, with_tasks=param_dict["tasks"])
        message = f"Job state: {simulation.job_state}"
        # the UI asks while it cannot open the status stream: the progress of the user's simulations is read often
        note_watching(user.id)
        return yaptide_response(message=message, code=200, content=content)

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

        # a job only says it merges or failed: the rest (the job directory, job ids, a cancel) is the engine's,
        # and a job directory taken from here would end up in a command run on the cluster
        job_state = payload_dict.get("job_state")
        if job_state not in JOB_REPORTED_STATES:
            return yaptide_response(message=f"Jobs report only {', '.join(JOB_REPORTED_STATES)}", code=400)
        update_dict = {"job_state": job_state}
        if job_state == EntityState.FAILED.value:
            update_dict["end_time"] = datetime.utcnow().isoformat(sep=" ")
        update_simulation_state(simulation, update_dict)
        # the first reason only: the collect job and the reporter job may both report the same failure
        if payload_dict.get("log") and fetch_logfiles_by_sim_id(sim_id=simulation.id) is None:
            logfiles = LogfilesModel(simulation_id=simulation.id)
            logfiles.data = payload_dict["log"]
            add_object_to_db(logfiles)

        return yaptide_response(message="Task updated", code=202)


# the states a simulation's own jobs may report (POST /jobs)
JOB_REPORTED_STATES = (EntityState.MERGING_RUNNING.value, EntityState.FAILED.value)


def page_content(page: PageModel) -> dict:
    """A page as the UI gets it: the page itself, or a signed link to it in object storage"""
    if page.stored_object:
        return {
            "page_number": page.page_number,
            "url": result_storage.page_url(page.stored_object.key),
            "format": page.stored_object.format,
        }
    return page.data


# the estimator's metadata says its full resolution is stored (result_storage.full_resolution_key); set by the server
# only, as a flag: the key is always made from the simulation and the estimator, never read from stored data
FULL_RESOLUTION = "full_resolution"


def estimator_content(estimator: EstimatorModel, pages: list[PageModel]) -> dict:
    """An estimator as the UI gets it; one whose pages were downsampled for the UI says it has its full resolution
    to download (GET /results/full_resolution)
    """
    metadata = dict(estimator.data)
    metadata.pop(FULL_RESOLUTION, None)
    content = {"metadata": metadata, "name": estimator.name, "pages": [page_content(page) for page in pages]}
    return with_full_resolution(content, estimator)


def with_full_resolution(content: dict, estimator: EstimatorModel) -> dict:
    """The content saying the estimator's full resolution can be downloaded, when it can"""
    if estimator.data.get(FULL_RESOLUTION) is True and result_storage.configured():
        content[FULL_RESOLUTION] = True
    return content


def get_single_estimator(sim_id: int, estimator_name: str):
    """Retrieve a single estimator by simulation ID and estimator name"""
    estimator = fetch_estimator_by_sim_id_and_est_name(sim_id=sim_id, est_name=estimator_name)

    if not estimator:
        return yaptide_response(message="Estimator not found", code=404)

    estimator_dict = estimator_content(estimator, fetch_pages_by_estimator_id(est_id=estimator.id))
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
        estimator_dict = estimator_content(estimator, estimator.pages)
        output = outputs.get(estimator_key(estimator.file_name))
        if output and output.get("uuid"):
            estimator_dict["output_uuid"] = output["uuid"]
        result_estimators.append(estimator_dict)
    return yaptide_response(
        message=f"Results for simulation: {sim_id}", code=200, content={"estimators": result_estimators}
    )


def prepare_create_or_update_pages_in_db(
    sim_id: int, estimator: EstimatorModel, estimator_dict: dict, use_storage: bool
) -> bool:
    """Prepares page objects for insertion or update without committing to the database.

    Pages go to object storage while it accepts them and to the database otherwise, so an outage of the storage
    does not lose the results; returns whether the storage is still used for the next pages.
    """
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
        # we always update the data
        if "stored" in page_dict:
            # uploaded straight to storage by a cluster job and checked there (yaptide/routes/results_upload_routes.py)
            page.compressed_data = None
            page.stored_object = PageObjectModel(
                key=page_dict["stored"]["key"], size=page_dict["stored"]["size"], format=result_storage.PAGE_FORMAT
            )
        else:
            if use_storage:
                key = result_storage.page_key(sim_id, estimator.file_name, page.page_number)
                try:
                    size = result_storage.put_page(key, page_dict)
                    page.compressed_data = None
                    page.stored_object = PageObjectModel(key=key, size=size, format=result_storage.PAGE_FORMAT)
                except Exception:  # skipcq: PYL-W0703
                    logging.exception("Storing results of simulation %d failed, the rest goes to the database", sim_id)
                    use_storage = False
            if not use_storage:
                page.data = page_dict
                page.stored_object = None
        if not page_existed:
            # if page was created, we add it to the session
            add_object_to_db(page, make_commit=False)
    return use_storage


def lock_results(simulation: SimulationModel) -> None:
    """Waits for results of the simulation stored at the same time (a repeated request, partial and final results),
    which would both create the estimators and pages, then reads the simulation again
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
    simulation: SimulationModel, estimators: list[dict], full_resolution: frozenset = frozenset()
) -> None:
    """Prepares the estimators and their pages in place of the stored ones, without committing.

    An estimator is its result file: the editor output writing it gives the name, and the estimator stored for the
    same file before (partial results, named with or without the trailing underscore) is updated. The estimators
    named in full_resolution have theirs in storage, as the server checked.
    """
    outputs = editor_outputs_by_file(simulation)
    order = {key: index for index, key in enumerate(outputs)}
    stored = {estimator_key(estimator.file_name): estimator for estimator in fetch_estimators_by_sim_id(simulation.id)}
    # created in the order of the editor outputs, which the results are listed in
    estimators = sorted(estimators, key=lambda estimator: order.get(estimator_key(estimator["name"]), len(order)))
    use_storage = result_storage.configured()
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
        # the metadata comes from the job: the flag is the server's alone
        sent = estimator_dict.get("metadata")
        metadata = (
            {key: value for key, value in sent.items() if key != FULL_RESOLUTION} if isinstance(sent, dict) else {}
        )
        if estimator_dict["name"] in full_resolution:
            metadata[FULL_RESOLUTION] = True
        estimator.data = metadata
        # the id for the pages
        db.session.flush()
        use_storage = prepare_create_or_update_pages_in_db(
            sim_id=simulation.id, estimator=estimator, estimator_dict=estimator_dict, use_storage=use_storage
        )


def store_results(
    simulation: SimulationModel, estimators: list[dict], full_resolution: frozenset = frozenset()
) -> None:
    """Stores the merged results of a simulation and marks it completed, unless it was finished meanwhile; the
    estimators named in full_resolution have their full resolution in storage
    """
    lock_results(simulation)
    if simulation.job_state in FINAL_STATES:
        logging.info("Simulation %d is %s, its results are not stored", simulation.id, simulation.job_state)
        return
    prepare_estimators_and_pages(simulation, estimators, full_resolution)
    if simulation.partial_primaries is not None:
        # the partial results of an HPC simulation are merged on the server, which names the estimators of input
        # files a little differently from the cluster's convertmc ("dose" and "dose_"): theirs go with them
        db.session.query(EstimatorModel).filter(
            EstimatorModel.simulation_id == simulation.id,
            EstimatorModel.file_name.notin_([estimator["name"] for estimator in estimators]),
        ).delete(synchronize_session=False)
    # the stored results are the final ones now
    simulation.partial_primaries = None
    simulation.partial_time = None
    # estimators and pages together, so a failure in between does not leave estimators without pages
    make_commit_to_db()

    update_dict = {"job_state": EntityState.COMPLETED.value, "end_time": datetime.utcnow().isoformat(sep=" ")}
    update_simulation_state(simulation=simulation, update_dict=update_dict)


def store_partial_results(simulation: SimulationModel, estimators: list[dict], primaries: int) -> bool:
    """Stores the results of a running simulation so far in place of the previous ones; the final results replace
    them. Returns whether they were stored, i.e. the simulation still runs.
    """
    lock_results(simulation)
    if simulation.job_state != EntityState.RUNNING.value:
        return False
    prepare_estimators_and_pages(simulation, estimators)
    simulation.partial_primaries = primaries
    simulation.partial_time = datetime.now(timezone.utc)
    make_commit_to_db()
    return True


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

        store_results(simulation, payload_dict["estimators"])
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

        estimator = fetch_estimator_by_sim_id_and_est_name(sim_id=simulation_id, est_name=estimator_name)
        if estimator is None:
            return yaptide_response(message="Estimator not found", code=404)
        if page_number is not None:
            page = fetch_page_by_est_id_and_page_number(est_id=estimator.id, page_number=page_number)
            result = with_full_resolution({"page": page_content(page)}, estimator)
            return yaptide_response(message="Page retrieved successfully", code=200, content=result)

        if page_numbers is not None:
            parsed_page_numbers = parse_page_numbers(page_numbers)
            pages = fetch_pages_by_est_id_and_page_numbers(est_id=estimator.id, page_numbers=parsed_page_numbers)
            result = with_full_resolution({"pages": [page_content(page) for page in pages]}, estimator)
            return yaptide_response(message="Pages retrieved successfully", code=200, content=result)
        return yaptide_response(message="Wrong parameters", code=400, content=errors)


class FullResolutionResource(Resource):
    """The full resolution of an estimator whose pages were downsampled for the UI, for download"""

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String(required=True)
        estimator_name = fields.String(required=True)

    @staticmethod
    @requires_auth()
    def get(user: UserModel):
        """Redirects to a signed link to the file in storage"""
        schema = FullResolutionResource.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        params: dict = schema.load(request.args)
        is_owned, error_message, res_code = check_if_job_is_owned_and_exist(job_id=params["job_id"], user=user)
        if not is_owned:
            return yaptide_response(message=error_message, code=res_code)
        simulation_id = fetch_simulation_id_by_job_id(job_id=params["job_id"])
        estimator = fetch_estimator_by_sim_id_and_est_name(sim_id=simulation_id, est_name=params["estimator_name"])
        if estimator is None or FULL_RESOLUTION not in with_full_resolution({}, estimator):
            return yaptide_response(message="No full resolution of this estimator", code=404)
        return redirect(result_storage.page_url(result_storage.full_resolution_key(simulation_id, estimator.file_name)))


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
