"""Merges the result files of a simulation's tasks into result pages, one estimator at a time, one file at a time.

Used by the backend (the merges of direct simulations, yaptide/utils/sim_utils.py) and run on the clusters by the
collect job and for partial results, next to results_uploader.py: it needs pymchelper and numpy, and result_format.py
beside it. Only one task's file and one merged estimator are in memory at once; each merged estimator is written as
pages (result_format) and dropped before the next one is read.

    python3 results_merger.py --output_dir OUT 'workspaces/task_*/*.bdo'
    python3 results_merger.py --output_dir OUT --latest_saves 'workspaces/task_*/saves'

writes OUT/<estimator>/<page number>/<the page's objects> and OUT/results.json: the primaries merged and, for every
estimator, its metadata and the size and MD5 of each object of its pages.
"""

import argparse
import gc
import glob
import json
import logging
import math
import pickle
import sys
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Tuple

import numpy as np
from pymchelper.estimator import Estimator
from pymchelper.input_output import AggregationType, fromfile, guess_corename
from pymchelper.page import Page
from pymchelper.shieldhit.detector.detector_type import SHDetType

try:
    from yaptide.batch import result_format
except ImportError:  # on a cluster, next to this script
    import result_format

# the manifest of a merge's output directory
MANIFEST = "results.json"
# estimator fields that are not its metadata, and page fields that are not the page's (as pymchelper's JsonWriter)
NOT_ESTIMATOR_METADATA = {"data", "data_raw", "error", "error_raw", "counter", "pages", "x", "y", "z"}
NOT_PAGE_METADATA = {"data_raw", "error_raw", "estimator", "diff_axis1", "diff_axis2"}
# a group's merged estimator, pickled by merge_groups.py: named by the estimator, it merges again with task files
MERGED_SUFFIX = ".pkl"


def collect_garbage() -> None:
    """Frees a merged or read estimator dropped: its pages and the estimator refer to each other, a cycle only the
    garbage collector frees (pymchelper's fromfilelist does the same)
    """
    gc.collect()


def read_estimator(file: str) -> Optional[Estimator]:
    """Reads a result file; raises ValueError when a page of a SHIELD-HIT12A file holds other than the bins its
    estimator declares (the UI gets values for every bin declared)
    """
    if file.endswith(MERGED_SUFFIX):
        # written by this simulation's merge_groups.py, next to this script
        with open(file, "rb") as merged:
            return pickle.load(merged)  # skipcq: BAN-B301
    estimator = fromfile(file)
    if estimator and file.endswith(".bdo"):
        for page in estimator.pages:
            axes = (estimator.x.n, estimator.y.n, estimator.z.n, page.diff_axis1.n, page.diff_axis2.n)
            if page.dettyp != SHDetType.mcpl and page.data_raw.size != math.prod(axes):
                raise ValueError(f"{file}: {page.data_raw.size} values for {axes} bins")
    return estimator


def merge_estimator_files(files: List[str]) -> Optional[Estimator]:
    """Merges one estimator's task files (or files merged already, of groups of tasks), reading one file at a time:
    each page aggregated by its normalisation, averages weighted by primaries, as pymchelper's fromfilelist does

    Mean only: pymchelper's WeightedStatsAggregator also keeps a variance of every bin, which the pages do not hold.
    """
    result = read_estimator(files[0])
    if not result:
        return None
    # the task files merged: one for a task's, the group's for a group's
    counter = getattr(result, "file_counter", 1) or 1
    kinds = [getattr(page, "page_normalized", AggregationType.AveragingCumulative) for page in result.pages]
    averaged = [
        kind not in (AggregationType.NoAggregation, AggregationType.Sum, AggregationType.Concatenation)
        for kind in kinds
    ]
    for page, avg in zip(result.pages, averaged):
        if avg:
            page.data_raw = page.data_raw * result.number_of_primaries
    for file in files[1:]:
        estimator = read_estimator(file)
        for page, other, kind, avg in zip(result.pages, estimator.pages, kinds, averaged):
            if avg:
                # in place where the reader allows it: the file's values are not needed afterwards, so no third array
                # of the page's size
                if other.data_raw.flags.writeable:
                    other.data_raw *= estimator.number_of_primaries
                    page.data_raw += other.data_raw
                else:
                    page.data_raw += other.data_raw * estimator.number_of_primaries
            elif kind == AggregationType.Sum:
                page.data_raw += other.data_raw
            elif kind == AggregationType.Concatenation:
                page.data_raw = np.concatenate((page.data_raw, other.data_raw))
        result.number_of_primaries += estimator.number_of_primaries
        counter += getattr(estimator, "file_counter", 1) or 1
        # the file's arrays go before the next one is read
        del estimator
        collect_garbage()
    for page, avg in zip(result.pages, averaged):
        if avg:
            page.data_raw /= result.number_of_primaries
    result.file_counter = counter
    return result


def corename(file: str) -> str:
    """The estimator a file holds: pymchelper's guess for task files, the name of a merged one"""
    if file.endswith(MERGED_SUFFIX):
        return Path(file).name[: -len(MERGED_SUFFIX)]
    return guess_corename(file)


