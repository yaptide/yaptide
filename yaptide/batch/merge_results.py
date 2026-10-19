"""Merges the result files of a simulation's tasks into the estimators the UI reads, one task file at a time.

Shared by the backend (direct simulations, yaptide/utils/sim_utils.py) and the HPC collect job, which runs this file
next to the simulation with numpy and pymchelper only. The memory it takes is about twice the largest estimator
(the merged pages and one task's file): pages too large to show are downsampled for the UI, the full resolution goes
to a SHIELD-HIT12A .bdo file next to the JSON, for download.
"""

import argparse
import gc
import glob
import json
import logging
import os
import struct
import sys
from typing import List, Optional

import numpy as np
from pymchelper.input_output import fromfile, group_input_files
from pymchelper.shieldhit.detector.detector_type import SHDetType

# a page with more values than this is downsampled for the UI (the full resolution is kept for download)
DISPLAY_MAX_BINS = 1_000_000
# a simulation whose result files would take more than this, all tasks together, is refused at submit
MAX_OUTPUT_BYTES = 50 * 10**9

# how SHIELD-HIT12A aggregates a page over tasks (the page_normalized tag of its .bdo files, see pymchelper's
# AggregationType): the first task's page, a sum, a mean weighted by primaries of the cumulative values or of the
# per-primary ones, or the values of all tasks one after another (phase space)
NO_AGGREGATION, SUM, AVERAGING_CUMULATIVE, CONCATENATION = 0, 1, 2, 4
# formats whose page data pymchelper reshapes in Fortran order (pymchelper.page.Page._reshape)
FORTRAN_ORDER = ("bdo2016", "bdo2019", "fluka_binary")
# .bdo tags (pymchelper.readers.shieldhit.binary_spec.SHBDOTagID): simulated primaries, a page's data
BDO_NSTAT, BDO_DATA = 0xAA00, 0xDDBB
# values written to a .bdo file at once
WRITE_CHUNK = 1 << 20


def read_estimator(file: str):
    """Reads a result file; raises ValueError when a page of a SHIELD-HIT12A file holds other than the bins its
    estimator declares (the JSON for the UI has values for every bin declared)
    """
    estimator = fromfile(file)
    if estimator and file.endswith(".bdo"):
        for page in estimator.pages:
            axes = (estimator.x.n, estimator.y.n, estimator.z.n, page.diff_axis1.n, page.diff_axis2.n)
            if page.dettyp != SHDetType.mcpl and page.data_raw.size != int(np.prod(axes)):
                raise ValueError(f"{file}: {page.data_raw.size} values for {axes} bins")
    return estimator


def merge_estimator_files(files: List[str]):
    """Merge one estimator's task files, read one at a time: each page aggregated by its normalisation, averages
    weighted by primaries

    Mean only - pymchelper's WeightedStatsAggregator also accumulates a variance, which the JSON for the UI drops.
    """
    result = read_estimator(files[0])
    if not result:
        return None
    kinds = [getattr(page, "page_normalized", AVERAGING_CUMULATIVE) for page in result.pages]
    averaged = [kind not in (NO_AGGREGATION, SUM, CONCATENATION) for kind in kinds]
    for page, avg in zip(result.pages, averaged):
        if avg:
            # in place, as no copy of a large page fits next to it
            page.data_raw = page.data_raw.astype(np.float64, copy=False)
            page.data_raw *= result.number_of_primaries
    for file in files[1:]:
        add_file(result, file, kinds)
    for page, avg in zip(result.pages, averaged):
        if avg:
            page.data_raw /= result.number_of_primaries
    result.file_counter = len(files)
    return result


def add_file(result, file: str, kinds: List[int]) -> None:
    """Adds a task's file to the merged estimator (averaged pages as sums weighted by primaries); a function of its
    own, so nothing of the file is left in memory when the next one is read
    """
    estimator = read_estimator(file)
    other = weighted = None
    for page, other, kind in zip(result.pages, estimator.pages, kinds):
        if kind == SUM:
            page.data_raw += other.data_raw
        elif kind == CONCATENATION:
            page.data_raw = np.concatenate((page.data_raw, other.data_raw))
        elif kind != NO_AGGREGATION:
            weighted = other.data_raw.astype(np.float64, copy=False)
            weighted *= estimator.number_of_primaries
            page.data_raw += weighted
    result.number_of_primaries += estimator.number_of_primaries
    # pymchelper's estimator and its pages refer to each other: only the garbage collector frees them
    estimator = other = weighted = None
    gc.collect()


