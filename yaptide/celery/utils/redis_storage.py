"""
Redis storage utilities for partial simulation results.

Stores per-task estimator data (Arrow IPC bytes) in the existing
Celery broker Redis instance. Each task's result overwrites any
previous value for the same task, and keys auto-expire after TTL.
"""

import logging
import os
from typing import Optional

import redis

# Default TTL for partial results: 24 hours
PARTIAL_RESULTS_TTL_SECONDS = 24 * 60 * 60

# Key prefix for partial results
_KEY_PREFIX = "partial"


def _make_key(simulation_id: int, task_id: int) -> str:
    """Build Redis key for a specific task's partial result."""
    return f"{_KEY_PREFIX}:{simulation_id}:{task_id}"


def _make_pattern(simulation_id: int) -> str:
    """Build Redis key pattern for all partial results of a simulation."""
    return f"{_KEY_PREFIX}:{simulation_id}:*"


def get_redis_client() -> Optional[redis.Redis]:
    """
    Create a Redis client from the CELERY_BROKER_URL environment variable.

    Returns None if the URL is not configured, allowing graceful degradation.
    """
    broker_url = os.environ.get("CELERY_BROKER_URL")
    if not broker_url:
        logging.warning("CELERY_BROKER_URL not set, partial results storage unavailable")
        return None
    try:
        return redis.Redis.from_url(broker_url, decode_responses=False)
    except Exception:
        logging.exception("Failed to create Redis client from CELERY_BROKER_URL")
        return None


def store_partial_result(simulation_id: int, task_id: int, ipc_bytes: bytes) -> bool:
    """
    Store a single task's estimator data (Arrow IPC bytes) in Redis.

    Overwrites any previous result for the same simulation_id/task_id.

    Args:
        simulation_id: Simulation database ID.
        task_id: Task index within the simulation.
        ipc_bytes: Arrow IPC serialized estimator data.

    Returns:
        True if stored successfully, False otherwise.
    """
    client = get_redis_client()
    if client is None:
        return False
    try:
        key = _make_key(simulation_id, task_id)
        client.set(key, ipc_bytes, ex=PARTIAL_RESULTS_TTL_SECONDS)
        logging.debug(
            "Stored partial result for simulation %d, task %d (%d bytes)", simulation_id, task_id, len(ipc_bytes)
        )
        return True
    except Exception:
        logging.exception("Failed to store partial result for simulation %d, task %d", simulation_id, task_id)
        return False


def get_all_partial_results(simulation_id: int) -> list[tuple[int, bytes]]:
    """
    Retrieve all stored partial results for a simulation.

    Returns:
        List of (task_id, ipc_bytes) tuples, sorted by task_id.
    """
    client = get_redis_client()
    if client is None:
        return []
    try:
        pattern = _make_pattern(simulation_id)
        results = []
        for key in client.scan_iter(match=pattern):
            key_str = key.decode("utf-8") if isinstance(key, bytes) else key
            # Extract task_id from key "partial:{sim_id}:{task_id}"
            parts = key_str.split(":")
            if len(parts) == 3:
                task_id = int(parts[2])
                data = client.get(key)
                if data is not None:
                    results.append((task_id, data))
        results.sort(key=lambda x: x[0])
        return results
    except Exception:
        logging.exception("Failed to get partial results for simulation %d", simulation_id)
        return []


def get_partial_result_count(simulation_id: int) -> int:
    """Return the number of partial results stored for a simulation."""
    client = get_redis_client()
    if client is None:
        return 0
    try:
        pattern = _make_pattern(simulation_id)
        count = 0
        for _ in client.scan_iter(match=pattern):
            count += 1
        return count
    except Exception:
        logging.exception("Failed to count partial results for simulation %d", simulation_id)
        return 0


def cleanup_partial_results(simulation_id: int) -> bool:
    """
    Delete all partial result keys for a simulation.

    Should be called after final merge completes.

    Returns:
        True if cleanup succeeded, False otherwise.
    """
    client = get_redis_client()
    if client is None:
        return False
    try:
        pattern = _make_pattern(simulation_id)
        keys = list(client.scan_iter(match=pattern))
        if keys:
            client.delete(*keys)
            logging.info("Cleaned up %d partial result keys for simulation %d", len(keys), simulation_id)
        return True
    except Exception:
        logging.exception("Failed to cleanup partial results for simulation %d", simulation_id)
        return False
