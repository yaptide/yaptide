from pathlib import Path
import sys
import re

from yaptide.persistence.models import SimulationModel

from pymchelper.estimator import Estimator
from pymchelper.axis import MeshAxis

# dirty hack needed to properly handle relative imports in the converter submodule
sys.path.append("yaptide/converter")
from ..converter.converter.api import get_parser_from_str, run_parser  # skipcq: FLK-E402


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
            "metadata": {},
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
                "metadata": {},
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


def write_input_files(json_data: dict, output_dir: Path):
    """
    Function used to write input files to output directory.
    Returns dictionary with filenames as keys and their content as values
    """
    if "beam.dat" not in json_data["sim_data"]:
        conv_parser = get_parser_from_str(json_data["sim_type"])
        return run_parser(parser=conv_parser, input_data=json_data["sim_data"], output_dir=output_dir)

    for key, file in json_data["sim_data"].items():
        with open(Path(output_dir, key), "w") as writer:
            writer.write(file)
    return json_data["sim_data"]


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


def sh12a_simulation_status(dir_path: str, sim_ended: bool = False) -> list:
    """Extracts current SHIELD-HIT12A simulation state from first available logfile"""
    # This is dummy version because pymchelper currently doesn't privide any information about progress
    result_list = []
    dir_path: Path = Path(dir_path)
    if not dir_path.exists():
        return result_list
    for shieldhit_log in dir_path.glob('**/shieldhit*.log'):
        task_id = int(str(shieldhit_log).split("run_")[1].split("/")[0])
        try:
            with open(shieldhit_log, "r") as reader:
                found_line_which_starts_status_block = False
                last_result_line = ""
                requested_primaries = 0
                for line in reader:
                    if not found_line_which_starts_status_block:
                        # We are searching for lines containing progress info
                        # They are preceded by line starting with "Starting transport"
                        found_line_which_starts_status_block = line.lstrip().startswith("Starting transport")

                        # We are also searching for requested particles number
                        if requested_primaries == 0 and re.search(r"Requested number of primaries NSTAT", line):
                            requested_primaries = int(line.split(": ")[1])
                    else:
                        # Searching for latest line
                        if line.lstrip().startswith("Primary particle") or line.lstrip().startswith("Run time"):
                            last_result_line = line

                run_match = r"\bPrimary particle no.\s*\d*\s*ETR:\s*\d*\s*hour.*\d*\s*minute.*\d*\s*second.*\b"
                complete_match = r"\bRun time:\s*\d*\s*hour.*\d*\s*minute.*\d*\s*second.*\b"
                task_status = {
                    "task_id": task_id,
                    "task_state": SimulationModel.JobStatus.RUNNING.value,
                    "requested_primaries": requested_primaries,
                    "simulated_primaries": 0
                }
                splitted = last_result_line.split()
                if re.search(run_match, last_result_line):
                    task_status["simulated_primaries"] = splitted[3]
                    task_status["estimated_time"] = {
                        "hours": splitted[5],
                        "minutes": splitted[7],
                        "seconds": splitted[9],
                    }
                elif re.search(complete_match, last_result_line):
                    task_status["simulated_primaries"] = requested_primaries
                    task_status["task_state"] = SimulationModel.JobStatus.COMPLETED.value
                    task_status["run_time"] = {
                        "hours": splitted[2],
                        "minutes": splitted[4],
                        "seconds": splitted[6],
                    }
                result_list.append(task_status)
        except FileNotFoundError:
            task_state = SimulationModel.JobStatus.FAILED.value if sim_ended\
                else SimulationModel.JobStatus.PENDING.value
            result_list.append({
                "task_id": task_id,
                "task_state": task_state
            })
    return result_list
