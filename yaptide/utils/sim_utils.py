import copy
import json
import logging
import re
import sys
from enum import Enum, auto
from pathlib import Path

from pymchelper.estimator import Estimator
from pymchelper.writers.json import JsonWriter

# dirty hack needed to properly handle relative imports in the converter submodule
sys.path.append("yaptide/converter")
from ..converter.converter.api import (get_parser_from_str, run_parser)  # skipcq: FLK-E402
from pymchelper.flair.Input import Card

NSTAT_MATCH = r"NSTAT\s*\d*\s*\d*"


def estimators_to_list(estimators_dict: dict, dir_path: Path) -> list[dict]:
    """Convert simulation output to JSON dictionary representation (to be consumed by UI)"""
    if not estimators_dict:
        return {"message": "No estimators"}

    # result_dict is a dictionary, which is later converted to json
    # to provide readable API response for fronted
    # keys in results_dict are estimator names, values are the estimator objects
    result_estimators = []
    estimator: Estimator
    for estimator_key, estimator in estimators_dict.items():
        filepath = dir_path / estimator_key
        writer = JsonWriter(str(filepath), None)
        writer.write(estimator)

        with open(writer.filename, "r") as json_file:
            est_dict = json.load(json_file)
            est_dict["name"] = estimator_key
            result_estimators.append(est_dict)

    return result_estimators


class JSON_TYPE(Enum):
    """Class defining custom JSON types"""

    Editor = auto()
    Files = auto()


def get_json_type(payload_dict: dict) -> JSON_TYPE:
    """Returns type of provided JSON"""
    if "input_files" in payload_dict:
        return JSON_TYPE.Files
    return JSON_TYPE.Editor


def convert_editor_dict_to_files_dict(editor_dict: dict, parser_type: str) -> dict:
    """
    Convert payload data to dictionary with filenames and contents for Editor type projects
    Otherwise return empty dictionary
    """
    conv_parser = get_parser_from_str(parser_type)
    files_dict = run_parser(parser=conv_parser, input_data=editor_dict)
    return files_dict


def check_and_convert_payload_to_files_dict(payload_dict: dict) -> dict:
    """
    Convert payload data to dictionary with filenames and contents for Editor type projects
    Otherwise return empty dictionary
    """
    files_dict = {}
    json_type = get_json_type(payload_dict)
    if json_type == JSON_TYPE.Editor:
        files_dict = convert_editor_dict_to_files_dict(editor_dict=payload_dict["input_json"],
                                                       parser_type=payload_dict["sim_type"])
    else:
        logging.warning("Project of %s used, conversion works only for Editor projects", json_type)
    return files_dict


def adjust_primaries_in_editor_dict(payload_editor_dict: dict, ntasks: int = None) -> tuple[dict, int]:
    """
    Replaces number of primaries in `payload_editor_dict`
    if `ntasks` parameter is provided, it is used over one
    provided in `payload_editor_dict`
    """
    if ntasks is None:
        ntasks = payload_editor_dict['ntasks']
    else:
        logging.warning("ntasks value was specified as %d and will be overwritten", ntasks)

    editor_dict = copy.deepcopy(payload_editor_dict['input_json'])
    number_of_all_primaries = editor_dict['beam']['numberOfParticles']
    editor_dict['beam']['numberOfParticles'] //= ntasks
    return editor_dict, number_of_all_primaries


def adjust_primaries_in_files_dict(payload_files_dict: dict, ntasks: int = None) -> tuple[dict, int]:
    """
    Replaces number of primaries in `payload_files_dict`
    if `ntasks` parameter is provided, it is used over one
    provided in `payload_files_dict`
    """
    if ntasks is None:
        ntasks = payload_files_dict['ntasks']
    else:
        logging.warning("ntasks value was specified as %d and will be overwritten", ntasks)

    input_files = payload_files_dict['input_files']
    # determining input file type
    # should be done in more robust way which will require a lot of refactoring to pass sim_type
    if 'beam.dat' in input_files:
        return adjust_primaries_for_shieldhit_files(payload_files_dict=payload_files_dict, ntasks=ntasks)
    if next((file for file in input_files if file.endswith(".inp")), None):
        return adjust_primaries_for_fluka_files(payload_files_dict=payload_files_dict, ntasks=ntasks)
    return {}, 0


