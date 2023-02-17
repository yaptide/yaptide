from yaptide.celery.worker import celery_app

from yaptide.persistence.models import SimulationModel

from pathlib import Path
import sys
import os
import tempfile
import re

from datetime import datetime

from celery.result import AsyncResult

from pymchelper.executor.options import SimulationSettings
from pymchelper.executor.runner import Runner as SHRunner
from pymchelper.estimator import Estimator
from pymchelper.axis import MeshAxis

# dirty hack needed to properly handle relative imports in the converter submodule
sys.path.append("yaptide/converter")
from ..converter.converter.api import get_parser_from_str, run_parser  # skipcq: FLK-E402


def write_input_files(param_dict: dict, raw_input_dict: dict, output_dir: Path):
    """
    Function used to write input files to output directory.
    Returns dictionary with filenames as keys and their content as values
    """
    if "input_files" not in raw_input_dict:
        conv_parser = get_parser_from_str(param_dict["sim_type"])
        return run_parser(parser=conv_parser, input_data=raw_input_dict, output_dir=output_dir)

    for key, file in raw_input_dict["input_files"].items():
        with open(Path(output_dir, key), "w") as writer:
            writer.write(file)
    return raw_input_dict["input_files"]


@celery_app.task(bind=True)
def run_simulation(self, param_dict: dict, raw_input_dict: dict):
    """Simulation runner"""
    # create temporary directory
    with tempfile.TemporaryDirectory() as tmp_dir_path:

        # digest dictionary with project data (extracted from JSON file)
        # and generate simulation input files
        input_files = write_input_files(param_dict, raw_input_dict, Path(tmp_dir_path))
        # we assume here that the simulation executable is available in the PATH so pymchelper will discover it
        settings = SimulationSettings(input_path=tmp_dir_path,  # skipcq: PYL-W0612
                                      simulator_exec_path=None,
                                      cmdline_opts="")

        # Pymchelper uses all available cores by default
        jobs = None
        # otherwise use given number of cores
        if param_dict["jobs"] > 0:
            jobs = param_dict["jobs"]

        runner_obj = SHRunner(jobs=jobs,
                              keep_workspace_after_run=True,
                              output_directory=tmp_dir_path)

        self.update_state(state="PROGRESS", meta={"path": tmp_dir_path, "sim_type": param_dict["sim_type"]})
        try:
            is_run_ok = runner_obj.run(settings=settings)
            if not is_run_ok:
                raise Exception
        except Exception:  # skipcq: PYL-W0703
            logfile = simulation_logfile(path=Path(tmp_dir_path, "run_1", "shieldhit_0001.log"))
            input_files = simulation_input_files(path=tmp_dir_path)
            return {"logfile": logfile, "input_files": input_files}

        estimators_dict: dict = runner_obj.get_data()

        result: dict = pymchelper_output_to_json(estimators_dict)

        return {
            "result": result,
            "metadata": {
                "source": "YAPTIDE" if "metadata" in raw_input_dict else "Input files",
                "simulator": param_dict["sim_type"],
                "type": "results",
            },
            "input_json": raw_input_dict if "metadata" in raw_input_dict else None,
            "input_files": input_files,
            "end_time": datetime.utcnow(),
            "cores": runner_obj.jobs
        }


@celery_app.task
def convert_input_files(param_dict: dict, raw_input_dict: dict):
    """Function converting output"""
    with tempfile.TemporaryDirectory() as tmp_dir_path:

        # digest dictionary with project data (extracted from JSON file)
        # and generate simulation input files
        conv_parser = get_parser_from_str(param_dict["sim_type"])
        run_parser(parser=conv_parser, input_data=raw_input_dict, output_dir=tmp_dir_path)

        input_files = simulation_input_files(path=tmp_dir_path)
        return {"input_files": input_files}


