from pathlib import Path
import json
import sys
import math

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
                return int(math.ceil(float(line.split()[1])/ntasks))
    except:
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
