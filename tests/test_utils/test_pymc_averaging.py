import copy
import random
from typing import List

import numpy as np
import pytest

from yaptide.celery.utils.averaging import EstimatorsAverager


def legacy_average_values(base_values: List[float], new_values: List[float], count: int) -> List[float]:
    """Pre-YAP-49 averaging of two lists of values, kept as a reference implementation"""
    return [sum(x) / (count + 1) for x in zip(map(lambda x: x * count, base_values), new_values)]


def legacy_average_estimators(base_list: list[dict], list_to_add: list[dict], averaged_count: int) -> list:
    """Pre-YAP-49 averaging of estimators, kept as a reference implementation"""
    for est_i, estimator_dict in enumerate(list_to_add):
        if estimator_dict["name"] != base_list[est_i]["name"]:
            est_i = next((i for i, item in enumerate(base_list) if item["name"] == estimator_dict["name"]), None)
        for page_i, page_dict in enumerate(estimator_dict["pages"]):
            if page_dict["metadata"]["page_number"] != base_list[est_i]["pages"][page_i]["metadata"]["page_number"]:
                page_i = next(
                    (
                        i
                        for i, item in enumerate(base_list[est_i]["pages"])
                        if item["metadata"]["page_number"] == page_dict["metadata"]["page_number"]
                    ),
                    None,
                )

            base_list[est_i]["pages"][page_i]["data"]["values"] = legacy_average_values(
                base_list[est_i]["pages"][page_i]["data"]["values"], page_dict["data"]["values"], averaged_count
            )
    return base_list


def legacy_merge(results: list[dict]) -> list[dict]:
    """Pre-YAP-49 merging loop from merge_results, including its weight counting"""
    averaged_estimators = None
    for i, result in enumerate(results):
        if "logfiles" in result:
            continue
        if averaged_estimators is None:
            averaged_estimators = result.get("estimators", [])
            continue
        averaged_estimators = legacy_average_estimators(averaged_estimators, result.get("estimators", []), i)
    return averaged_estimators


def merge(results: list[dict]) -> list[dict]:
    """Averages task results the way merge_results does it"""
    averager = EstimatorsAverager()
    for result in results:
        if "logfiles" in result:
            continue
        averager.add(result.get("estimators", []))
    return averager.averaged()


def scaled_estimators(estimators: list[dict], factor: float) -> list[dict]:
    """Deep copy of estimators with every value multiplied by factor"""
    result = copy.deepcopy(estimators)
    for estimator in result:
        for page in estimator["pages"]:
            page["data"]["values"] = [value * factor for value in page["data"]["values"]]
    return result


def flat_values(estimators: list[dict]) -> np.ndarray:
    """All values of all pages of all estimators, ordered by estimator name and page number"""
    values = []
    for estimator in sorted(estimators, key=lambda item: item["name"]):
        for page in sorted(estimator["pages"], key=lambda item: int(item["metadata"]["page_number"])):
            values.extend(page["data"]["values"])
    return np.asarray(values, dtype=np.float64)


def constant_estimators(value: float) -> list[dict]:
    """Minimal single estimator with two pages, all values equal to value"""
    return [
        {
            "name": "z_profile_",
            "pages": [
                {"metadata": {"page_number": "0"}, "data": {"values": [value, value, value]}},
                {"metadata": {"page_number": "1"}, "data": {"values": [value]}},
            ],
        }
    ]


@pytest.fixture(scope="function")
def estimators(result_dict_data: dict) -> list[dict]:
    """Estimators of a real, completed simulation"""
    return copy.deepcopy(result_dict_data["estimators"])


def test_averaging_matches_legacy_implementation(estimators: list[dict]):
    """Averaging on numpy gives the same result as the pre-YAP-49 implementation"""
    factors = [1.0, 1.1, 0.9, 1.05]
    results = [{"estimators": scaled_estimators(estimators, factor)} for factor in factors]

    new = merge(copy.deepcopy(results))
    legacy = legacy_merge(copy.deepcopy(results))

    assert np.allclose(flat_values(new), flat_values(legacy), rtol=1e-9, atol=0.0)


def test_averaging_identical_results_changes_nothing(estimators: list[dict]):
    """Averaging several copies of the same result returns the original values"""
    results = [{"estimators": copy.deepcopy(estimators)} for _ in range(4)]

    averaged = merge(results)

    assert np.allclose(flat_values(averaged), flat_values(estimators), rtol=1e-12, atol=0.0)


def test_weights_are_correct_when_a_task_fails():
    """A task carrying logfiles instead of estimators does not skew the averaging weights"""
    results = [
        {"logfiles": {"task_1.log": "failed"}},
        {"estimators": constant_estimators(3.0)},
        {"estimators": constant_estimators(6.0)},
        {"estimators": constant_estimators(9.0)},
    ]

    averaged = merge(copy.deepcopy(results))

    # plain mean of 3, 6 and 9
    assert np.allclose(flat_values(averaged), 6.0)
    # the pre-YAP-49 implementation weighted the first result twice as heavily as the others,
    # because the skipped logfiles task was still counted: (2 * 3 + 6 + 9) / 4
    assert np.allclose(flat_values(legacy_merge(copy.deepcopy(results))), 5.25)