def adjust_primaries_for_shieldhit_files(payload_files_dict: dict, ntasks: int = None) -> tuple[dict, int]:
    """Adjusts number of primaries in beam.dat file for SHIELD-HIT12A"""
    files_dict = copy.deepcopy(payload_files_dict['input_files'])
    all_beam_lines: list[str] = files_dict['beam.dat'].split('\n')
    all_beam_lines_with_nstat = [line for line in all_beam_lines if line.lstrip().startswith('NSTAT')]
    beam_lines_count = len(all_beam_lines_with_nstat)
    if beam_lines_count != 1:
        logging.warning("Found unexpected number of lines with NSTAT keyword: %d", beam_lines_count)
    if beam_lines_count < 1:
        return files_dict, 0
    number_of_all_primaries: str = all_beam_lines_with_nstat[0].split()[1]
    primaries_per_task = str(int(number_of_all_primaries) // ntasks)
    for i in range(len(all_beam_lines)):
        if re.search(NSTAT_MATCH, all_beam_lines[i]):
            # line below replaces first found nstat value
            # it is important to specify 3rd argument as 1
            # because otherwise values further in line might be changed to
            all_beam_lines[i] = all_beam_lines[i].replace(number_of_all_primaries, primaries_per_task, 1)
    files_dict['beam.dat'] = '\n'.join(all_beam_lines)
    # number_of_tasks = payload_files_dict['ntasks']  -> to be implemented in UI
    # here we manipulate the files_dict['beam.dat'] file to adjust number of primaries
    # we manipulate content of the file, no need to write the file to disk
    return files_dict, int(number_of_all_primaries)


def adjust_primaries_for_fluka_files(payload_files_dict: dict, ntasks: int = None) -> tuple[dict, int]:
    """Adjusts number of primaries in *.inp file for FLUKA"""
    files_dict = copy.deepcopy(payload_files_dict['input_files'])
    input_file = next((file for file in files_dict if file.endswith(".inp")), None)
    if not input_file:
        return {}, 0

    # read number of primaries from fluka file
    all_input_lines: list[str] = files_dict[input_file].split('\n')
    # get value from START card
    start_card = next((line for line in all_input_lines if line.lstrip().startswith('START')), None)
    number_of_all_primaries = start_card.split()[1]
    parsed_number_of_all_primaries = int(float(number_of_all_primaries))
    primaries_per_task = parsed_number_of_all_primaries // ntasks
    logging.warning("Number of primaries per task: %d", primaries_per_task)
    for i in range(len(all_input_lines)):
        # replace first found card START
        if all_input_lines[i].lstrip().startswith('START'):
            logging.warning("Replacing START card with new value")
            start_card = str(Card(tag="START", what=[str(primaries_per_task)]))
            all_input_lines[i] = start_card
            break
    files_dict[input_file] = '\n'.join(all_input_lines)
    return files_dict, parsed_number_of_all_primaries


def files_dict_with_adjusted_primaries(payload_dict: dict, ntasks: int = None) -> tuple[dict, int]:
    """
    Replaces number of primaries in `payload_dict`
    if `ntasks` parameter is provided, it is used over one
    provided in `payload_dict`
    returns dict with input files and full number of requested primaries
    """
    json_type = get_json_type(payload_dict)
    if json_type == JSON_TYPE.Editor:
        new_payload_dict = copy.deepcopy(payload_dict)
        new_payload_dict["input_json"], number_of_all_primaries = adjust_primaries_in_editor_dict(
            payload_editor_dict=payload_dict, ntasks=ntasks)
        return check_and_convert_payload_to_files_dict(new_payload_dict), number_of_all_primaries
    if json_type == JSON_TYPE.Files:
        files_dict, number_of_all_primaries = adjust_primaries_in_files_dict(payload_files_dict=payload_dict,
                                                                             ntasks=ntasks)
        return files_dict, number_of_all_primaries
    return {}, 0


def write_simulation_input_files(files_dict: dict, output_dir: Path) -> None:
    """Save files from provided dict (filenames as keys and content as values) into the provided directory"""
    for filename, file_contents in files_dict.items():
        with open(output_dir / filename, "w", newline='\n') as writer:  # skipcq: PTC-W6004
            writer.write(file_contents)


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
