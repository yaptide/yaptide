"""Tests for JSON converter"""
import json
from pathlib import Path
import pytest
import sys

from yaptide.utils.sim_utils import (
    check_and_convert_payload_to_files_dict,
    convert_editor_dict_to_files_dict,
    adjust_primaries_in_editor_dict,
    adjust_primaries_in_files_dict,
    write_simulation_input_files,
    get_json_type,
    JSON_TYPE
)

# dirty hack needed to properly handle relative imports in the converter submodule
converter_path = Path(__file__).resolve().parent.parent / "yaptide" / "converter"
sys.path.append(str(converter_path))
from converter.api import get_parser_from_str, run_parser  # skipcq: FLK-E402


@pytest.mark.parametrize("json_fixture", ["project_json_path", "payload_files_dict_path", "payload_editor_dict_path"])
def test_if_json_valid(json_fixture: str, request):
    """Check if test file exists."""
    # we cannot pass directly a fixture object (pytest limitation)
    # so we pass a name of the function and request fixture value
    # insired by https://engineeringfordatascience.com/posts/pytest_fixtures_with_parameterize/
    json_path: Path = request.getfixturevalue(json_fixture)

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

    files_dict = run_parser(parser=conv_parser, input_data=project_json_data)
    validate_config_dict(files_dict)


def validate_config_dict(files_dict: dict, expected_primaries: int = 10000):
    assert files_dict is not None
    assert 'beam.dat' in files_dict
    assert 'invalid_key' not in files_dict
    assert 'NSTAT' in files_dict['beam.dat']
    all_beam_strings_with_nstat = [line for line in files_dict['beam.dat'].split('\n') if 'NSTAT' in line]
    assert len(all_beam_strings_with_nstat) == 1
    line_with_nstat = all_beam_strings_with_nstat[0]
    print(line_with_nstat)
    assert len(line_with_nstat.split()) > 2
    nstat_keyword = line_with_nstat.split()[0]
    assert nstat_keyword == 'NSTAT'
    number_of_primaries = line_with_nstat.split()[1]
    assert number_of_primaries == f'{expected_primaries}'


def test_json_type_detection_editor(payload_editor_dict_data: dict):
    """
    We have two possible types of JSON project data : 
       - generated using editor (project) or 
       - containing user uploaded files (files)
    """
    json_type = get_json_type(payload_editor_dict_data)
    assert json_type == JSON_TYPE.Editor
    assert json_type != JSON_TYPE.Files


def test_json_type_detection_files(payload_files_dict_data: dict):
    """
    We have two possible types of JSON project data : 
       - generated using editor (project) or 
       - containing user uploaded files (files)
    """
    json_type = get_json_type(payload_files_dict_data)
    assert json_type != JSON_TYPE.Editor
    assert json_type == JSON_TYPE.Files


def test_if_parsing_works_for_payload(payload_editor_dict_data: dict):
    """Check if JSON data is parseable by converter"""
    assert payload_editor_dict_data is not None

    files_dict = convert_editor_dict_to_files_dict(editor_dict=payload_editor_dict_data["input_json"],
                                                   parser_type="shieldhit")
    assert files_dict is not None
    validate_config_dict(files_dict)


def test_if_manual_setting_primaries_works_for_editor(payload_editor_dict_data: dict):
    """Check if JSON data is parseable by converter"""
    assert payload_editor_dict_data is not None

    number_of_primaries = 137
    payload_editor_dict_data['input_json']['beam']['numberOfParticles'] = number_of_primaries
    files_dict = check_and_convert_payload_to_files_dict(payload_editor_dict_data)
    assert files_dict is not None
    validate_config_dict(files_dict, expected_primaries=number_of_primaries)


def test_setting_primaries_per_task_for_editor(payload_editor_dict_data: dict):
    """Check if JSON data is parseable by converter"""
    number_of_primaries_per_task = payload_editor_dict_data['input_json']['beam']['numberOfParticles']
    number_of_primaries_per_task //= payload_editor_dict_data["ntasks"]
    json_project_data_with_adjust_prim_no, number_of_all_primaries = adjust_primaries_in_editor_dict(payload_editor_dict_data)
    files_dict = convert_editor_dict_to_files_dict(editor_dict=json_project_data_with_adjust_prim_no,
                                                   parser_type="shieldhit")
    assert number_of_all_primaries == payload_editor_dict_data['input_json']['beam']['numberOfParticles']
    assert files_dict is not None
    validate_config_dict(files_dict, expected_primaries=number_of_primaries_per_task)


def test_setting_primaries_per_task_for_files(payload_files_dict_data: dict):
    """Check if JSON data is parseable by converter"""
    beam_nstat_line: str = [line for line in payload_files_dict_data['input_files']
                            ['beam.dat'].split('\n') if 'NSTAT' in line][0]
    number_of_primaries_per_task = int(beam_nstat_line.split()[1])
    number_of_primaries_per_task //= payload_files_dict_data['ntasks']
    # print(number_of_primaries_per_task)
    files_dict, number_of_all_primaries = adjust_primaries_in_files_dict(payload_files_dict_data)
    assert files_dict is not None
    assert number_of_all_primaries == int(beam_nstat_line.split()[1])
    validate_config_dict(files_dict, expected_primaries=number_of_primaries_per_task)


def test_input_files_writing(payload_editor_dict_data: dict, tmp_path: Path):
    """Test if input files are written to the directory"""
    files_dict = check_and_convert_payload_to_files_dict(payload_editor_dict_data)

    # check if temporary directory exists
    assert tmp_path.exists()
    # check if temporary directory is empty
    assert len(list(tmp_path.iterdir())) == 0

    write_simulation_input_files(files_dict=files_dict, output_dir=tmp_path)

    # check if simulation input files are generated
    for filename in ('beam.dat', 'detect.dat', 'geo.dat', 'mat.dat'):
        assert (tmp_path / filename).exists()
        assert (tmp_path / filename).stat().st_size > 0
    # check if file named 'beam.dat' contains 'NSTAT' keyword
    with open(tmp_path / 'beam.dat', 'r') as file_handle:
        assert 'NSTAT' in file_handle.read()
