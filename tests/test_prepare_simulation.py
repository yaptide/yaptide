"""Tests for JSON converter"""
import json
import logging
from pathlib import Path
import pytest
import sys
from yaptide.utils.sim_utils import check_and_convert_payload_to_dict, convert_editor_payload_to_dict, get_json_type, JSON_TYPE, editor_json_with_adjusted_primaries, write_simulation_input_files

# dirty hack needed to properly handle relative imports in the converter submodule
converter_path = Path(__file__).resolve().parent.parent / "yaptide" / "converter"
sys.path.append(str(converter_path))
import converter
from converter.api import get_parser_from_str, run_parser  # skipcq: FLK-E402

logger = logging.getLogger(__name__)

""" Notepad :
We have 3 types of JSON files:
1. Project JSON - file that could be generated using UI and saved using "Save project" button
  - examples of such files are in https://github.com/yaptide/ui/tree/master/src/ThreeEditor/examples or in yaptide_tester/example.json
  - this file can contain only simulation input in JSON format or results as well
  - top level keys: "metadata", "project", "scene", TODO

2. Payload JSON - object which is sent to the server using POST request from UI
  - all such objects contain "sim_data" top level key

  a) editor payload JSON type assumes that user defined completely the simulation using UI 3D Editor and selected it for running
    - examples of such files are in tests/res/json_editor_payload.json
    - inside "sim_data" key we have contents of project json file
  b) files payload JSON type assumes that user uploaded input files and selected them for running
    - examples of such files are in tests/res/json_files_payload.json
    - inside "sim_data" key we have dictionary with filenames as keys and contents of input files as values
 
In the source code we assume following convention: `project_json`, `editor_json`, `files_json`
Therefore editor_json['sim_data'] can be passed as `project_json` 

"""


@pytest.fixture(scope='module')
def project_json_path() -> Path:
    """Location of this script according to pathlib"""
    main_dir = Path(__file__).resolve().parent.parent
    logger.debug("Main dir", main_dir)
    return main_dir / "yaptide_tester" / "example.json"


@pytest.fixture(scope='module')
def project_json_data(project_json_path) -> dict:
    json_data = {}
    with open(project_json_path, 'r') as file_handle:
        json_data = json.load(file_handle)
    return json_data


@pytest.fixture(scope='module')
def payload_editor_json_path() -> Path:
    """Location of this script according to pathlib"""
    main_dir = Path(__file__).resolve().parent
    return main_dir / "res" / "json_editor_payload.json"


@pytest.fixture(scope='module')
def payload_editor_json_data(payload_editor_json_path) -> dict:
    json_data = {}
    with open(payload_editor_json_path, 'r') as file_handle:
        json_data = json.load(file_handle)
    return json_data


@pytest.fixture(scope='module')
def payload_files_json_path() -> Path:
    """Location of this script according to pathlib"""
    main_dir = Path(__file__).resolve().parent
    return main_dir / "res" / "json_files_payload.json"


@pytest.fixture(scope='module')
def payload_files_json_data(payload_files_json_path) -> dict:
    json_data = {}
    with open(payload_files_json_path, 'r') as file_handle:
        json_data = json.load(file_handle)
    return json_data


@pytest.mark.parametrize("json_fixture", ["project_json_path", "payload_files_json_path", "payload_editor_json_path"])
def test_if_json_valid(json_fixture: str, request):
    """Check if test file exists."""
    # we cannot pass directly a fixture object (pytest limitation)
    # so we pass a name of the function and request fixture value
    # insired by https://engineeringfordatascience.com/posts/pytest_fixtures_with_parameterize/
    json_path = request.getfixturevalue(json_fixture)

    # run the tests
    assert json_path.exists()
    assert json_path.is_file()
    assert json_path.stat().st_size > 0
    # check if file is valid json
    with open(json_path, 'r') as file_handle:
        json_obj = json.load(file_handle)
        assert json_obj is not None


def test_if_parsing_works_for_project(project_json_data: dict):
    """Check if JSON file is parseable by converter"""
    assert project_json_data is not None
    conv_parser = get_parser_from_str('shieldhit')
    assert conv_parser is not None

    filename_content_dict = run_parser(parser=conv_parser, input_data=project_json_data)
    validate_config_dict(filename_content_dict)


