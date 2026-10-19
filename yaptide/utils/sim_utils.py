import copy
import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pymchelper.input_output import group_input_files
from pymchelper.flair.Input import Card
from converter.api import get_parser_from_str, run_parser
from yaptide.batch.merge_results import MAX_OUTPUT_BYTES, merge_group
from yaptide.utils.enums import InputType, SimulationType

NSTAT_MATCH = r"NSTAT\s*\d*\s*\d*"
# NSTAT without a step of saving, or with 0 (save only at the end)
NSTAT_WITHOUT_SAVES = re.compile(r"^(\s*NSTAT\s+\d+)(?:[ \t]+0)?(?=[ \t]*(?:!|\r?$))", re.MULTILINE)


def merge_simulation_outputs(output_dirs: list[Path], full_resolution_dir: Optional[Path] = None) -> list[dict]:
    """Merge the result files (SHIELD-HIT12A .bdo, FLUKA *_fort.*) of all tasks into estimators ready for the UI

    Each page is aggregated by its normalisation and averages are weighted by primaries, one task's file at a time
    (yaptide/batch/merge_results.py, which the HPC jobs run too). With full_resolution_dir given, an estimator with
    pages downsampled for the UI is written there in full as <name>.bdo. The list is sorted by name, the same for
    every merge.
    """
    missing = [str(path) for path in output_dirs if not path.is_dir()]
    if missing:
        # a merge without some tasks would be stored as the whole result
        raise FileNotFoundError(f"Task outputs missing: {', '.join(missing)}")
    files = [
        str(file) for path in output_dirs for pattern in ("*.bdo", "*_fort.*") for file in sorted(path.glob(pattern))
    ]
    merged = []
    for corename, group in group_input_files(files).items():
        full_resolution = str(full_resolution_dir / f"{corename}.bdo") if full_resolution_dir else None
        estimator = merge_group(corename, group, full_resolution)
        if estimator:
            merged.append({**estimator, "name": corename})
    return sorted(merged, key=lambda estimator: estimator["name"])


# the lines of a detect.dat geometry giving its bins along an axis: "X -5 5 100" (Mesh), "R 0 5 10" (Cyl), ...
BINNED_AXES = ("x", "y", "z", "r", "phi")
# bytes a value takes in a result file
VALUE_BYTES = 8
# what a merge of the results takes besides 3 copies of the largest estimator (the merged one, and a task's file as
# pymchelper reads it: the values and a list of as many items), measured on Linux: Python with numpy and pymchelper,
# the JSON of each downsampled page, the cluster's tools - generous
MERGE_BASE_BYTES = 2 << 30
PAGE_JSON_BYTES = 64 << 20


@dataclass
class OutputSize:
    """One output of a SHIELD-HIT12A detect.dat: its name, the bins of its geometry and the values it scores"""

    name: str
    bins: list[int]
    values: int
    pages: int


def detect_outputs(detect_dat: str) -> list[OutputSize]:
    """The outputs a SHIELD-HIT12A detect.dat scores: each geometry's bins (Mesh X x Y x Z, Cyl R x PHI x Z; one bin
    for the others, e.g. Zone), times every Quantity of the output, times its differential bins (Diff1, Diff2 after
    the Quantity they belong to)
    """
    geometries, outputs, block = {}, [], None
    for line in detect_dat.splitlines():
        words = re.split(r"[!#]", line, maxsplit=1)[0].split()
        if not words:
            continue
        key = words[0].lower()
        if key in ("geometry", "output", "filter"):
            block = {"kind": key, "name": "", "geo": "", "bins": [], "quantities": []}
            if key == "output":
                outputs.append(block)
        elif block is None or len(words) < 2:
            continue
        elif key == "name" and block["kind"] == "geometry":
            block["name"] = words[1]
            geometries[words[1]] = block["bins"]
        elif key in BINNED_AXES and block["kind"] == "geometry" and len(words) >= 4:
            block["bins"].append(abs(int(float(words[3]))))
        elif key == "geo" and block["kind"] == "output":
            block["geo"] = words[1]
        elif key == "filename" and block["kind"] == "output":
            block["name"] = re.sub(r"\.bdo$", "", words[1])
        elif key == "quantity" and block["kind"] == "output":
            block["quantities"].append(1)
        elif key in ("diff1", "diff2") and block["kind"] == "output" and block["quantities"] and len(words) >= 4:
            block["quantities"][-1] *= max(abs(int(float(words[3]))), 1)
    sizes = []
    for output in outputs:
        bins = geometries.get(output["geo"]) or [1]
        sizes.append(
            OutputSize(
                name=output["name"] or output["geo"],
                bins=bins,
                values=math.prod(bins) * sum(output["quantities"]),
                pages=len(output["quantities"]),
            )
        )
    return sizes


