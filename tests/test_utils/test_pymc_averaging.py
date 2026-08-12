import copy
import random
from typing import List

import numpy as np
import pytest

from yaptide.celery.utils.averaging import EstimatorsAverager

def merge(results: list[dict]) -> list[dict] | None:
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


def test_weights_are_correct_when_a_task_fails():
    """A task carrying logfiles instead of estimators does not skew the averaging weights"""
    results = [
        {"logfiles": {"task_1.log": "failed"}},
        {"estimators": constant_estimators(3.0)},
        {"estimators": constant_estimators(6.0)},
        {"estimators": constant_estimators(9.0)},
    ]

    averaged = merge(copy.deepcopy(results))

    assert averaged is not None
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

    shuffled_merged = merge(shuffled)
    ordered_merged = merge(ordered)
    assert shuffled_merged is not None
    assert ordered_merged is not None
    assert np.allclose(flat_values(shuffled_merged), flat_values(ordered_merged), rtol=1e-12, atol=0.0)


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

    assert averaged is not None
    assert np.allclose(flat_values(averaged), flat_values(estimators) * 2.0, rtol=1e-12, atol=0.0)