def block_factors(shape: tuple, max_bins: int) -> List[int]:
    """Integer block sizes per axis that bring the bins down to max_bins: the axis with the most bins shown is
    reduced first, an axis of one bin stays one
    """
    factors = [1] * len(shape)
    shown = list(shape)
    while int(np.prod(shown)) > max_bins:
        axis = shown.index(max(shown))
        factors[axis] += 1
        shown[axis] = -(-shape[axis] // factors[axis])
    return factors


def block_mean(data: np.ndarray, factors: List[int]) -> np.ndarray:
    """Mean of each block of factors bins along every axis; a partial last block averages the bins it has"""
    for axis, factor in enumerate(factors):
        if factor > 1:
            starts = np.arange(0, data.shape[axis], factor)
            counts = np.diff(np.append(starts, data.shape[axis]))
            shape = [-1 if dim == axis else 1 for dim in range(data.ndim)]
            data = np.add.reduceat(data, starts, axis=axis) / counts.reshape(shape)
    return data


def page_values(page, order: str):
    """The page's values and the centres of its plotted axes' bins as the UI gets them, and the page's downsampling
    (None when it is shown in full)

    A block mean is exact for summed or averaged quantities like dose and fluence; for LET-like ones (averages
    weighted by dose within a bin) it is an approximation, as the blocks are not weighted by dose.
    """
    axes = [page.plot_axis(i).data for i in range(page.dimension)]
    if page.data_raw.size <= DISPLAY_MAX_BINS or page.dettyp == SHDetType.mcpl:
        return page.data_raw, axes, None
    shape = page.data.shape
    factors = block_factors(shape, DISPLAY_MAX_BINS)
    values = block_mean(page.data, factors).ravel(order=order)
    # the plotted axes are the ones of more than one bin, in the order x, y, z and the differential ones
    axes = [block_mean(axis, [factor]) for axis, factor in zip(axes, [f for n, f in zip(shape, factors) if n > 1])]
    mesh = 3 if shape[3:] == (1, 1) else 5
    shown = [-(-n // f) for n, f in zip(shape, factors)]
    return values, axes, {"bins": [int(n) for n in shape[:mesh]], "shown": shown[:mesh]}


def estimator_dict(estimator) -> dict:
    """The estimator as the UI reads it: pymchelper's JSON (pymchelper.writers.json.JsonWriter), with the pages too
    large to show downsampled; such a page has "downsampled" in its metadata
    """
    exclude = {"data_raw", "error_raw", "estimator", "diff_axis1", "diff_axis2"} | set(estimator.__dict__)
    skipped = {"data", "data_raw", "error", "error_raw", "counter", "pages", "x", "y", "z"}
    result = {
        "metadata": {
            name: str(value).replace('"', "") for name, value in estimator.__dict__.items() if name not in skipped
        },
        "pages": [],
    }
    order = "F" if estimator.file_format in FORTRAN_ORDER else "C"
    for page in estimator.pages:
        values, axes, downsampled = page_values(page, order)
        page_dict = {
            "metadata": {
                name: str(value).replace('"', "") for name, value in page.__dict__.items() if name not in exclude
            },
            "dimensions": page.dimension,
            "data": {"unit": str(page.unit), "name": str(page.name)},
        }
        if downsampled:
            page_dict["metadata"]["downsampled"] = downsampled
        page_dict["data"]["values"] = [values.tolist()] if page.dimension == 0 else values.tolist()
        for i, axis_values in enumerate(axes):
            axis = page.plot_axis(i)
            page_dict[f"axis_dim{i + 1}"] = {
                "unit": str(axis.unit),
                "name": str(axis.name),
                "values": axis_values.tolist(),
            }
        result["pages"].append(page_dict)
    return result


def write_bdo(estimator, template: str, path: str) -> None:
    """Writes the merged estimator as a SHIELD-HIT12A .bdo file: the template (a task's file of it) with the merged
    data and the primaries of all tasks; pymchelper reads it as the merged estimator
    """
    pages = iter(estimator.pages)
    with open(template, "rb") as source, open(path, "wb") as target:
        # magic number, byte order and version, then entries: id, numpy type and number of items, the items
        target.write(source.read(24))
        while True:
            header = source.read(24)
            if len(header) < 24:
                break
            tag, kind, count = struct.unpack("<Q8sQ", header)
            dtype = np.dtype(kind.rstrip(b"\0").decode("ascii"))
            if tag not in (BDO_NSTAT, BDO_DATA):
                target.write(header + source.read(count * dtype.itemsize))
                continue
            source.seek(count * dtype.itemsize, 1)
            if tag == BDO_NSTAT:
                target.write(header + np.array([estimator.number_of_primaries], dtype=dtype).tobytes())
                continue
            page = next(pages)
            # the file keeps cumulative pages summed over primaries, the reader divides them
            scale = (
                estimator.number_of_primaries if getattr(page, "page_normalized", None) == AVERAGING_CUMULATIVE else 1
            )
            target.write(struct.pack("<Q8sQ", tag, kind, page.data_raw.size))
            for start in range(0, page.data_raw.size, WRITE_CHUNK):
                (page.data_raw[start : start + WRITE_CHUNK] * scale).astype(dtype).tofile(target)


def merge_group(corename: str, files: List[str], full_resolution: Optional[str] = None) -> Optional[dict]:
    """Merges one estimator's task files into the dict the UI reads; when a page was downsampled and full_resolution
    is given, the merged estimator is written there in full (SHIELD-HIT12A files only)
    """
    estimator = merge_estimator_files(files)
    if not estimator:
        return None
    estimator.file_corename = corename
    result = estimator_dict(estimator)
    downsampled = any("downsampled" in page["metadata"] for page in result["pages"])
    if full_resolution and downsampled and estimator.file_format == "bdo2019":
        write_bdo(estimator, files[0], full_resolution)
    return result


def merge_into(files: List[str], output_dir: str) -> int:
    """Merges the task files into one JSON file per estimator in output_dir (with the full resolution next to it,
    when downsampled); returns how many were written
    """
    written = 0
    for corename, group in group_input_files(files).items():
        estimator = merge_group(corename, group, os.path.join(output_dir, f"{corename}.bdo"))
        if estimator:
            with open(os.path.join(output_dir, f"{corename}.json"), "w") as json_file:
                json.dump(estimator, json_file)
            written += 1
    return written


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output_dir", required=True)
    # a pattern, not the files: thousands of them would pass the argument limit of the shell
    parser.add_argument("pattern")
    args = parser.parse_args()
    # nothing to merge (every task failed) fails the job, which would otherwise end with empty results
    sys.exit(0 if merge_into(sorted(glob.glob(args.pattern)), args.output_dir) else 1)
