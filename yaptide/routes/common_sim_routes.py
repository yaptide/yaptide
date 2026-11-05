import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from flask import request, current_app as app
from flask_restful import Resource
from sqlalchemy import text
from sqlalchemy.dialects import postgresql, sqlite
from marshmallow import Schema, fields

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
    note_watching,
    make_commit_to_db,
    update_simulation_state,
)
from yaptide.batch import result_format
from yaptide.persistence import result_storage
from yaptide.persistence.database import db
from yaptide.persistence.models import (
    EstimatorModel,
    ExpiringObjectModel,
    LogfilesModel,
    PageModel,
    PageObjectModel,
    PartialPageModel,
    PartialViewerModel,
    SimulationModel,
    UserModel,
)
from yaptide.routes.utils.decorators import requires_auth
from yaptide.routes.utils.response_templates import yaptide_response
from yaptide.routes.utils.utils import FINAL_STATES, check_if_job_is_owned_and_exist, job_status_content
from yaptide.routes.utils.tokens import decode_auth_token
from yaptide.utils.enums import EntityState, InputType, PlatformType, SimulationType


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
        if payload_dict.get("log"):
            logfiles = LogfilesModel(simulation_id=simulation.id)
            logfiles.data = payload_dict["log"]
            add_object_to_db(logfiles)

        return yaptide_response(message="Task updated", code=202)


# the states a simulation's own jobs may report (POST /jobs)
JOB_REPORTED_STATES = (EntityState.MERGING_RUNNING.value, EntityState.FAILED.value)


def serve_json() -> bool:
    """Whether pages in ZARR_FORMAT go to the UI as JSON pages (RESULTS_SERVE_JSON)"""
    return os.environ.get("RESULTS_SERVE_JSON", "").lower() in ("1", "true", "yes")


