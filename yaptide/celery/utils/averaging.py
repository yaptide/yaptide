import logging
from typing import Optional

import numpy as np
from pymchelper.averaging import WeightedStatsAggregator

# Explicit type, so whole numbers don't get misinterpreted as ints
VALUES_DTYPE = np.float64

# Key identifying a single page of a single estimator across simulation tasks.
PageKey = tuple[str, str]


def page_key(estimator_name: str, page: dict) -> PageKey:
    """Identity of a page within an estimator, used to match pages between tasks"""
    metadata = page.get("metadata", {})
    if "page_number" not in metadata:
        raise ValueError(f"Page of estimator {estimator_name} has no page_number in its metadata")
    # page_number is a string in the JSON produced by pymchelper, but normalize it
    # anyway so a caller passing an int matches the same page.
    return estimator_name, str(metadata["page_number"])


class EstimatorsAverager:
    """
    Accumulates estimator values across simulation tasks and averages them on demand.

    Values of each page are fed into a pymchelper WeightedStatsAggregator, which keeps
    a numerically stable running mean. Pages are matched between tasks by estimator
    name and page number, not by position.
    """

    def __init__(self) -> None:
        # Estimators of the first added task, reused as the carrier of metadata,
        # dimensions and axes. Its values are replaced by the averages in averaged().
        self._estimators: Optional[list[dict]] = None
        self._aggregators: dict[PageKey, WeightedStatsAggregator] = {}
        self._count = 0

    @property
    def count(self) -> int:
        """Number of tasks accumulated so far"""
        return self._count

    def add(self, estimators: list[dict]) -> None:
        """Adds estimators of a single simulation task to the accumulator"""
        if not estimators:
            logging.debug("Skipping a task with no estimators")
            return

        if self._estimators is None:
            self._adopt(estimators)
            return

        for estimator in estimators:
            for page in estimator["pages"]:
                key = page_key(estimator["name"], page)
                aggregator = self._aggregators.get(key)
                if aggregator is None:
                    raise ValueError(f"Estimator {key[0]}, page {key[1]} is missing from the results of the first task")
                values = np.asarray(page["data"]["values"], dtype=VALUES_DTYPE)
                if values.shape != aggregator.data.shape:
                    raise ValueError(
                        f"Estimator {key[0]}, page {key[1]} has {values.shape} values in this task "
                        f"but {aggregator.data.shape} in the first one"
                    )
                aggregator.update(values)

        self._count += 1
        logging.debug("Accumulated estimators of %d tasks", self._count)

    def averaged(self) -> Optional[list[dict]]:
        """
        Returns the estimators with values averaged over all added tasks,
        or None if no task carrying estimators was added.

        The estimators of the first added task are modified in place and returned.
        """
        if self._estimators is None:
            return None

        for estimator in self._estimators:
            for page in estimator["pages"]:
                key = page_key(estimator["name"], page)
                page["data"]["values"] = self._aggregators[key].mean.tolist()
                logging.debug("Averaged page %s of estimator %s over %d tasks", key[1], key[0], self._count)

        return self._estimators

    def _adopt(self, estimators: list[dict]) -> None:
        """Takes the estimators of the first task as the base of the accumulation"""
        aggregators: dict[PageKey, WeightedStatsAggregator] = {}
        for estimator in estimators:
            for page in estimator["pages"]:
                key = page_key(estimator["name"], page)
                if key in aggregators:
                    raise ValueError(f"Estimator {key[0]} has more than one page numbered {key[1]}")
                aggregators[key] = WeightedStatsAggregator()
                aggregators[key].update(np.asarray(page["data"]["values"], dtype=VALUES_DTYPE))

        self._estimators = estimators
        self._aggregators = aggregators
        self._count = 1
        logging.debug("Accumulating %d estimators, %d pages in total", len(estimators), len(aggregators))
