import copy
import logging
from pathlib import Path
import json
import sys
import math
from enum import Enum, auto

from pymchelper.estimator import Estimator
from pymchelper.writers.json import JsonWriter

# dirty hack needed to properly handle relative imports in the converter submodule
sys.path.append("yaptide/converter")
from ..converter.converter.api import get_parser_from_str, run_parser  # skipcq: FLK-E402


def pymchelper_output_to_json(estimators_dict: dict, dir_path: Path) -> dict:
    """Convert simulation output to JSON dictionary representation (to be consumed by UI)"""
    if not estimators_dict:
        return {"message": "No estimators"}

    # result_dict is a dictionary, which is later converted to json
    # to provide readable API response for fronted
    # keys in results_dict are estimator names, values are the estimator objects
    result_dict = {"estimators": []}
    estimator: Estimator
    for estimator_key, estimator in estimators_dict.items():
        filepath = dir_path / estimator_key
        writer = JsonWriter(str(filepath), None)
        writer.write(estimator)

        with open(writer.filename, "r") as json_file:
            est_dict = json.load(json_file)
            est_dict["name"] = estimator_key
            result_dict["estimators"].append(est_dict)

    return result_dict


class JSON_TYPE(Enum):
    Editor = auto()
    Files = auto()


def get_json_type(json_data: dict) -> JSON_TYPE:
    possible_input_file_names = set(['beam.dat', 'geo.dat', 'detect.dat', 'mat.dat'])
    if possible_input_file_names.intersection(set(json_data["sim_data"].keys())):
        return JSON_TYPE.Files
    return JSON_TYPE.Editor


def convert_editor_payload_to_dict(json_project_data: dict, parser_type: str) -> dict:
    """
    Convert payload data to dictionary with filenames and contents for Editor type projects
    Otherwise return empty dictionary
    """
    conv_parser = get_parser_from_str(parser_type)
    filenames_content_dict = run_parser(parser=conv_parser, input_data=json_project_data)
    return filenames_content_dict


def check_and_convert_payload_to_dict(json_data: dict) -> dict:
    """
    Convert payload data to dictionary with filenames and contents for Editor type projects
    Otherwise return empty dictionary
    """
    filenames_content_dict = {}
    json_type = get_json_type(json_data)
    if json_type == JSON_TYPE.Editor:
        filenames_content_dict = convert_editor_payload_to_dict(json_project_data=json_data["sim_data"],
                                                         parser_type=json_data["sim_type"])
    else:
        logging.warning("Project of %s used, conversion works only for Editor projects", json_type)
    return filenames_content_dict


def editor_json_with_adjusted_primaries(json_editor_data: dict) -> dict:
    json_project_data = copy.deepcopy(json_editor_data['sim_data'])
    json_project_data['beam']['numberOfParticles'] //= json_editor_data['ntasks']
    return json_project_data

def files_json_with_adjusted_primaries(json_files_data: dict) -> dict:
    json_files_data_current = copy.deepcopy(json_files_data['sim_data'])
    # TODO: check if this is correct
    return json_files_data_current

def json_with_adjusted_primaries(json_data: dict) -> dict:
    json_type = get_json_type(json_data)
    if json_type == JSON_TYPE.Editor:
        return editor_json_with_adjusted_primaries(json_editor_data=json_data)
    elif json_type == JSON_TYPE.Files:
        return files_json_with_adjusted_primaries(json_files_data=json_data)
    return {}

def write_simulation_input_files(filename_and_content_dict: dict, output_dir: Path) -> None:
    for filename, file_contents in filename_and_content_dict.items():
        with open(output_dir / filename, "w") as file_handle:
            file_handle.write(file_contents)


def write_input_files(json_data: dict, output_dir: Path) -> dict:
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


def extract_particles_per_task(beam_dat: str, ntasks: int) -> int:
    """
    Function extracting number of particles to simulate per 1 task
    Number provided in beam.dat file is dedicated full amout of particles
    """
    try:
        lines = beam_dat.split("\n")
        for line in lines:
            if line.startswith("NSTAT"):
                return int(math.ceil(float(line.split()[1]) / ntasks))
    except:  # skipcq: FLK-E722
        pass
    # return default
    return 1000


def simulation_logfiles(path: Path) -> dict:
    """Function returning simulation logfile"""
    result = {}
    for log in path.glob("run_*/shieldhit_*log"):
        try:
            with open(log, "r") as reader:  # skipcq: PTC-W6004
                result[log.name] = reader.read()
        except FileNotFoundError:
            result[log.name] = "No file"
    return result


def simulation_input_files(path: Path) -> dict:
    """Function returning a dictionary with simulation input filenames as keys and their content as values"""
    result = {}
    try:
        for filename in ["info.json", "geo.dat", "detect.dat", "beam.dat", "mat.dat"]:
            file = path / filename
            with open(file, "r") as reader:
                result[filename] = reader.read()
    except FileNotFoundError:
        result["info"] = "No input present"
    return result