def pymchelper_output_to_json(estimators_dict: dict) -> dict:
    """Dummy function for converting simulation output to dictionary"""
    if not estimators_dict:
        return {"message": "No estimators"}

    # result_dict is a dictionary, which is later converted to json
    # to provide readable API response for fronted
    # keys in results_dict are estimator names, values are the estimator objects
    result_dict = {"estimators": []}
    estimator: Estimator
    for estimator_key, estimator in estimators_dict.items():
        # est_dict contains list of pages
        est_dict = {
            "name": estimator_key,
            "metadata" : {},
            "pages": []
        }

        # read metadata from estimator object
        for name, value in estimator.__dict__.items():
            # skip non-metadata fields
            if name not in {"data", "data_raw", "error", "error_raw", "counter", "pages", "x", "y", "z"}:
                # remove \" to properly generate JSON
                est_dict["metadata"][name] = str(value).replace("\"", "")

        for page in estimator.pages:
            # page_dict contains:
            # "dimensions" indicating it is 1 dim page
            # "data" which has unit, name and list of data values
            page_dict = {
                "metadata" : {},
                "dimensions": page.dimension,
                "data": {
                    "unit": str(page.unit),
                    "name": str(page.name),
                }
            }

            # read metadata from page object
            for name, value in page.__dict__.items():
                # skip non-metadata fields and fields already read from estimator object
                exclude = {"data_raw", "error_raw", "estimator", "diff_axis1", "diff_axis2"}
                exclude |= set(estimator.__dict__.keys())
                if name not in exclude:
                    # remove \" to properly generate JSON
                    page_dict["metadata"][name] = str(value).replace("\"", "")

            if page.dimension == 0:
                page_dict["data"]["values"] = [page.data_raw.tolist()]
            else:
                page_dict["data"]["values"] = page.data_raw.tolist()
            # currently output is returned only when dimension == 1 due to
            # problems in efficient testing of other dimensions

            if page.dimension in {1, 2}:
                axis: MeshAxis = page.plot_axis(0)
                page_dict["first_axis"] = {
                    "unit": str(axis.unit),
                    "name": str(axis.name),
                    "values": axis.data.tolist(),
                }
            if page.dimension == 2:
                axis: MeshAxis = page.plot_axis(1)
                page_dict["second_axis"] = {
                    "unit": str(axis.unit),
                    "name": str(axis.name),
                    "values": axis.data.tolist(),
                }
            if page.dimension > 2:
                # Add info about the location of the file containging to many dimensions
                raise ValueError(f"Invalid number of pages {page.dimension}")

            est_dict["pages"].append(page_dict)
        result_dict["estimators"].append(est_dict)

    return result_dict


def simulation_logfile(path: Path) -> str:
    """Function returning simulation logfile"""
    try:
        with open(path, "r") as reader:
            return reader.read()
    except FileNotFoundError:
        return "logfile not found"


def simulation_input_files(path: str) -> dict:
    """Function returning a dictionary with simulation input filenames as keys and their content as values"""
    result = {}
    try:
        for filename in ["info.json", "geo.dat", "detect.dat", "beam.dat", "mat.dat"]:
            file = Path(path, filename)
            with open(file, "r") as reader:
                result[filename] = reader.read()
    except FileNotFoundError:
        result["info"] = "No input present"
    return result


def translate_celery_state_naming(job_state: str) -> str:
    if job_state in ["RECEIVED", "RETRY"]:
        return SimulationModel.JobStatus.PENDING.value
    if job_state in ["PROGRESS", "STARTED"]:
        return SimulationModel.JobStatus.RUNNING.value
    if job_state in ["FAILURE", "REVOKED"]:
        return SimulationModel.JobStatus.FAILED.value
    if job_state in ["SUCCESS"]:
        return SimulationModel.JobStatus.COMPLETED.value
    # Others are the same
    return job_state