def group_input_files(files: List[str]) -> dict:
    """The files of every estimator: name -> files"""
    grouped: dict = {}
    for file in files:
        grouped.setdefault(corename(file), []).append(file)
    return grouped


def merged_estimators(files: List[str]) -> Iterator[Tuple[str, Estimator]]:
    """The merged estimators of the result files (SHIELD-HIT12A .bdo, FLUKA *_fort.*, merged ones of groups), by
    name, one at a time: the next one is merged when the caller asks for it
    """
    for name, group in sorted(group_input_files(sorted(files)).items()):
        estimator = merge_estimator_files(group)
        if estimator:
            estimator.file_corename = name
            yield name, estimator


def estimator_metadata(estimator: Estimator) -> dict:
    """The estimator's metadata as the UI reads it"""
    return {
        name: str(value).replace('"', "")
        for name, value in estimator.__dict__.items()
        if name not in NOT_ESTIMATOR_METADATA
    }


def page_without_values(estimator: Estimator, page: Page) -> dict:
    """A page as the UI reads it, without its values: the JSON pages had these fields"""
    excluded = NOT_PAGE_METADATA | set(estimator.__dict__)
    result = {
        "metadata": {
            name: str(value).replace('"', "") for name, value in page.__dict__.items() if name not in excluded
        },
        "dimensions": page.dimension,
        "data": {"unit": str(page.unit), "name": str(page.name)},
    }
    for number in range(page.dimension):
        axis = page.plot_axis(number)
        result[f"axis_dim{number + 1}"] = {
            "unit": str(axis.unit),
            "name": str(axis.name),
            "values": axis.data.tolist(),
        }
    return result


def page_values(page: Page) -> np.ndarray:
    """A page's values, flat"""
    return np.ravel(page.data_raw)


def write_pages(files: List[str], store: Callable[[str, int, dict, np.ndarray], dict]) -> Tuple[List[dict], int]:
    """Merges the result files and hands every page to store(estimator name, page number, page without values,
    values), one estimator at a time; returns the estimators (name, metadata and what store returned for each page)
    and the primaries merged
    """
    estimators, primaries = [], 0
    for name, estimator in merged_estimators(files):
        pages = []
        for page in estimator.pages:
            page_dict = page_without_values(estimator, page)
            number = int(page_dict["metadata"].get("page_number", len(pages)))
            pages.append(store(name, number, page_dict, page_values(page)))
        estimators.append({"name": name, "metadata": estimator_metadata(estimator), "pages": pages})
        primaries = max(primaries, int(estimator.number_of_primaries))
        # the next estimator is merged once this one is gone
        del estimator, page
        collect_garbage()
    return estimators, primaries


def write_directory(files: List[str], output_dir: Path, compress: bool = True) -> dict:
    """Merges the result files into pages in output_dir and writes its manifest; returns the manifest"""

    def store(name: str, number: int, page: dict, values: np.ndarray) -> dict:
        """Writes a page's objects into the directory; the page's entry of the manifest"""
        page_dir = output_dir / name / str(number)
        objects = {}
        for object_name, body in result_format.page_files(page, values, compress).items():
            path = page_dir / object_name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            objects[object_name] = {"size": len(body), "md5": result_format.body_md5(body)}
        return {
            "page_number": number,
            "name": str(page["metadata"].get("name", "")),
            "dimensions": int(page["dimensions"]),
            "files": objects,
        }

    estimators, primaries = write_pages(files, store)
    manifest = {"format": result_format.FORMAT, "primaries": primaries, "estimators": estimators}
    (output_dir / MANIFEST).write_text(json.dumps(manifest))
    return manifest


def latest_saves(pattern: str) -> List[str]:
    """The result files of the latest complete save of every task: each directory the pattern matches holds a task's
    saves, a directory each named by its primaries (the watcher writes them, yaptide/batch/watcher.py)
    """
    files = []
    for saves_dir in sorted(glob.glob(pattern)):
        saves = [path for path in Path(saves_dir).iterdir() if path.is_dir() and path.name.isdigit()]
        if saves:
            latest = max(saves, key=lambda path: int(path.name))
            files.extend(str(path) for path in sorted(latest.glob("*.bdo")))
    return files


def main(argv: Optional[List[str]] = None) -> int:
    """Merges the files the patterns match, or the latest saves of the tasks; non-zero without any result"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--latest_saves", help="pattern of the tasks' save directories, for partial results")
    parser.add_argument("--no_compress", action="store_true")
    parser.add_argument("patterns", nargs="*", help="patterns of result files, quoted: too many for a command line")
    args = parser.parse_args(argv)
    if args.latest_saves:
        files = latest_saves(args.latest_saves)
    else:
        files = sorted({file for pattern in args.patterns for file in glob.glob(pattern)})
    if not files:
        logging.error("No result files to merge")
        return 1
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = write_directory(files, output_dir, not args.no_compress)
    if not manifest["estimators"]:
        logging.error("No estimators in %d result files", len(files))
        return 1
    logging.info("Merged %d files into %d estimators", len(files), len(manifest["estimators"]))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
