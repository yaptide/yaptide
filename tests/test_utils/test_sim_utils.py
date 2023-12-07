import pytest
from pytest import param

from yaptide.utils.sim_utils import adjust_primaries_for_fluka_files


@pytest.mark.parametrize("start_line, tasks, expected", [
    param("START         50000.0", 1, "START         50000.", id="1 task"),
    param("START         50000.0", 2, "START         25000.", id="2 tasks"),
    param("START         50000.0", 3, "START         16666.", id="3 tasks"),
])
def test_adjust_primaries_for_fluka_files(start_line: str, tasks: int, expected: str):
    payload_files_dict = {"input_files": {"fluka.inp": f'{start_line}\n'}}
    expected = f'{expected}\n'

    files_dict, total_primaries = adjust_primaries_for_fluka_files(payload_files_dict=payload_files_dict, ntasks=tasks)

    assert len(files_dict) == 1
    assert total_primaries == 50000
    assert files_dict["fluka.inp"] == expected
