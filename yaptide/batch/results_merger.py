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
import struct
import sys
import tempfile
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Tuple

import numpy as np
from pymchelper.estimator import Estimator
from pymchelper.input_output import AggregationType, fromfile, guess_corename
from pymchelper.page import Page
from pymchelper.readers.shieldhit.reader_bdo2019 import SHReaderBDO2019
from pymchelper.shieldhit.detector.detector_type import SHDetType

try:
    from yaptide.batch import bdo_pages, result_format
except ImportError:  # on a cluster, next to this script
    import bdo_pages
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


class ResultFileError(ValueError):
    """A result file that cannot be read whole: cut short, or gone (a save removed while a merge read it)"""

    def __init__(self, file: str, reason) -> None:
        super().__init__(f"{file}: {reason}")
        self.file = file


def read_bdo(file: str) -> Optional[Estimator]:
    """Reads a SHIELD-HIT12A file of the token format of 2019 with pymchelper's reader of that format, once:
    pymchelper's fromfile first tries the file as FLUKA's (whose reader takes the magic number for the length of a
    record, and reads the whole file into it), then looks for its format, before it reads the file once more
    """
    estimator = Estimator()
    estimator.file_counter = 1
    if not SHReaderBDO2019(file).read(estimator):
        return None
    return estimator


def read_whole(file: str) -> Optional[Estimator]:
    """Reads a result file with all its pages"""
    if file.endswith(MERGED_SUFFIX):
        # written by this simulation's merge_groups.py, next to this script
        with open(file, "rb") as merged:
            return pickle.load(merged)  # skipcq: BAN-B301
    if file.endswith(".bdo"):
        try:
            with open(file, "rb") as source:
                walked = bdo_pages.walk(source, lambda info: False)
        except bdo_pages.BdoError:
            walked = None
        if walked is not None and walked.file_format == bdo_pages.BDO2019:
            return read_bdo(file)
    return fromfile(file)


def page_wanted(
    info: bdo_pages.PageInfo, modes: Optional[set] = None, numbers: Optional[set] = None
) -> bool:
    """Whether a merge takes a page: of one of the modes (all without modes), and one of the numbers (all without)"""
    if modes is not None and result_format.partial_mode(info.dimensions, info.mcpl) not in modes:
        return False
    return numbers is None or info.number in numbers


# where the pages read of a file are copied, for pymchelper to read them: memory, where there is a tmpfs
PAGES_DIR = "/dev/shm" if Path("/dev/shm").is_dir() else None


def read_pages(file: str, modes: Optional[set] = None, numbers: Optional[set] = None) -> Optional[Estimator]:
    """Reads only the pages of the modes and numbers of a SHIELD-HIT12A result file: the others are skipped, their
    values never read (bdo_pages); None when it has none of them. The pages wanted are copied into a file of their
    own (in memory where it can), which pymchelper reads as it reads the whole file
    """
    keep = lambda info: page_wanted(info, modes, numbers)  # noqa: E731
    try:
        with open(file, "rb") as source:
            walked = bdo_pages.walk(source, keep)
    except bdo_pages.BdoError as err:
        raise ResultFileError(file, err) from err
    if not walked.whole:
        raise ResultFileError(file, "the file ends within a page")
    if not any(walked.kept):
        return None
    if all(walked.kept) and walked.file_format == bdo_pages.BDO2019:
        # every page wanted (a save holds only the pages of partial results): read as it is
        return read_bdo(file)
    try:
        directory = tempfile.TemporaryDirectory(prefix="yaptide_pages_", dir=PAGES_DIR)
    except OSError:
        directory = tempfile.TemporaryDirectory(prefix="yaptide_pages_")
    with directory:
        # the same name, so pymchelper finds the estimator's name in it
        copy = Path(directory.name) / Path(file).name
        try:
            walked = bdo_pages.copy_file(Path(file), copy, keep)
        except bdo_pages.BdoError as err:
            raise ResultFileError(file, err) from err
        if walked.file_format == bdo_pages.BDO2019:
            return read_bdo(str(copy))
        return fromfile(str(copy))


def read_estimator(file: str, modes: Optional[set] = None, numbers: Optional[set] = None) -> Optional[Estimator]:
    """Reads a result file, with modes or numbers only those pages (None when it has none of them); raises
    ResultFileError when it is gone, when a SHIELD-HIT12A file has no pages, or when one of its pages holds other than
    the bins its estimator declares (the UI gets values for every bin declared)
    """
    partial = (modes is not None or numbers is not None) and file.endswith(".bdo")
    try:
        estimator = read_pages(file, modes, numbers) if partial else read_whole(file)
    except (OSError, EOFError, IndexError, AttributeError, struct.error, pickle.UnpicklingError) as err:
        # gone, or cut short inside a page's tags (pymchelper then misses what the page needs)
        raise ResultFileError(file, err) from err
    if partial and estimator is None:
        return None
    if estimator is not None and file.endswith(".bdo") and not estimator.pages:
        raise ResultFileError(file, "no pages")
    if estimator and file.endswith(".bdo"):
        for page in estimator.pages:
            axes = (estimator.x.n, estimator.y.n, estimator.z.n, page.diff_axis1.n, page.diff_axis2.n)
            if page.dettyp != SHDetType.mcpl and page.data_raw.size != math.prod(axes):
                raise ResultFileError(file, f"{page.data_raw.size} values for {axes} bins")
    return estimator


def page_mode(page: Page) -> str:
    """What partial results carry of the page (result_format.partial_mode): by its dimensions, a list of particles
    (MCPL) only in the final results
    """
    return result_format.partial_mode(page.dimension, page.dettyp == SHDetType.mcpl)