def validate_config_dict(filename_content_dict: dict, expected_primaries: int = 10000):
    assert filename_content_dict is not None
    assert 'beam.dat' in filename_content_dict
    assert 'dupa' not in filename_content_dict
    assert 'NSTAT' in filename_content_dict['beam.dat']
    all_beam_strings_with_nstat = [line for line in filename_content_dict['beam.dat'].split('\n') if 'NSTAT' in line]
    assert len(all_beam_strings_with_nstat) == 1
    line_with_nstat = all_beam_strings_with_nstat[0]
    print(line_with_nstat)
    assert len(line_with_nstat.split()) > 2
    nstat_keyword = line_with_nstat.split()[0]
    assert nstat_keyword == 'NSTAT'
    number_of_primaries = line_with_nstat.split()[1]
    assert number_of_primaries == f'{expected_primaries}'


def test_json_type_detection_editor(payload_editor_json_data: dict):
    ''' We have two possible types of JSON project data : 
       - generated using editor (project) or 
       - containing user uploaded files (files) '''
    json_type = get_json_type(payload_editor_json_data)
    assert json_type == JSON_TYPE.Editor
    assert json_type != JSON_TYPE.Files


def test_json_type_detection_files(payload_files_json_data: dict):
    ''' We have two possible types of JSON project data : 
       - generated using editor (project) or 
       - containing user uploaded files (files) '''
    json_type = get_json_type(payload_files_json_data)
    assert json_type != JSON_TYPE.Editor
    assert json_type == JSON_TYPE.Files


def test_if_parsing_works_for_payload(payload_editor_json_data: dict):
    """Check if JSON data is parseable by converter"""
    assert payload_editor_json_data is not None

    filename_content_dict = convert_editor_payload_to_dict(json_project_data=payload_editor_json_data["sim_data"],
                                                           parser_type="shieldhit")
    assert filename_content_dict is not None
    validate_config_dict(filename_content_dict)


def test_if_manual_setting_primaries_works_for_editor(payload_editor_json_data: dict):
    """Check if JSON data is parseable by converter"""
    assert payload_editor_json_data is not None

    number_of_primaries = 137
    payload_editor_json_data['sim_data']['beam']['numberOfParticles'] = number_of_primaries
    filename_content_dict = check_and_convert_payload_to_dict(payload_editor_json_data)
    assert filename_content_dict is not None
    validate_config_dict(filename_content_dict, expected_primaries=number_of_primaries)


def test_setting_primaries_per_task_for_editor(payload_editor_json_data: dict):
    """Check if JSON data is parseable by converter"""
    number_of_primaries_per_task = payload_editor_json_data['sim_data']['beam']['numberOfParticles']
    number_of_primaries_per_task //= payload_editor_json_data['ntasks']
    json_project_data_with_adjust_prim_no = editor_json_with_adjusted_primaries(payload_editor_json_data)
    filename_content_dict = convert_editor_payload_to_dict(json_project_data=json_project_data_with_adjust_prim_no,
                                                           parser_type="shieldhit")
    assert filename_content_dict is not None
    validate_config_dict(filename_content_dict, expected_primaries=number_of_primaries_per_task)

def test_setting_primaries_per_task_for_files(payload_files_json_data: dict):
    """Check if JSON data is parseable by converter"""

    number_of_primaries_per_task = payload_files_json_data['sim_data']['beam']['numberOfParticles']
    number_of_primaries_per_task //= payload_files_json_data['ntasks']
    filename_content_dict = files_json_with_adjusted_primaries(payload_files_json_data)
    assert filename_content_dict is not None
    validate_config_dict(filename_content_dict, expected_primaries=number_of_primaries_per_task)



def test_input_files_writing(payload_editor_json_data: dict, tmp_path: Path):
    filename_content_dict = check_and_convert_payload_to_dict(payload_editor_json_data)

    # check if temporary directory exists
    assert tmp_path.exists()
    # check if temporary directory is empty
    assert len(list(tmp_path.iterdir())) == 0

    write_simulation_input_files(filename_and_content_dict=filename_content_dict, output_dir=tmp_path)

    # check if simulation input files are generated
    for filename in ('beam.dat', 'detect.dat', 'geo.dat', 'mat.dat'):
        assert (tmp_path / filename).exists()
        assert (tmp_path / filename).stat().st_size > 0
    # check if file named 'beam.dat' contains 'NSTAT' keyword
    with open(tmp_path / 'beam.dat', 'r') as file_handle:
        assert 'NSTAT' in file_handle.read()
