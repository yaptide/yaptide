"""Result pages as Zarr v3 arrays: one array per page, its values as float32 and its metadata as attributes.

Written on the backend (the merges of direct simulations) and on the clusters (the merges of HPC simulations), so it
needs the standard library only: numpy and zstandard are used when there. A page is two objects, under one prefix:

- zarr.json: the array's metadata; its attributes hold the page as the UI knew it from the JSON pages, without the
  values (attributes.yaptide_page);
- c/0: one shard holding every chunk of the values. Chunks of zeros only are left out (the shard's index marks them
  empty), so sparse results take little space even without compression; with zstandard each chunk is compressed.

Any Zarr v3 reader opens the prefix (zarr-python, zarrita.js in the browser): one signed link per object. The values
are flat, in the order pymchelper keeps them (Page.data_raw), as the JSON pages had them; a page of dimension 0 has one
value.
"""

import base64
import hashlib
import json
import math
import struct
import sys
from array import array
from typing import Optional, Sequence

try:
    import numpy as np
except ImportError:  # a cluster's Python without numpy
    np = None
try:
    import zstandard
except ImportError:
    zstandard = None

# the format a stored page has (PageObjectModel.format)
FORMAT = "zarr-v3"
METADATA_FILE = "zarr.json"
SHARD_FILE = "c/0"
FILES = (METADATA_FILE, SHARD_FILE)
# values in one chunk: 256 KiB, a read of the browser fetches a few of them for a slice of a large mesh
CHUNK_ITEMS = 1 << 16
# what the values are stored as: a Monte Carlo result has far fewer significant digits than float32's 7
DATA_TYPE = "float32"
ITEM_SIZE = 4
# a chunk left out of a shard: its offset and size in the index
EMPTY = 2**64 - 1
ZSTD_LEVEL = 1
BYTES_CODEC = {"name": "bytes", "configuration": {"endian": "little"}}


def float32_bytes(values: Sequence[float]) -> bytes:
    """The values as little-endian float32"""
    if np is not None:
        return np.ravel(np.asarray(values, dtype="<f4")).tobytes()
    packed = array("f", values)
    if sys.byteorder == "big":
        packed.byteswap()
    return packed.tobytes()


def float32_values(data: bytes) -> list:
    """Little-endian float32 back to floats"""
    unpacked = array("f")
    unpacked.frombytes(data)
    if sys.byteorder == "big":
        unpacked.byteswap()
    return unpacked.tolist()


def chunk_items(count: int) -> int:
    """Values in a chunk of an array of count values"""
    return max(1, min(CHUNK_ITEMS, count))


def metadata(page: dict, count: int, compressed: bool) -> dict:
    """zarr.json of a page of count values"""
    inner = chunk_items(count)
    codecs = [BYTES_CODEC]
    if compressed:
        codecs.append({"name": "zstd", "configuration": {"level": ZSTD_LEVEL, "checksum": False}})
    return {
        "zarr_format": 3,
        "node_type": "array",
        "shape": [count],
        "data_type": DATA_TYPE,
        # one shard holds all the chunks; it may reach past the end of the array, as a last chunk does
        "chunk_grid": {"name": "regular", "configuration": {"chunk_shape": [inner * max(1, math.ceil(count / inner))]}},
        "chunk_key_encoding": {"name": "default", "configuration": {"separator": "/"}},
        "fill_value": 0.0,
        "codecs": [
            {
                "name": "sharding_indexed",
                "configuration": {
                    "chunk_shape": [inner],
                    "codecs": codecs,
                    "index_codecs": [BYTES_CODEC],
                    "index_location": "end",
                },
            }
        ],
        "attributes": {"yaptide_page": page},
    }


def shard(data: bytes, inner: int, compressor) -> bytes:
    """The shard of the values (float32 bytes): the chunks that are not all zeros, then the index"""
    chunk_bytes = inner * ITEM_SIZE
    body, index = [], []
    offset = 0
    for start in range(0, len(data), chunk_bytes):
        chunk = data[start : start + chunk_bytes]
        # the last chunk is whole in the shard, filled up with the fill value
        chunk += bytes(chunk_bytes - len(chunk))
        if not any(chunk):
            index.append((EMPTY, EMPTY))
            continue
        if compressor is not None:
            chunk = compressor.compress(chunk)
        body.append(chunk)
        index.append((offset, len(chunk)))
        offset += len(chunk)
    return b"".join(body) + b"".join(struct.pack("<QQ", *entry) for entry in index)


def page_files(page: dict, values: Sequence[float], compress: bool = True) -> dict:
    """The objects of a page: name -> bytes; page is the page as the UI reads it, without its values"""
    data = float32_bytes(values)
    count = len(data) // ITEM_SIZE
    compressor = zstandard.ZstdCompressor(level=ZSTD_LEVEL) if compress and zstandard is not None else None
    meta = metadata(page, count, compressor is not None)
    files = {METADATA_FILE: json.dumps(meta).encode()}
    if count:
        files[SHARD_FILE] = shard(data, chunk_items(count), compressor)
    return files


def body_md5(body: bytes) -> str:
    """MD5 of an object's body in base64, as the Content-MD5 header carries it"""
    # the checksum S3 asks for, not a security measure
    return base64.b64encode(hashlib.md5(body).digest()).decode()  # skipcq: PTC-W1003


def content_type(name: str) -> str:
    """Content type of a page's object"""
    return "application/json" if name == METADATA_FILE else "application/octet-stream"


def read_page(files: dict) -> tuple:
    """A page's objects (name -> bytes) back to the page without values and its values (a list of floats); a page
    compressed with zstd needs zstandard. Reads the pages written here, not every Zarr array.
    """
    meta = json.loads(files[METADATA_FILE])
    count = meta["shape"][0]
    config = meta["codecs"][0]["configuration"]
    inner = config["chunk_shape"][0]
    compressed = any(codec["name"] == "zstd" for codec in config["codecs"])
    decompressor: Optional[object] = None
    if compressed:
        if zstandard is None:
            raise ValueError("the page is compressed with zstd, which needs the zstandard module")
        decompressor = zstandard.ZstdDecompressor()
    data = bytearray()
    if count:
        body = files[SHARD_FILE]
        chunks = math.ceil(meta["chunk_grid"]["configuration"]["chunk_shape"][0] / inner)
        index = body[len(body) - 16 * chunks :]
        for number in range(chunks):
            offset, size = struct.unpack_from("<QQ", index, 16 * number)
            if offset == EMPTY:
                data += bytes(inner * ITEM_SIZE)
                continue
            chunk = body[offset : offset + size]
            data += decompressor.decompress(chunk, max_output_size=inner * ITEM_SIZE) if decompressor else chunk
    return meta["attributes"]["yaptide_page"], float32_values(bytes(data[: count * ITEM_SIZE]))


def json_page(page: dict, values: list) -> dict:
    """The page as the JSON pages had it, values included"""
    return dict(page, data=dict(page["data"], values=values))
