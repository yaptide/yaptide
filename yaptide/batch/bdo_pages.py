"""Reads SHIELD-HIT12A result files (.bdo, the token format of 2019) page by page, skipping the pages not wanted.

SHIELD-HIT12A writes every page of an estimator into its file at every save, a large 3D map with the small depth-dose
line beside it. pymchelper reads a file whole (each token's values into memory), so a partial result that needs the
line only would read the map too. These functions walk the file's tokens and copy out only the pages wanted: the
values of the other pages are never read, the file is only seeked past them. The copy is a .bdo file pymchelper reads
as usual, so the values are read exactly as before.

A file is a header (magic number, byte order, version) and tokens: an id, a numpy type and a number of items, then the
items. The estimator's tokens (its mesh among them) come first, then each page: its detector type token begins it,
its differential binning follows, its data block ends it.

Standard library only: the watchers on the clusters copy saves with it (watcher.py), next to this script.
"""

import os
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Callable, List, Optional, Tuple

HEADER_BYTES = 24
MAGIC = b"xSH12A"
TOKEN = struct.Struct("<Q8sQ")
# the token ids (pymchelper.readers.shieldhit.binary_spec.SHBDOTagID)
FORMAT = 0x05
GEO_N_BINS = 0xE004
DETECTOR_TYPE = 0xDD30
PAGE_NUMBER = 0xDD31
PAGE_DIFF_SIZE = 0xDDD4
DATA_BLOCK = 0xDDBB
# a list of particles (SHDetType.mcpl): not a page of bins
MCPL = 63
# the FORMAT of a file of the token format of 2019 (pymchelper's SHFileFormatId.bdo2019), the one read here
BDO2019 = 2
# copies values through a buffer of this size
COPY_BYTES = 1 << 20
NUMPY_TYPE = re.compile(r"^[<>|=]?([a-zA-Z])(\d+)$")


class BdoError(ValueError):
    """Not a SHIELD-HIT12A result file of the token format, or one with a token past its end"""


@dataclass
class PageInfo:
    """A page of a result file: its dimensions (axes with more than one bin, differential ones included), whether it
    is a list of particles, the bytes of its values, its number (the page number the file gives it, else its place in
    the file, from 0: the number its results are stored under) and its detector type
    """

    dimensions: int
    mcpl: bool
    data_bytes: int
    number: int = 0
    detector_type: int = 0


@dataclass
class _Page:
    """A page being read: its tokens so far, kept in memory (all small but the data block)"""

    tokens: List[bytes] = field(default_factory=list)
    detector_type: Optional[int] = None
    diff_sizes: Tuple[int, ...] = ()
    number: Optional[int] = None


@dataclass
class Walked:
    """What a walk through a result file found: its pages, which of them were kept, whether it ended with a whole
    page (a file the simulator is still writing ends within one), and its FORMAT (None when it gives none)
    """

    pages: List[PageInfo]
    kept: List[bool]
    whole: bool
    file_format: Optional[int] = None


def item_size(kind: bytes) -> int:
    """Bytes of an item of a token's numpy type (e.g. <f8, <i8, S24)"""
    match = NUMPY_TYPE.match(kind.rstrip(b"\0").decode("ascii", "replace"))
    if not match:
        raise BdoError(f"unknown token type {kind!r}")
    return int(match[2])


