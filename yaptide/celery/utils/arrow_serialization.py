"""
Arrow IPC serialization utilities for estimator data.

Converts estimator list[dict] to/from Arrow IPC binary format.
The large numerical `values` arrays are stored as Arrow columns for efficient
binary encoding, while metadata (estimator metadata, page metadata, axes)
is stored as JSON strings in the Arrow schema metadata.

Each page is written as a separate IPC message (using write_record_batch
in a stream) so that per-page metadata is preserved in the schema.
"""

import io
import json
import logging
import struct

import pyarrow as pa


def _page_to_record_batch(estimator_name: str, estimator_metadata: dict, page: dict) -> pa.RecordBatch:
    """Convert a single page dict to an Arrow RecordBatch with metadata."""
    values = page.get("data", {}).get("values", [])
    values_array = pa.array(values, type=pa.float64())

    # Store all non-values data as JSON in schema metadata
    page_meta = {
        "estimator_name": estimator_name,
        "estimator_metadata": json.dumps(estimator_metadata),
        "page_dimensions": str(page.get("dimensions", 0)),
        "page_metadata": json.dumps(page.get("metadata", {})),
        "data_name": page.get("data", {}).get("name", ""),
        "data_unit": page.get("data", {}).get("unit", ""),
    }

    # Include axis data if present
    for axis_key in ("axis_dim1", "axis_dim2", "axis_dim3"):
        if axis_key in page:
            page_meta[axis_key] = json.dumps(page[axis_key])

    schema = pa.schema(
        [pa.field("values", pa.float64())],
        metadata={k: v.encode("utf-8") for k, v in page_meta.items()},
    )
    return pa.record_batch([values_array], schema=schema)


def estimators_to_arrow_ipc(estimators: list[dict]) -> bytes:
    """
    Serialize a list of estimator dicts to Arrow IPC format.

    Each page is serialized as an independent IPC stream message so that
    per-page schema metadata (estimator name, page metadata, axes) is preserved.
    Messages are length-prefixed (4-byte big-endian) for reliable framing.

    Args:
        estimators: List of estimator dicts with structure:
            [{"name": str, "metadata": dict, "pages": [{"data": {"values": [...]}, ...}]}]

    Returns:
        Concatenated length-prefixed Arrow IPC messages as bytes.
    """
    output = io.BytesIO()

    for estimator in estimators:
        estimator_name = estimator.get("name", "")
        estimator_metadata = estimator.get("metadata", {})

        for page in estimator.get("pages", []):
            batch = _page_to_record_batch(estimator_name, estimator_metadata, page)

            # Write this batch as a self-contained IPC stream
            sink = pa.BufferOutputStream()
            writer = pa.ipc.new_stream(sink, batch.schema)
            writer.write_batch(batch)
            writer.close()

            ipc_bytes = sink.getvalue().to_pybytes()

            # Length-prefix the message
            output.write(struct.pack(">I", len(ipc_bytes)))
            output.write(ipc_bytes)

    return output.getvalue()


def arrow_ipc_to_estimators(data: bytes) -> list[dict]:
    """
    Deserialize Arrow IPC bytes back to a list of estimator dicts.

    Args:
        data: Concatenated length-prefixed Arrow IPC messages.

    Returns:
        List of estimator dicts in the standard format.
    """
    if not data:
        return []

    estimators_by_name: dict[str, dict] = {}
    buf = io.BytesIO(data)

    try:
        while True:
            # Read 4-byte length prefix
            length_bytes = buf.read(4)
            if len(length_bytes) < 4:
                break  # End of stream

            msg_length = struct.unpack(">I", length_bytes)[0]
            msg_bytes = buf.read(msg_length)
            if len(msg_bytes) < msg_length:
                logging.warning("Truncated Arrow IPC message, expected %d bytes got %d", msg_length, len(msg_bytes))
                break

            # Read this IPC stream (contains exactly one batch)
            reader = pa.ipc.open_stream(pa.BufferReader(msg_bytes))
            for batch in reader:
                meta = batch.schema.metadata or {}
                decoded_meta = {
                    k.decode("utf-8") if isinstance(k, bytes) else k: v.decode("utf-8") if isinstance(v, bytes) else v
                    for k, v in meta.items()
                }

                estimator_name = decoded_meta.get("estimator_name", "")

                if estimator_name not in estimators_by_name:
                    estimators_by_name[estimator_name] = {
                        "name": estimator_name,
                        "metadata": json.loads(decoded_meta.get("estimator_metadata", "{}")),
                        "pages": [],
                    }

                # Reconstruct page dict
                page = {
                    "dimensions": int(decoded_meta.get("page_dimensions", "0")),
                    "metadata": json.loads(decoded_meta.get("page_metadata", "{}")),
                    "data": {
                        "name": decoded_meta.get("data_name", ""),
                        "unit": decoded_meta.get("data_unit", ""),
                        "values": batch.column("values").to_pylist(),
                    },
                }

                # Reconstruct axis data
                for axis_key in ("axis_dim1", "axis_dim2", "axis_dim3"):
                    if axis_key in decoded_meta:
                        page[axis_key] = json.loads(decoded_meta[axis_key])

                estimators_by_name[estimator_name]["pages"].append(page)

    except Exception:
        logging.exception("Failed to deserialize Arrow IPC data")
        return []

    return list(estimators_by_name.values())