@celery_app.task
def simulation_task_status(task_id: str) -> dict:
    """Task responsible for returning simulation status"""
    job = AsyncResult(id=task_id, app=celery_app)
    job_state = job.state
    result = {
        "job_state": translate_celery_state_naming(job_state)
    }
    if job_state == "PENDING":
        pass
    elif job_state == "PROGRESS":
        if not job.info.get("sim_type") in {"shieldhit", "sh_dummy"}:
            return result
        sim_info = sh12a_simulation_status(dir_path=job.info.get("path"))
        result["job_tasks_status"] = sim_info
    elif job_state != "FAILURE":
        if "result" in job.info:
            for key in ["result", "metadata", "input_files", "input_json", "end_time", "cores"]:
                result[key] = job.info[key]
        elif "logfile" in job.info:
            result["job_state"] = translate_celery_state_naming("FAILURE")
            result["error"] = "Simulation error"
            result["logfile"] = job.info.get("logfile")
            result["input_files"] = job.info.get("input_files")
    else:
        result["error"] = str(job.info)

    return result


def sh12a_simulation_status(dir_path: str) -> list:
    """Extracts current SHIELD-HIT12A simulation state from first available logfile"""
    # This is dummy version because pymchelper currently doesn't privide any information about progress
    # file_path = Path(dir_path, "run_1", "shieldhit_0001.log")
    result_list = []
    for work_dir in os.listdir(dir_path):
        regex_match = r"run_"
        if not re.search(regex_match, work_dir): continue
        workdir = Path(dir_path, work_dir)
        task_id = int(work_dir.split("_")[1])
        for filename in os.listdir(workdir):
            regex_match = r"shieldhit.*log"
            if not re.search(regex_match, filename): continue
            file_path = Path(workdir, filename)
            try:
                with open(file_path, "r") as reader:
                    found_line_which_starts_status_block = False
                    last_result_line = ""
                    requested_particles = 0
                    for line in reader:
                        if not found_line_which_starts_status_block:
                            # We are searching for lines containing progress info
                            # They are preceded by line starting with "Starting transport"
                            found_line_which_starts_status_block = line.lstrip().startswith("Starting transport")

                            # We are also searching for requested particles number
                            if requested_particles == 0 and re.search(r"Requested number of primaries NSTAT", line):
                                requested_particles = int(line.split(": ")[1])
                        else:
                            # Searching for latest line
                            if line.lstrip().startswith("Primary particle"):
                                last_result_line = line

                    regex_match = r"\bPrimary particle no.\s*\d*\s*ETR:\s*\d*\s*hours\s*\d*\s*minutes\s*\d*\s*seconds\b"
                    task_status = {
                        "task_id": task_id,
                        "task_state": SimulationModel.JobStatus.RUNNING.value,
                        "task_info": {
                            "requested_particles": requested_particles,
                            "simulated_primaries": 0
                        }
                    }
                    if re.search(regex_match, last_result_line):
                        splitted = last_result_line.split()
                        task_status["task_info"]["simulated_primaries"] = splitted[3]
                        task_status["estimated"] = {
                                "hours": splitted[5],
                                "minutes": splitted[7],
                                "seconds": splitted[9],
                            }
                    result_list.append(task_status)
            except FileNotFoundError:
                result_list.append({
                    "task_id": task_id,
                    "task_state": SimulationModel.JobStatus.PENDING.value
                })
    return result_list


@celery_app.task
def get_input_files(task_id: str) -> dict:
    """Task responsible for returning simulation input files generated by converter"""
    job = AsyncResult(id=task_id, app=celery_app)

    if job.state == "PROGRESS":
        result = {"info": "Input files"}
        input_files = simulation_input_files(job.info.get("path"))
        for key, value in input_files.items():
            result[key] = value
        return result
    return {"info": "No input present"}


@celery_app.task
def cancel_simulation(task_id: str) -> bool:
    """Task responsible for canceling simulation in progress"""
    # Currently this task does nothing because to working properly it requires changes in pymchelper
    print(task_id)
    return False