def int_values(payload: bytes) -> Tuple[int, ...]:
    """The 64-bit integers of a token"""
    return struct.unpack(f"<{len(payload) // 8}q", payload[: len(payload) // 8 * 8])


def page_dimensions(mesh_bins: Tuple[int, ...], diff_sizes: Tuple[int, ...]) -> int:
    """The axes of a page with more than one bin: of its estimator's mesh and of its differential binning, as
    pymchelper's Page.dimension
    """
    return sum(1 for bins in mesh_bins if bins > 1) + sum(1 for bins in diff_sizes if bins > 1)


def _read_exact(file: BinaryIO, size: int) -> bytes:
    """size bytes, or BdoError when the file ends sooner"""
    data = file.read(size)
    if len(data) < size:
        raise BdoError("the file ends within a token")
    return data


def _copy(source: BinaryIO, target: BinaryIO, size: int) -> None:
    """Copies size bytes"""
    while size:
        chunk = source.read(min(size, COPY_BYTES))
        if not chunk:
            raise BdoError("the file ends within a token")
        target.write(chunk)
        size -= len(chunk)


def walk(source: BinaryIO, keep: Callable[[PageInfo], bool], target: Optional[BinaryIO] = None) -> Walked:
    """Walks a result file's tokens: with a target, copies the estimator's tokens and the pages keep wants into it"""
    header = source.read(HEADER_BYTES)
    if len(header) < HEADER_BYTES or not header.startswith(MAGIC):
        raise BdoError("not a SHIELD-HIT12A result file of the token format")
    size = os.fstat(source.fileno()).st_size
    if target is not None:
        target.write(header)
    mesh_bins: Tuple[int, ...] = ()
    file_format: Optional[int] = None
    pages: List[PageInfo] = []
    kept: List[bool] = []
    # tokens after a page's data block (or the estimator's) wait for the next detector type: they go with it
    page: Optional[_Page] = None
    waiting: List[bytes] = []
    while True:
        head = source.read(TOKEN.size)
        if not head:
            break
        if len(head) < TOKEN.size:
            raise BdoError("the file ends within a token")
        token_id, kind, count = TOKEN.unpack(head)
        payload_bytes = count * item_size(kind)
        if payload_bytes > size - source.tell():
            raise BdoError("a token reaches past the end of the file")
        if token_id == DATA_BLOCK:
            if page is None:
                raise BdoError("a data block outside of a page")
            info = PageInfo(
                dimensions=page_dimensions(mesh_bins, page.diff_sizes),
                mcpl=page.detector_type == MCPL,
                data_bytes=payload_bytes,
                number=len(pages) if page.number is None else page.number,
                detector_type=page.detector_type or 0,
            )
            wanted = keep(info)
            pages.append(info)
            kept.append(wanted)
            if wanted and target is not None:
                target.write(b"".join(page.tokens))
                target.write(head)
                _copy(source, target, payload_bytes)
            else:
                source.seek(payload_bytes, os.SEEK_CUR)
            page = None
            continue
        token = head + _read_exact(source, payload_bytes)
        if token_id == DETECTOR_TYPE:
            if page is not None:
                raise BdoError("a page without its data block")
            page = _Page(tokens=waiting + [token], detector_type=int_values(token[TOKEN.size :])[0])
            waiting = []
        elif page is not None:
            page.tokens.append(token)
            if token_id == PAGE_DIFF_SIZE:
                page.diff_sizes = int_values(token[TOKEN.size :])
            elif token_id == PAGE_NUMBER:
                page.number = int_values(token[TOKEN.size :])[0]
        elif pages:
            waiting.append(token)
        else:
            # the estimator's own tokens
            if token_id == GEO_N_BINS:
                mesh_bins = int_values(token[TOKEN.size :])
            elif token_id == FORMAT:
                file_format = int_values(token[TOKEN.size :])[0]
            if target is not None:
                target.write(token)
    if target is not None and page is None:
        target.write(b"".join(waiting))
    return Walked(pages, kept, page is None, file_format)


def pages_of(path: Path) -> List[PageInfo]:
    """The pages of a result file, its values not read; BdoError when cut short within a page"""
    with open(path, "rb") as source:
        walked = walk(source, lambda info: False)
    if not walked.whole:
        raise BdoError(f"{path}: the file ends within a page")
    return walked.pages


def copy_file(source_path: Path, target_path: Path, keep: Callable[[PageInfo], bool]) -> Walked:
    """Copies a result file with only the pages keep wants (the estimator's tokens all kept); what the walk found.
    BdoError when the file is cut short within a page: the copy would miss it
    """
    with open(source_path, "rb") as source, open(target_path, "wb") as target:
        walked = walk(source, keep, target)
    if not walked.whole:
        raise BdoError(f"{source_path}: the file ends within a page")
    return walked


def copy_pages(source_path: Path, target_path: Path, keep: Callable[[PageInfo], bool]) -> int:
    """Copies a result file with only the pages keep wants (copy_file); the pages copied"""
    return sum(copy_file(source_path, target_path, keep).kept)