def output_size_error(files_dict: dict, ntasks: int) -> Optional[str]:
    """Why a simulation is refused for the size of its result files (all tasks', SHIELD-HIT12A only), None if not"""
    outputs = detect_outputs(files_dict.get("detect.dat", ""))
    total = sum(output.values for output in outputs) * VALUE_BYTES * ntasks
    if total <= MAX_OUTPUT_BYTES:
        return None
    largest = max(outputs, key=lambda output: output.values)
    return (
        f"The outputs would take {round(total / 1e9)} GB ({largest.name}: {' × '.join(map(str, largest.bins))} bins"
        f" × {ntasks} tasks); the limit is {round(MAX_OUTPUT_BYTES / 1e9)} GB. Use fewer bins or tasks."
    )


def merge_memory_bytes(files_dict: dict) -> int:
    """Memory merging the results of a SHIELD-HIT12A simulation takes (yaptide/batch/merge_results.py): 3 copies
    of the largest output, the JSON of its pages and a base
    """
    outputs = detect_outputs(files_dict.get("detect.dat", ""))
    largest = max(outputs, key=lambda output: output.values, default=OutputSize("", [], 0, 0))
    return 3 * largest.values * VALUE_BYTES + largest.pages * PAGE_JSON_BYTES + MERGE_BASE_BYTES


def get_json_type(payload_dict: dict) -> InputType:
    """Returns type of provided JSON"""
    if "input_files" in payload_dict:
        return InputType.FILES
    return InputType.EDITOR


def get_simulator_type_and_particle_source_input_file(
    payload_dict: dict,
) -> tuple[Optional[SimulationType], Optional[str]]:
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
        logging.warning("Received payload doesn't have the input_files dictionary.")
        return None, None

    # determining input file type - that information should most certainly be passed in the payload,
    # but now it's not, so we have to do this ugly thing
    if "beam.dat" in input_files:
        return SimulationType.SHIELDHIT, "beam.dat"
    inp_file = next((file for file in input_files if file.endswith(".inp")), None)
    if inp_file:
        return SimulationType.FLUKA, inp_file

    # if we couldn't determine the file type, return a tuple of Nones
    logging.warning("Couldn't determine the file type from the received payload.")
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
        # check with try-catch for the number of particles variable and return it
        # if it's not there, return None
        try:
            return payload_dict["input_json"]["beam"]["numberOfParticles"]
        except KeyError:
            logging.warning("The payload received from the editor doesn't have the number of particles value.")
            return None

    # get number of primaries when FILES were used
    if input_type == InputType.FILES:
        file_type, file_name = get_simulator_type_and_particle_source_input_file(payload_dict)

        # if we couldn't get the file, return None
        if not file_type:
            logging.warning("Couldn't get the particle source input file from received payload.")
            return None

        # get file lines
        # no need for key check since if the file_type is not None then we know it exists
        file_lines: list[str] = payload_dict["input_files"][file_name].split("\n")

        # return number of particles depending on the simulation type
        # this could be more generalized by just defining startswith string,
        # but a change to how one simulation type defines its files could break the generalization
        # therefore I don't believe such specific operations should be generalized
        if file_type == SimulationType.SHIELDHIT:
            first_nstat_line = next((line for line in file_lines if line.lstrip().startswith("NSTAT")), None)
            if first_nstat_line:
                # try-catch for index out of range and int conversion errors
                try:
                    return int(first_nstat_line.split()[1])
                except (IndexError, ValueError):
                    return None
            # if there's no NSTAT line, return None
            else:
                return None

        if file_type == SimulationType.FLUKA:
            first_start_line = next((line for line in file_lines if line.lstrip().startswith("START")), None)
            if first_start_line:
                # try-catch for index out of range and int conversion errors
                try:
                    # START values are often written as floats (e.g. 50000.0)
                    # therefore we use a float first, to avoid excepting due to ValueError
                    return int(float(first_start_line.split()[1]))
                except (IndexError, ValueError):
                    return None
            # if there's no START line, return None
            else:
                return None

        # if the file_type is unknown, return None
        logging.warning("The simulator type determined from payload is unknown.")
        return None

    # if the input type couldn't be determined, return None
    logging.warning("Couldn't determine the input type when trying to get the total number of primaries.")
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
        files_dict = convert_editor_dict_to_files_dict(
            editor_dict=payload_dict["input_json"], parser_type=payload_dict["sim_type"]
        )
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
        ntasks = payload_editor_dict["ntasks"]
    else:
        logging.warning("ntasks value was specified as %d and will be overwritten", ntasks)

    editor_dict = copy.deepcopy(payload_editor_dict["input_json"])
    number_of_all_primaries = editor_dict["beam"]["numberOfParticles"]
    editor_dict["beam"]["numberOfParticles"] //= ntasks
    return editor_dict, number_of_all_primaries