def page_content(page: PageModel) -> dict:
    """A page as the UI gets it: the page itself, or signed links to it in object storage

    A page in ZARR_FORMAT comes with a link for each of its objects ("files": zarr.json and the shard c/0); "url" is
    the link of its zarr.json. With RESULTS_SERVE_JSON set it comes as the JSON page instead, read and converted here:
    a bridge for a UI that does not read ZARR_FORMAT yet, at the cost of the old JSON on every read.
    """
    stored = page.stored_object
    if stored and stored.format == result_storage.ZARR_FORMAT and serve_json():
        return result_format.json_page(*result_format.read_page(result_storage.get_page_files(stored.key)))
    if stored and stored.format == result_storage.ZARR_FORMAT:
        files = result_storage.page_file_urls(stored.key)
        return {
            "page_number": page.page_number,
            "name": page.page_name,
            "dimensions": page.page_dimension,
            "format": stored.format,
            "url": files[result_format.METADATA_FILE],
            "files": files,
        }
    if stored:
        return {
            "page_number": page.page_number,
            "url": result_storage.page_url(stored.key),
            "format": stored.format,
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


def stored_page(page_dict: dict) -> dict:
    """The page in object storage a page entry points at: key, size and format"""
    return {"format": result_storage.PAGE_FORMAT, **page_dict["stored"]}


def store_json_page(sim_id: int, estimator: EstimatorModel, page_dict: dict, revision: str) -> PageObjectModel:
    """Stores a page that came with its values (POST /results of a job submitted before the clusters merged into
    pages themselves) in ZARR_FORMAT
    """
    data = dict(page_dict["data"])
    values = data.pop("values")
    prefix = result_storage.page_prefix(
        sim_id, estimator.file_name, int(page_dict["metadata"]["page_number"]), revision
    )
    size = result_storage.put_page_files(prefix, result_format.page_files(dict(page_dict, data=data), values))
    return PageObjectModel(key=prefix, size=size, format=result_storage.ZARR_FORMAT)


def prepare_create_or_update_pages_in_db(
    sim_id: int, estimator: EstimatorModel, estimator_dict: dict, use_storage: bool, superseded: list[str]
) -> bool:
    """Prepares page objects for insertion or update without committing to the database.

    A page comes stored already (a merge put it into storage) or with its values: those go to object storage while
    it accepts them and to the database otherwise, so an outage of the storage does not lose the results. The keys of
    stored pages replaced go to superseded, to be removed once the new ones are committed. Returns whether the storage
    is still used for the next pages.
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
        if "stored" in page_dict:
            # merged into storage by the engine, or uploaded straight to it by a cluster job and checked there
            # (yaptide/routes/results_upload_routes.py)
            page.compressed_data = None
            page.stored_object = PageObjectModel(**stored_page(page_dict))
        else:
            if use_storage:
                try:
                    page.stored_object = store_json_page(sim_id, estimator, page_dict, revision)
                    page.compressed_data = None
                except Exception:  # skipcq: PYL-W0703
                    logging.exception("Storing results of simulation %d failed, the rest goes to the database", sim_id)
                    use_storage = False
            if not use_storage:
                page.data = page_dict
                page.stored_object = None
        if old_key and old_key != (page.stored_object.key if page.stored_object else None):
            superseded.append(old_key)
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


def prepare_estimators_and_pages(simulation: SimulationModel, estimators: list[dict], superseded: list[str]) -> None:
    """Prepares the estimators and their pages in place of the stored ones, without committing; the keys of the
    stored pages they replace go to superseded.

    An estimator is its result file: the editor output writing it gives the name, and the estimator stored for the
    same file before (partial results, named with or without the trailing underscore) is updated.
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
        estimator.data = estimator_dict["metadata"]
        # the id for the pages
        db.session.flush()
        use_storage = prepare_create_or_update_pages_in_db(
            sim_id=simulation.id,
            estimator=estimator,
            estimator_dict=estimator_dict,
            use_storage=use_storage,
            superseded=superseded,
        )


def stored_pages(estimators: list[dict]) -> list[str]:
    """Keys of the pages already in storage among the estimators' pages"""
    return [page["stored"]["key"] for estimator in estimators for page in estimator["pages"] if "stored" in page]


def store_results(simulation: SimulationModel, estimators: list[dict]) -> bool:
    """Stores the merged results of a simulation and marks it completed, unless it was finished meanwhile; whether
    they were stored (pages already in storage that were not are removed)
    """
    lock_results(simulation)
    if simulation.job_state in FINAL_STATES:
        logging.info("Simulation %d is %s, its results are not stored", simulation.id, simulation.job_state)
        db.session.commit()
        result_storage.delete_pages(stored_pages(estimators))
        return False
    superseded = []
    prepare_estimators_and_pages(simulation, estimators, superseded)
    had_partial = simulation.partial_primaries is not None
    if had_partial:
        # partial results of estimators the final ones lack (a result file named differently by the cluster's
        # convertmc, "dose" and "dose_", when it merged without results_merger.py) go with them
        others = (
            db.session.query(EstimatorModel)
            .filter(
                EstimatorModel.simulation_id == simulation.id,
                EstimatorModel.file_name.notin_([estimator["name"] for estimator in estimators]),
            )
            .all()
        )
        superseded.extend(page.stored_object.key for other in others for page in other.pages if page.stored_object)
        for other in others:
            db.session.delete(other)
    # the stored results are the final ones now
    simulation.partial_primaries = None
    simulation.partial_time = None
    forget_partial(simulation.id)
    # estimators and pages together, so a failure in between does not leave estimators without pages
    make_commit_to_db()

    update_dict = {"job_state": EntityState.COMPLETED.value, "end_time": datetime.utcnow().isoformat(sep=" ")}
    update_simulation_state(simulation=simulation, update_dict=update_dict)
    if had_partial:
        # partial results a browser may still be loading: removed PARTIAL_CLEANUP_SECONDS from now
        expire_pages(simulation.id, superseded)
    else:
        result_storage.delete_pages(superseded)
    return True


# the stored pages of partial results stay this long after the simulation ended (clean_partial_results)
PARTIAL_CLEANUP_SECONDS = 15 * 60


def expire_pages(simulation_id: int, keys: list[str]) -> None:
    """Removes the stored pages PARTIAL_CLEANUP_SECONDS from now; at once when that cannot be noted"""
    if not keys:
        return
    delete_after = datetime.now(timezone.utc) + timedelta(seconds=PARTIAL_CLEANUP_SECONDS)
    try:
        db.session.add_all(
            ExpiringObjectModel(simulation_id=simulation_id, key=key, delete_after=delete_after) for key in keys
        )
        db.session.commit()
    except Exception:  # skipcq: PYL-W0703 - the final results are stored already
        db.session.rollback()
        logging.exception("Noting the partial results of simulation %d for removal failed", simulation_id)
        result_storage.delete_pages(keys)


def aware(moment: Optional[datetime]) -> Optional[datetime]:
    """A time from the database, in UTC (SQLite keeps none of the zone)"""
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def clean_partial_results(now: Optional[datetime] = None) -> int:
    """Removes partial results PARTIAL_CLEANUP_SECONDS after their simulation ended: the stored pages the final
    results replaced, and the partial results of a simulation that failed or was cancelled (its estimators and
    pages). Returns the pages removed
    """
    now = now or datetime.now(timezone.utc)
    expired = db.session.query(ExpiringObjectModel).filter(ExpiringObjectModel.delete_after <= now).all()
    keys = [row.key for row in expired]
    for row in expired:
        db.session.delete(row)
    ended = (
        db.session.query(SimulationModel)
        .filter(
            SimulationModel.partial_primaries.isnot(None),
            SimulationModel.job_state.in_([EntityState.FAILED.value, EntityState.CANCELED.value]),
        )
        .all()
    )
    cutoff = now - timedelta(seconds=PARTIAL_CLEANUP_SECONDS)
    for simulation in ended:
        end = aware(simulation.end_time) or aware(simulation.partial_time)
        if end is None or end > cutoff:
            continue
        for estimator in fetch_estimators_by_sim_id(simulation.id):
            keys.extend(page.stored_object.key for page in estimator.pages if page.stored_object)
            db.session.delete(estimator)
        simulation.partial_primaries = None
        simulation.partial_time = None
        forget_partial(simulation.id)
        logging.info("Removed the partial results of simulation %d, %s", simulation.id, simulation.job_state)
    # who looked at a simulation that ended without partial results, and the maps asked for
    lingering = {
        simulation_id
        for (simulation_id,) in db.session.query(PartialViewerModel.simulation_id)
        .union(db.session.query(PartialPageModel.simulation_id))
        .all()
    }
    for simulation_id in lingering:
        simulation = db.session.get(SimulationModel, simulation_id)
        if simulation is None or simulation.job_state in FINAL_STATES:
            forget_partial(simulation_id)
    db.session.commit()
    result_storage.delete_pages(keys)
    return len(keys)


# Partial results are merged only for the users who look at them. A browser tab with a running simulation's results
# open beats (POST /results/watch) every few seconds and says when it closes; the live pages are merged while one beats.
# A map is merged only when asked for (POST /results/on_demand), only that page. Both go into the simulation's wanted
# object in storage, which the cluster's watchers read (result_format.parse_wanted); the engine reads the database.
VIEWER_SECONDS = result_format.WANTED_LIVE_SECONDS


def utc_now() -> datetime:
    """Now, in UTC"""
    return datetime.now(timezone.utc)


def wanted_state(simulation_id: int, now: Optional[datetime] = None) -> tuple[float, set]:
    """What the users look at: until when (seconds since the epoch, 0 for no one) the live pages are wanted, and the
    pages asked for ((estimator file name, page number) pairs)
    """
    now = now or utc_now()
    last_seen = (
        db.session.query(db.func.max(PartialViewerModel.last_seen))
        .filter(PartialViewerModel.simulation_id == simulation_id)
        .scalar()
    )
    live_until = 0.0
    if last_seen is not None and aware(last_seen) > now - timedelta(seconds=VIEWER_SECONDS):
        live_until = aware(last_seen).timestamp() + VIEWER_SECONDS
    requested = (
        db.session.query(PartialPageModel)
        .filter(PartialPageModel.simulation_id == simulation_id, PartialPageModel.requested_at.isnot(None))
        .all()
    )
    return live_until, {(page.estimator, page.page_number) for page in requested}


def on_cluster(simulation_id: int) -> bool:
    """Whether the simulation runs on a cluster, whose watchers read the wanted object (the engine reads the
    database for the direct ones)
    """
    simulation = db.session.get(SimulationModel, simulation_id)
    return simulation is not None and simulation.platform == PlatformType.BATCH.value


def publish_wanted(simulation_id: int) -> None:
    """Writes what the users look at into the wanted object of a simulation on a cluster, for its watchers; a
    failure is only logged (the next beat writes it again)
    """
    if not result_storage.configured() or not on_cluster(simulation_id):
        return
    try:
        result_storage.put_wanted(simulation_id, result_format.wanted_body(*wanted_state(simulation_id)))
    except Exception as err:  # skipcq: PYL-W0703
        logging.warning("Writing what the users of simulation %d look at failed: %s", simulation_id, err)


def note_viewer(simulation_id: int, viewer: str, closed: bool = False) -> None:
    """A browser tab beat (or closed): noted, the tabs that stopped beating forgotten; commits"""
    now = utc_now()
    db.session.query(PartialViewerModel).filter(
        PartialViewerModel.simulation_id == simulation_id,
        PartialViewerModel.last_seen < now - timedelta(seconds=VIEWER_SECONDS),
    ).delete(synchronize_session=False)
    if closed:
        db.session.query(PartialViewerModel).filter(
            PartialViewerModel.simulation_id == simulation_id, PartialViewerModel.viewer == viewer
        ).delete(synchronize_session=False)
    else:
        insert = postgresql.insert if db.engine.dialect.name == "postgresql" else sqlite.insert
        seen = {"simulation_id": simulation_id, "viewer": viewer, "last_seen": now}
        db.session.execute(
            insert(PartialViewerModel)
            .values(seen)
            .on_conflict_do_update(index_elements=["simulation_id", "viewer"], set_={"last_seen": now})
        )
    db.session.commit()


def partial_pages(simulation_id: int) -> list[PartialPageModel]:
    """The maps of a running simulation's partial results, in order"""
    return (
        db.session.query(PartialPageModel)
        .filter(PartialPageModel.simulation_id == simulation_id)
        .order_by(PartialPageModel.estimator, PartialPageModel.page_number)
        .all()
    )


def iso(moment: Optional[datetime]) -> Optional[str]:
    """A time as the UI reads it"""
    moment = aware(moment)
    return moment.isoformat() if moment else None


def partial_pages_content(simulation: SimulationModel) -> list[dict]:
    """The maps of a running simulation as the UI gets them: estimator (its name in the results) and file, page
    number, name and dimensions, when last asked for, merged and of how many primaries
    """
    names = {estimator_key(estimator.file_name): estimator.name for estimator in fetch_estimators_by_sim_id(simulation.id)}
    outputs = editor_outputs_by_file(simulation)
    content = []
    for page in partial_pages(simulation.id):
        key = estimator_key(page.estimator)
        content.append(
            {
                "estimator": names.get(key) or (outputs[key]["name"] if key in outputs else page.estimator),
                "file": page.estimator,
                "page_number": page.page_number,
                "name": page.page_name,
                "dimensions": page.dimensions,
                "requested_at": iso(page.requested_at),
                "merged_at": iso(page.merged_at),
                "primaries": page.primaries,
            }
        )
    return content


def note_partial_pages(simulation_id: int, estimators: list[dict], primaries: int) -> bool:
    """Notes the maps partial results carry or announce (stubs, results_merger.page_stubs): a map merged is no longer
    asked for, and keeps when and of how many primaries. Without committing; whether a request was taken off
    """
    known = {(page.estimator, page.page_number): page for page in partial_pages(simulation_id)}
    now, delivered = utc_now(), False
    for estimator in estimators:
        for entry in estimator["pages"]:
            dimensions = int(entry.get("dimensions", 0))
            if result_format.partial_mode(dimensions) != result_format.ON_DEMAND:
                continue
            number = int(entry.get("page_number", entry.get("metadata", {}).get("page_number", 0)))
            page = known.get((estimator["name"], number))
            if page is None:
                page = PartialPageModel(simulation_id=simulation_id, estimator=estimator["name"], page_number=number)
                known[(estimator["name"], number)] = page
                db.session.add(page)
            name = entry.get("name", entry.get("metadata", {}).get("name"))
            if name:
                page.page_name = str(name)
            page.page_name = page.page_name or ""
            page.dimensions = dimensions
            if entry.get("stub"):
                continue
            delivered = delivered or page.requested_at is not None
            page.requested_at = None
            page.merged_at = now
            page.primaries = primaries
    return delivered


def forget_partial(simulation_id: int) -> None:
    """The simulation ended: no one's looking and no map asked for is noted any more (without committing), and its
    wanted object goes
    """
    db.session.query(PartialViewerModel).filter(PartialViewerModel.simulation_id == simulation_id).delete(
        synchronize_session=False
    )
    db.session.query(PartialPageModel).filter(PartialPageModel.simulation_id == simulation_id).delete(
        synchronize_session=False
    )
    if result_storage.configured() and on_cluster(simulation_id):
        try:
            result_storage.delete_wanted(simulation_id)
        except Exception as err:  # skipcq: PYL-W0703
            logging.warning("Removing the wanted object of simulation %d failed: %s", simulation_id, err)


def store_partial_results(simulation: SimulationModel, estimators: list[dict], primaries: int) -> bool:
    """Stores the results of a running simulation so far in place of the previous ones; the final results replace
    them. A page missing from them keeps its previous partial results (a map not asked for again,
    yaptide/batch/result_format.py); stubs of maps only note them. Returns whether they were stored, i.e. the
    simulation still runs (pages already in storage that were not are removed).
    """
    lock_results(simulation)
    if simulation.job_state != EntityState.RUNNING.value:
        db.session.commit()
        result_storage.delete_pages(stored_pages(estimators))
        return False
    delivered = note_partial_pages(simulation.id, estimators, primaries)
    with_values = [
        dict(estimator, pages=[page for page in estimator["pages"] if not page.get("stub")]) for estimator in estimators
    ]
    with_values = [estimator for estimator in with_values if estimator["pages"]]
    superseded = []
    if with_values:
        prepare_estimators_and_pages(simulation, with_values, superseded)
        simulation.partial_primaries = primaries
        simulation.partial_time = utc_now()
    make_commit_to_db()
    result_storage.delete_pages(superseded)
    if delivered:
        publish_wanted(simulation.id)
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


VIEWER_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def owned_simulation(user: UserModel, job_id):
    """The user's simulation of the job, or the error response"""
    if not isinstance(job_id, str):
        return None, yaptide_response(message="job_id is required", code=400)
    is_owned, error_message, res_code = check_if_job_is_owned_and_exist(job_id=job_id, user=user)
    if not is_owned:
        return None, yaptide_response(message=error_message, code=res_code)
    return fetch_simulation_by_job_id(job_id=job_id), None


def partial_state(simulation: SimulationModel) -> dict:
    """What the UI shows of a running simulation's partial results besides the pages: whether the live ones are
    merged now (someone looks), and the maps there are to ask for
    """
    live_until, _ = wanted_state(simulation.id)
    return {"live": live_until > utc_now().timestamp(), "pages": partial_pages_content(simulation)}


# simulations one beat may name: far more than anyone runs at once
MAX_WATCHED = 100


class WatchResource(Resource):
    """A browser tab with the app open: it beats every few seconds while open, naming the user's unfinished
    simulations (their live pages are merged while one does), and says when it closes (navigator.sendBeacon, a
    text/plain body)
    """

    @staticmethod
    @requires_auth()
    def post(user: UserModel):
        """Body: job_ids, viewer (the tab's own random id: letters, digits, - and _) and closed (optional, true when
        the tab closes). Answers the partial state (partial_state) of each running simulation, by job id
        """
        payload = request.get_json(force=True, silent=True)
        if not isinstance(payload, dict) or not VIEWER_PATTERN.fullmatch(str(payload.get("viewer", ""))):
            return yaptide_response(message="job_ids and viewer are required", code=400)
        job_ids = payload.get("job_ids")
        if not isinstance(job_ids, list) or len(job_ids) > MAX_WATCHED or not all(isinstance(j, str) for j in job_ids):
            return yaptide_response(message=f"job_ids: a list of at most {MAX_WATCHED} job ids", code=400)
        closed = bool(payload.get("closed"))
        states = {}
        for job_id in dict.fromkeys(job_ids):
            simulation, error = owned_simulation(user, job_id)
            if error or simulation.job_state in FINAL_STATES:
                continue
            note_viewer(simulation.id, payload["viewer"], closed)
            publish_wanted(simulation.id)
            if not closed:
                states[job_id] = partial_state(simulation)
        return yaptide_response(message="Closed" if closed else "Watching", code=200, content={"simulations": states})


class OnDemandResource(Resource):
    """The maps of a running simulation's partial results (yaptide/batch/result_format.py): each merged only when the
    user asks for it, as each costs a merge of the map's bins over the tasks' saves; the next partial results carry
    that page once
    """

    class APIParametersSchema(Schema):
        """Class specifies API parameters"""

        job_id = fields.String(required=True)

    @staticmethod
    @requires_auth()
    def get(user: UserModel):
        """The maps there are to ask for, and whether this server can deliver them"""
        schema = OnDemandResource.APIParametersSchema()
        errors: dict[str, list[str]] = schema.validate(request.args)
        if errors:
            return yaptide_response(message="Wrong parameters", code=400, content=errors)
        simulation, error = owned_simulation(user, schema.load(request.args)["job_id"])
        if error:
            return error
        content = dict(partial_state(simulation), available=result_storage.configured())
        return yaptide_response(message="On-demand pages", code=200, content=content)

    @staticmethod
    @requires_auth()
    def post(user: UserModel):
        """Asks for one map in the next partial results of a running simulation; body: job_id, file (the
        estimator's result file, as GET lists it) and page_number
        """
        payload = request.get_json(force=True, silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("file"), str):
            return yaptide_response(message="job_id, file and page_number are required", code=400)
        number = payload.get("page_number")
        if type(number) is not int or number < 0:
            return yaptide_response(message="page_number must be a number", code=400)
        simulation, error = owned_simulation(user, payload.get("job_id"))
        if error:
            return error
        if simulation.job_state != EntityState.RUNNING.value:
            return yaptide_response(message=f"Simulation is {simulation.job_state}", code=409)
        page = (
            db.session.query(PartialPageModel)
            .filter_by(simulation_id=simulation.id, estimator=payload["file"], page_number=number)
            .one_or_none()
        )
        if page is None:
            return yaptide_response(message="No such map in the partial results", code=404)
        page.requested_at = utc_now()
        db.session.commit()
        publish_wanted(simulation.id)
        return yaptide_response(message="Page requested", code=202, content=partial_state(simulation))


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
