"""Pages in ZARR_FORMAT where zstandard is missing (a cluster's Python): compressed with gzip, read back the same"""

import gzip
import json

import pytest

from yaptide.batch import result_format

PAGE = {"name": "dose", "data": {"unit": "Gy"}}
# sparse, as a large mesh's dose: two chunks of zeros left out, two with values
VALUES = [0.0] * (2 * result_format.CHUNK_ITEMS) + [float(i % 7) for i in range(2 * result_format.CHUNK_ITEMS)]


def inner_codecs(files: dict) -> list:
    """The codecs of a page's chunks, from its zarr.json"""
    return json.loads(files[result_format.METADATA_FILE])["codecs"][0]["configuration"]["codecs"]


def test_gzip_without_zstandard(monkeypatch: pytest.MonkeyPatch):
    """Without zstandard the chunks are gzip members, the codec says so, and the page reads back whole"""
    monkeypatch.setattr(result_format, "zstandard", None)

    files = result_format.page_files(PAGE, VALUES)

    assert inner_codecs(files) == [result_format.BYTES_CODEC, {"name": "gzip", "configuration": {"level": 1}}]
    assert len(files[result_format.SHARD_FILE]) < len(VALUES)
    assert result_format.read_page(files) == (PAGE, VALUES)
    # the same values give the same bytes (no time in the gzip header), so a page's checksum is stable
    assert result_format.page_files(PAGE, VALUES) == files


def test_gzip_chunk_is_a_gzip_member(monkeypatch: pytest.MonkeyPatch):
    """Any Zarr reader's gzip codec opens a chunk: the first stored chunk is the third chunk of values"""
    monkeypatch.setattr(result_format, "zstandard", None)

    shard = result_format.page_files(PAGE, VALUES)[result_format.SHARD_FILE]
    index = shard[-16 * 4 :]
    offset, size = int.from_bytes(index[32:40], "little"), int.from_bytes(index[40:48], "little")

    expected = result_format.float32_bytes(VALUES[2 * result_format.CHUNK_ITEMS : 3 * result_format.CHUNK_ITEMS])
    assert gzip.decompress(shard[offset : offset + size]) == expected


def test_uncompressed_stays_raw(monkeypatch: pytest.MonkeyPatch):
    """compress=False still writes the raw chunks, with no codec but bytes"""
    monkeypatch.setattr(result_format, "zstandard", None)

    files = result_format.page_files(PAGE, VALUES, compress=False)

    assert inner_codecs(files) == [result_format.BYTES_CODEC]
    assert result_format.read_page(files) == (PAGE, VALUES)
