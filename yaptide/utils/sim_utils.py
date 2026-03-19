import copy
import json
import logging
import re
from enum import Enum, auto
from pathlib import Path
from typing import Optional

from pymchelper.estimator import Estimator
from pymchelper.writers.json import JsonWriter
from pymchelper.flair.Input import Card
from converter.api import (get_parser_from_str, run_parser)
from yaptide.utils.enums import InputType, SimulationType

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


def get_json_type(payload_dict: dict) -> InputType:
    """Returns type of provided JSON"""
    if "input_files" in payload_dict:
        return InputType.FILES
    return InputType.EDITOR


def get_primaries_file_type_and_name(payload_dict: dict) -> tuple[Optional[SimulationType], Optional[str]]:
    """
    Function used for getting the file type and name that contains the primaries
    from the payload dictionary received from a request.

    Args:
        payload_dict: A dictionary containing the payload received from a request.

    Returns:
        Tuple of SimulationType enumerator and string containing the name of the file
        or the tuple of Nones if the file type couldn't be determined
    """
    # ensure that the payload contains the input files dictionary
    input_files = payload_dict.get("input_files")
    if not input_files:
        return None, None

    # determining input file type - that information should most certainly be passed in the payload,
    # but now it's not, so we have to do this ugly thing
    if "beam.dat" in input_files:
        return SimulationType.SHIELDHIT, "beam.dat"
    inp_file = next((file for file in input_files if file.endswith(".inp")), None)
    if inp_file:
        return SimulationType.FLUKA, inp_file

    # if we couldn't determine the file type, return a tuple of Nones
    return None, None


def get_total_number_of_primaries(payload_dict: dict) -> Optional[int]:
    """
    Gets the total number of primary particles from the payload dictionary from a request
    depending on the input type and the simulation type.

    Args:
        payload_dict: A dictionary containing the payload received from a request.

    Returns:
        Integer representing the total number of primaries or None if it cannot be acquired from given payload.
    """
    input_type = get_json_type(payload_dict)

    # get number of primaries when EDITOR was used
    if input_type == InputType.EDITOR:
        # check with try-catch for the number of paricles variable and return it
        # if it's not there, return None
        try:
            return payload_dict["input_json"]["beam"]["numberOfParticles"]
        except KeyError:
            return None

    # get number of primaries when FILES were used
    if input_type == InputType.FILES:
        file_type, file_name = get_primaries_file_type_and_name(payload_dict)

        # if we couldn't get the file, return None
        if not file_type:
            return None

        # get file lines
        # no need for key check since if the file_type is not None then we know it exists
        file_lines: list[str] = payload_dict["input_files"][file_name].split('\n')

        # return number of particles depending on the simulation type
        # this could be more generalized by just defining startswith string,
        # but a change to how one simulation type defines its files could break the generalization
        # therefore I don't believe such specific operations should be generalized
        if file_type == SimulationType.SHIELDHIT:
            first_nstat_line = next((line for line in file_lines if line.lstrip().startswith('NSTAT')), None)
            if first_nstat_line:
                # try-catch for index out of range and int convession esrors
                try:
                    return int(first_nstat_line.split()[1])
                except (IndexError, ValueError):
                    return None
            # if there's no NSTAT line, return None
            else:
                return None

        if file_type == SimulationType.FLUKA:
            first_start_line = next((line for line in file_lines if line.lstrip().startswith('START')), None)
            if first_start_line:
                # try-catch for index out of range and int conversion errors
                try:
                    return int(first_start_line.split()[1])
                except (IndexError, ValueError):
                    return None
            # if there's no START line, return None
            else:
                return None

        # if the file_type is unknown, return None
        return None

    # if the input type couldn't be determined, return None
    return None


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
    if json_type == InputType.EDITOR:
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

    file_type, file_name = get_primaries_file_type_and_name(payload_files_dict)
    if file_type == SimulationType.SHIELDHIT:
        return adjust_primaries_for_shieldhit_files(payload_files_dict=payload_files_dict,
                                                    ntasks=ntasks,
                                                    primaries_file=file_name)
    if file_type == SimulationType.FLUKA:
        return adjust_primaries_for_fluka_files(payload_files_dict=payload_files_dict,
                                                ntasks=ntasks,
                                                primaries_file=file_name)
    return {}, 0


def adjust_primaries_for_shieldhit_files(payload_files_dict: dict,
                                         ntasks: int = None,
                                         primaries_file: str = None) -> tuple[dict, int]:
    """Adjusts number of primaries in beam.dat file for SHIELD-HIT12A"""
    files_dict = copy.deepcopy(payload_files_dict['input_files'])

    # if the primaries file name is not passed, use beam.dat
    if not primaries_file:
        primaries_file = "beam.dat"

    all_beam_lines: list[str] = files_dict[primaries_file].split('\n')
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
    files_dict[primaries_file] = '\n'.join(all_beam_lines)
    # number_of_tasks = payload_files_dict['ntasks']  -> to be implemented in UI
    # here we manipulate the files_dict['beam.dat'] file to adjust number of primaries
    # we manipulate content of the file, no need to write the file to disk
    return files_dict, int(number_of_all_primaries)


def adjust_primaries_for_fluka_files(payload_files_dict: dict,
                                     ntasks: int = None,
                                     primaries_file: str = None) -> tuple[dict, int]:
    """Adjusts number of primaries in *.inp file for FLUKA"""
    files_dict = copy.deepcopy(payload_files_dict['input_files'])

    # if the primaries file name is not passed, get it from payload
    if not primaries_file:
        primaries_file = next((file for file in files_dict if file.endswith(".inp")), None)
        if not primaries_file:
            return {}, 0

    # read number of primaries from fluka file
    all_input_lines: list[str] = files_dict[primaries_file].split('\n')
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
            card = Card(tag="START")
            card.setWhat(1, str(primaries_per_task))
            start_card = str(card)
            all_input_lines[i] = start_card
            break
    files_dict[primaries_file] = '\n'.join(all_input_lines)
    return files_dict, parsed_number_of_all_primaries


def files_dict_with_adjusted_primaries(payload_dict: dict, ntasks: int = None) -> tuple[dict, int]:
    """
    Replaces number of primaries in `payload_dict`
    if `ntasks` parameter is provided, it is used over one
    provided in `payload_dict`
    returns dict with input files and full number of requested primaries
    """
    json_type = get_json_type(payload_dict)
    if json_type == InputType.EDITOR:
        new_payload_dict = copy.deepcopy(payload_dict)
        new_payload_dict["input_json"], number_of_all_primaries = adjust_primaries_in_editor_dict(
            payload_editor_dict=payload_dict, ntasks=ntasks)
        return check_and_convert_payload_to_files_dict(new_payload_dict), number_of_all_primaries
    if json_type == InputType.FILES:
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