def keep_pages(
    estimator: Optional[Estimator], modes: Optional[set], numbers: Optional[set] = None
) -> Optional[Estimator]:
    """Leaves the estimator its pages of the modes and numbers only (all of them without), each keeping its number:
    the others of a partial result are not merged, so a large page does not cost its merge at every partial result
    """
    if estimator is None or (modes is None and numbers is None):
        return estimator
    for number, page in enumerate(estimator.pages):
        if getattr(page, "page_number", None) is None:
            page.page_number = number
    estimator.pages = [
        page
        for page in estimator.pages
        if (modes is None or page_mode(page) in modes) and (numbers is None or int(page.page_number) in numbers)
    ]
    return estimator


def merge_estimator_files(
    files: List[str], modes: Optional[set] = None, numbers: Optional[set] = None
) -> Optional[Estimator]:
    """Merges one estimator's task files (or files merged already, of groups of tasks), reading one file at a time:
    each page aggregated by its normalisation, averages weighted by primaries, as pymchelper's fromfilelist does.
    With modes (result_format.partial_modes) or page numbers, only those pages; None when the estimator has none.

    Mean only: pymchelper's WeightedStatsAggregator also keeps a variance of every bin, which the pages do not hold.
    """
    result = keep_pages(read_estimator(files[0], modes, numbers), modes, numbers)
    if not result or not result.pages:
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
        estimator = keep_pages(read_estimator(file, modes, numbers), modes, numbers)
        if estimator is None:
            raise ResultFileError(file, f"none of the pages of {files[0]}")
        # a file cut short between pages reads whole, with fewer pages: the shorter one is left out
        if len(estimator.pages) != len(result.pages):
            short = file if len(estimator.pages) < len(result.pages) else files[0]
            raise ResultFileError(short, f"{len(estimator.pages)} pages, {len(result.pages)} in {files[0]}")
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


def merged_estimators(
    files: List[str], modes: Optional[set] = None, pages: Optional[dict] = None
) -> Iterator[Tuple[str, Estimator]]:
    """The merged estimators of the result files (SHIELD-HIT12A .bdo, FLUKA *_fort.*, merged ones of groups), by
    name, one at a time: the next one is merged when the caller asks for it. With modes, only the pages of those
    modes; with pages (estimator -> page numbers), only those estimators and pages (merge_estimator_files)
    """
    for name, group in sorted(group_input_files(sorted(files)).items()):
        if pages is not None and name not in pages:
            continue
        estimator = merge_estimator_files(group, modes, None if pages is None else set(pages[name]))
        if estimator:
            estimator.file_corename = name
            yield name, estimator


def page_stubs(files: List[str], modes: set) -> dict:
    """The pages of the modes the result files hold, without their values: estimator -> stubs (page number, name and
    dimensions), so the user sees which maps there are to ask for before any was merged. Only the tokens are read
    (bdo_pages), one file of each estimator; a file that cannot be read gives none
    """
    stubs: dict = {}
    for name, group in sorted(group_input_files(sorted(file for file in files if file.endswith(".bdo"))).items()):
        try:
            infos = bdo_pages.pages_of(Path(group[0]))
        except (OSError, bdo_pages.BdoError):
            continue
        entries = [
            {"page_number": info.number, "name": detector_name(info.detector_type), "dimensions": info.dimensions}
            for info in infos
            if result_format.partial_mode(info.dimensions, info.mcpl) in modes
        ]
        if entries:
            stubs[name] = entries
    return stubs


def detector_name(detector_type: int) -> str:
    """The name pymchelper gives a page of a detector type"""
    try:
        return str(SHDetType(detector_type))
    except ValueError:
        return ""


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


def write_pages(
    files: List[str],
    store: Callable[[str, int, dict, np.ndarray], dict],
    modes: Optional[set] = None,
    pages: Optional[dict] = None,
    stubs: Optional[dict] = None,
) -> Tuple[List[dict], int]:
    """Merges the result files and hands every page to store(estimator name, page number, page without values,
    values), one estimator at a time; returns the estimators (name, metadata and what store returned for each page)
    and the primaries merged. With modes, only the pages of those modes; with pages (estimator -> page numbers), only
    those (merge_estimator_files). Stubs (page_stubs) go with the estimators' pages, marked "stub"
    """
    estimators, primaries = [], 0
    stubs = dict(stubs or {})
    for name, estimator in merged_estimators(files, modes, pages):
        entries = []
        for page in estimator.pages:
            page_dict = page_without_values(estimator, page)
            number = int(page_dict["metadata"].get("page_number", len(entries)))
            entries.append(store(name, number, page_dict, page_values(page)))
        entries.extend(dict(stub, stub=True) for stub in stubs.pop(name, ()))
        estimators.append({"name": name, "metadata": estimator_metadata(estimator), "pages": entries})
        primaries = max(primaries, int(estimator.number_of_primaries))
        # the next estimator is merged once this one is gone
        del estimator, page
        collect_garbage()
    # estimators of maps only: their stubs alone
    for name, entries in sorted(stubs.items()):
        estimators.append({"name": name, "metadata": {}, "pages": [dict(stub, stub=True) for stub in entries]})
    return estimators, primaries


def write_directory(
    files: List[str],
    output_dir: Path,
    compress: bool = True,
    modes: Optional[set] = None,
    pages: Optional[dict] = None,
    stubs: Optional[dict] = None,
) -> dict:
    """Merges the result files into pages in output_dir and writes its manifest; returns the manifest. With modes or
    pages, only those pages; stubs go with them (write_pages)
    """

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

    estimators, primaries = write_pages(files, store, modes, pages, stubs)
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
