"""
Benchmark of averaging simulation results across tasks (YAP-49).

Compares the pre-YAP-49 implementation, which averaged Python lists element by element,
with the numpy accumulator in yaptide.celery.utils.averaging. Reports wall time and peak
memory allocated by the averaging itself, excluding the generation of the input data.

Usage:
    python scripts/benchmark_averaging.py
    python scripts/benchmark_averaging.py --tasks 8 --estimators 4 --pages 5 --values 1000000
"""

import argparse
import copy
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Callable, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yaptide.celery.utils.averaging import EstimatorsAverager  # noqa: E402

# Sizes reported as (tasks, estimators, pages per estimator, values per page).
# Larger results are worth measuring one at a time with the command line arguments,
# because the generated input alone takes about 32 bytes per value in Python lists.
DEFAULT_CASES = [
    (4, 4, 5, 8_000),  # roughly the size of tests/res/json_with_results.json
    (4, 4, 5, 250_000),  # 5 million values per task, ~40 MB of float64
    (8, 4, 5, 250_000),  # same result, twice as many tasks to merge
]


def legacy_average_values(base_values: List[float], new_values: List[float], count: int) -> List[float]:
    """Pre-YAP-49 averaging of two lists of values"""
    return [sum(x) / (count + 1) for x in zip(map(lambda x: x * count, base_values), new_values)]


def legacy_average_estimators(base_list: list[dict], list_to_add: list[dict], averaged_count: int) -> list:
    """Pre-YAP-49 averaging of estimators, with the index based matching left intact"""
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
    """Pre-YAP-49 merging loop from merge_results"""
    averaged_estimators = None
    for i, result in enumerate(results):
        if averaged_estimators is None:
            averaged_estimators = result["estimators"]
            continue
        averaged_estimators = legacy_average_estimators(averaged_estimators, result["estimators"], i)
    return averaged_estimators


def numpy_merge(results: list[dict]) -> list[dict]:
    """Averaging as merge_results does it after YAP-49"""
    averager = EstimatorsAverager()
    for result in results:
        averager.add(result["estimators"])
    return averager.averaged()


def make_results(tasks: int, estimators: int, pages: int, values: int) -> list[dict]:
    """Synthesizes results of a number of tasks, shaped like the output of estimators_to_list"""
    results = []
    for task in range(tasks):
        results.append(
            {
                "estimators": [
                    {
                        "name": f"estimator_{estimator}",
                        "metadata": {"number_of_primaries": "1000"},
                        "pages": [
                            {
                                "metadata": {"page_number": str(page)},
                                "dimensions": 1,
                                "data": {
                                    "name": "Dose",
                                    "unit": "MeV/g",
                                    "values": [float(task + page + index % 97) for index in range(values)],
                                },
                            }
                            for page in range(pages)
                        ],
                    }
                    for estimator in range(estimators)
                ]
            }
        )
    return results


def measure(merge: Callable[[list[dict]], list[dict]], results: list[dict]) -> tuple[float, float]:
    """Wall time in seconds and peak allocated memory in MB of a single merge"""
    tracemalloc.start()
    start = time.perf_counter()
    merge(results)
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return elapsed, peak / 1024 / 1024


def main() -> None:
    """Runs the benchmark for every requested case and prints a table"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=int, help="number of simulation tasks to average")
    parser.add_argument("--estimators", type=int, help="number of estimators per task")
    parser.add_argument("--pages", type=int, help="number of pages per estimator")
    parser.add_argument("--values", type=int, help="number of values per page")
    args = parser.parse_args()

    if all(value is not None for value in (args.tasks, args.estimators, args.pages, args.values)):
        cases = [(args.tasks, args.estimators, args.pages, args.values)]
    else:
        cases = DEFAULT_CASES

    header = f"{'tasks':>6} {'values/task':>13} {'legacy [s]':>11} {'numpy [s]':>10} {'speedup':>8} "
    header += f"{'legacy [MB]':>12} {'numpy [MB]':>11}"
    print(header)
    print("-" * len(header))

    for tasks, estimators, pages, values in cases:
        results = make_results(tasks, estimators, pages, values)
        values_per_task = estimators * pages * values

        legacy_time, legacy_peak = measure(legacy_merge, copy.deepcopy(results))
        numpy_time, numpy_peak = measure(numpy_merge, copy.deepcopy(results))

        speedup = legacy_time / numpy_time if numpy_time else float("inf")
        print(
            f"{tasks:>6} {values_per_task:>13,} {legacy_time:>11.2f} {numpy_time:>10.2f} "
            f"{speedup:>7.1f}x {legacy_peak:>12.1f} {numpy_peak:>11.1f}"
        )


if __name__ == "__main__":
    main()