def adjust_primaries_in_files_dict(payload_files_dict: dict, ntasks: int = None) -> tuple[dict, int]:
    """
    Replaces number of primaries in `payload_files_dict`
    if `ntasks` parameter is provided, it is used over one
    provided in `payload_files_dict`
    """
    if ntasks is None:
        ntasks = payload_files_dict["ntasks"]
    else:
        logging.warning("ntasks value was specified as %d and will be overwritten", ntasks)

    file_type, file_name = get_simulator_type_and_particle_source_input_file(payload_files_dict)
    if file_type == SimulationType.SHIELDHIT:
        return adjust_primaries_for_shieldhit_files(
            payload_files_dict=payload_files_dict, ntasks=ntasks, beam_dat_file=file_name
        )
    if file_type == SimulationType.FLUKA:
        return adjust_primaries_for_fluka_files(
            payload_files_dict=payload_files_dict, ntasks=ntasks, fluka_input_file=file_name
        )
    return {}, 0


def adjust_primaries_for_shieldhit_files(
    payload_files_dict: dict, ntasks: int = None, beam_dat_file: str = "beam.dat"
) -> tuple[dict, int]:
    """Adjusts number of primaries in beam.dat file for SHIELD-HIT12A"""
    files_dict = copy.deepcopy(payload_files_dict["input_files"])
    all_beam_lines: list[str] = files_dict[beam_dat_file].split("\n")
    all_beam_lines_with_nstat = [line for line in all_beam_lines if line.lstrip().startswith("NSTAT")]
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
    files_dict[beam_dat_file] = "\n".join(all_beam_lines)
    # number_of_tasks = payload_files_dict['ntasks']  -> to be implemented in UI
    # here we manipulate the files_dict['beam.dat'] file to adjust number of primaries
    # we manipulate content of the file, no need to write the file to disk
    return files_dict, int(number_of_all_primaries)


def adjust_primaries_for_fluka_files(
    payload_files_dict: dict, ntasks: int = None, fluka_input_file: str = None
) -> tuple[dict, int]:
    """Adjusts number of primaries in *.inp file for FLUKA"""
    files_dict = copy.deepcopy(payload_files_dict["input_files"])

    # if the primaries file name is not passed, get it from payload
    if not fluka_input_file:
        fluka_input_file = next((file for file in files_dict if file.endswith(".inp")), None)
        if not fluka_input_file:
            return {}, 0

    # read number of primaries from fluka file
    all_input_lines: list[str] = files_dict[fluka_input_file].split("\n")
    # get value from START card
    start_card = next((line for line in all_input_lines if line.lstrip().startswith("START")), None)
    number_of_all_primaries = start_card.split()[1]
    parsed_number_of_all_primaries = int(float(number_of_all_primaries))
    primaries_per_task = parsed_number_of_all_primaries // ntasks
    logging.warning("Number of primaries per task: %d", primaries_per_task)
    for i in range(len(all_input_lines)):
        # replace first found card START
        if all_input_lines[i].lstrip().startswith("START"):
            logging.warning("Replacing START card with new value")
            card = Card(tag="START")
            card.setWhat(1, str(primaries_per_task))
            start_card = str(card)
            all_input_lines[i] = start_card
            break
    files_dict[fluka_input_file] = "\n".join(all_input_lines)
    return files_dict, parsed_number_of_all_primaries


def set_shieldhit_save_step(files_dict: dict, primaries_per_task: int) -> None:
    """Makes SHIELD-HIT12A save its results every tenth of a task's primaries, for partial results; a step of saving
    set in the input is kept
    """
    if "beam.dat" in files_dict:
        step = max(1, primaries_per_task // 10)
        files_dict["beam.dat"] = NSTAT_WITHOUT_SAVES.sub(lambda match: f"{match[1]}    {step}", files_dict["beam.dat"])


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
            payload_editor_dict=payload_dict, ntasks=ntasks
        )
        return check_and_convert_payload_to_files_dict(new_payload_dict), number_of_all_primaries
    if json_type == InputType.FILES:
        files_dict, number_of_all_primaries = adjust_primaries_in_files_dict(
            payload_files_dict=payload_dict, ntasks=ntasks
        )
        return files_dict, number_of_all_primaries
    return {}, 0


def is_plain_filename(filename: str) -> bool:
    """Accept only a bare file name, so the file lands directly in the target directory."""
    return filename not in ("", "..") and Path(filename).name == filename


def write_simulation_input_files(files_dict: dict, output_dir: Path) -> None:
    """Save files from provided dict (filenames as keys and content as values) into the provided directory"""
    for filename, file_contents in files_dict.items():
        if not is_plain_filename(filename):
            raise ValueError(f"Invalid input filename: {filename!r}")
        with open(output_dir / filename, "w", newline="\n") as writer:  # skipcq: PTC-W6004
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