def test_weights_are_correct_when_several_tasks_fail():
    """Averaging depends only on the tasks that carried estimators"""
    results = [
        {"logfiles": {"task_1.log": "failed"}},
        {"estimators": constant_estimators(4.0)},
        {"logfiles": {"task_3.log": "failed"}},
        {"estimators": constant_estimators(8.0)},
    ]

    averaged = merge(results)

    assert np.allclose(flat_values(averaged), 6.0)


def test_estimators_and_pages_are_matched_by_name_not_position(estimators: list[dict]):
    """Shuffling estimators and pages of later tasks does not change the average"""
    factors = [1.0, 1.2, 0.8]
    ordered = [{"estimators": scaled_estimators(estimators, factor)} for factor in factors]

    shuffled = copy.deepcopy(ordered)
    shuffler = random.Random(20260811)
    for result in shuffled[1:]:
        shuffler.shuffle(result["estimators"])
        for estimator in result["estimators"]:
            shuffler.shuffle(estimator["pages"])

    assert np.allclose(flat_values(merge(shuffled)), flat_values(merge(ordered)), rtol=1e-12, atol=0.0)


def test_task_with_unknown_estimator_raises(estimators: list[dict]):
    """An estimator absent from the first task is reported instead of silently corrupting the result"""
    extra = copy.deepcopy(estimators)
    extra[0]["name"] = "estimator_nobody_expected"

    averager = EstimatorsAverager()
    averager.add(copy.deepcopy(estimators))

    with pytest.raises(ValueError, match="estimator_nobody_expected"):
        averager.add(extra)


def test_task_with_mismatched_page_length_raises():
    """A page whose length differs between tasks is reported instead of being broadcast"""
    averager = EstimatorsAverager()
    averager.add(constant_estimators(1.0))

    truncated = constant_estimators(1.0)
    truncated[0]["pages"][0]["data"]["values"] = [1.0, 1.0]

    with pytest.raises(ValueError, match="page 0"):
        averager.add(truncated)


def test_duplicated_page_number_raises():
    """Two pages with the same number inside one estimator cannot be matched unambiguously"""
    duplicated = constant_estimators(1.0)
    duplicated[0]["pages"][1]["metadata"]["page_number"] = "0"

    with pytest.raises(ValueError, match="more than one page numbered 0"):
        EstimatorsAverager().add(duplicated)


def test_page_without_page_number_raises():
    """Pages are identified by page_number, so its absence is an error"""
    without_number = constant_estimators(1.0)
    del without_number[0]["pages"][0]["metadata"]["page_number"]

    with pytest.raises(ValueError, match="no page_number"):
        EstimatorsAverager().add(without_number)


def test_no_estimators_gives_no_result():
    """When every task failed there is nothing to average and nothing to send"""
    results = [{"logfiles": {"task_1.log": "failed"}}, {"logfiles": {"task_2.log": "failed"}}]

    assert merge(results) is None


def test_tasks_with_empty_estimators_are_skipped(estimators: list[dict]):
    """An empty estimators list does not become the base of the accumulation"""
    results = [
        {"estimators": []},
        {"estimators": scaled_estimators(estimators, 1.0)},
        {"estimators": scaled_estimators(estimators, 3.0)},
    ]

    averaged = merge(results)

    assert np.allclose(flat_values(averaged), flat_values(estimators) * 2.0, rtol=1e-12, atol=0.0)


def test_integer_values_are_not_truncated():
    """Values parsed from JSON as ints are accumulated as floats"""
    results = [{"estimators": constant_estimators(1)}, {"estimators": constant_estimators(2)}]

    averaged = merge(results)

    assert np.allclose(flat_values(averaged), 1.5)


def test_metadata_and_axes_are_preserved(estimators: list[dict]):
    """Averaging touches values only"""
    results = [{"estimators": scaled_estimators(estimators, factor)} for factor in (1.0, 2.0)]

    averaged = merge(copy.deepcopy(results))

    assert [estimator["name"] for estimator in averaged] == [estimator["name"] for estimator in estimators]
    for averaged_estimator, original_estimator in zip(averaged, estimators):
        assert averaged_estimator["metadata"] == original_estimator["metadata"]
        for averaged_page, original_page in zip(averaged_estimator["pages"], original_estimator["pages"]):
            assert averaged_page["metadata"] == original_page["metadata"]
            assert averaged_page.get("dimensions") == original_page.get("dimensions")
            assert averaged_page.get("axis_dim1") == original_page.get("axis_dim1")
            assert averaged_page["data"]["unit"] == original_page["data"]["unit"]


def test_averaged_values_are_json_serializable(estimators: list[dict]):
    """Averages are handed back as Python floats, ready to be sent to the backend"""
    results = [{"estimators": scaled_estimators(estimators, factor)} for factor in (1.0, 2.0)]

    averaged = merge(results)

    for estimator in averaged:
        for page in estimator["pages"]:
            assert isinstance(page["data"]["values"], list)
            assert all(isinstance(value, float) for value in page["data"]["values"])
