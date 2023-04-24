"""Tests for JSON converter"""
import json
import logging
from pathlib import Path
import pytest
import sys
from yaptide.utils.sim_utils import convert_payload_to_dict

# dirty hack needed to properly handle relative imports in the converter submodule
converter_path = Path(__file__).resolve().parent.parent / "yaptide" / "converter"
sys.path.append(str(converter_path))
import converter
from converter.api import get_parser_from_str, run_parser  # skipcq: FLK-E402

logger = logging.getLogger(__name__)


@pytest.fixture(scope='module')
def project_json() -> Path:
    """Location of this script according to pathlib"""
    main_dir = Path(__file__).resolve().parent.parent
    logger.debug("Main dir", main_dir)
    return main_dir / "yaptide_tester" / "example.json"


@pytest.fixture(scope='module')
def payload_json() -> Path:
    """Location of this script according to pathlib"""
    main_dir = Path(__file__).resolve().parent
    return main_dir / "res" / "json_payload.json"


@pytest.mark.parametrize("json_fixture", ["project_json", "payload_json"])
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


def test_if_parsing_works_for_project(project_json: Path):
    """Check if JSON file is parseable by converter"""
    with open(project_json, 'r') as file_handle:
        json_data = json.load(file_handle)
        assert json_data is not None
        conv_parser = get_parser_from_str('shieldhit')
        assert conv_parser is not None

        filename_content_dict = run_parser(parser=conv_parser, input_data=json_data)
        assert filename_content_dict is not None
        assert 'beam.dat' in filename_content_dict
        assert 'dupa' not in filename_content_dict
        assert 'NSTAT' in filename_content_dict['beam.dat']
        all_beam_strings_with_nstat = [
            line for line in filename_content_dict['beam.dat'].split('\n') if 'NSTAT' in line
        ]
        assert len(all_beam_strings_with_nstat) == 1
        line_with_nstat = all_beam_strings_with_nstat[0]
        print(line_with_nstat)
        assert len(line_with_nstat.split()) > 2
        nstat_keyword = line_with_nstat.split()[0]
        assert nstat_keyword == 'NSTAT'
        number_of_primaries = line_with_nstat.split()[1]
        assert number_of_primaries == '10000'



def test_if_parsing_works_for_payload(payload_json: Path):
    """Check if JSON file is parseable by converter"""
    with open(payload_json, 'r') as file_handle:
        json_data = json.load(file_handle)
        assert json_data is not None

        filename_content_dict = convert_payload_to_dict(json_data)
        assert filename_content_dict is not None
