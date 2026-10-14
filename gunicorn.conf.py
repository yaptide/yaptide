"""gunicorn settings, read automatically from the working directory of the Flask image"""

import os

# measured: ~110-150 MB per sync worker, up to ~300 MB while it handles a large /results upload
MB_PER_WORKER = 300
# every worker keeps a Postgres connection open, next to the engine and its Ray workers - more would run into
# Postgres' default limit of 100 connections on a big machine, and the workers that can't connect stop the server
MAX_WORKERS = 32


def available_cpus() -> int:
    """CPUs the container may use: its cgroup quota if set, otherwise the CPUs it may run on"""
    try:
        with open("/sys/fs/cgroup/cpu.max") as cpu_max:
            quota, period = cpu_max.read().split()
        if quota != "max":
            return max(1, int(quota) // int(period))
    except (OSError, ValueError):
        pass
    if hasattr(os, "sched_getaffinity"):  # not on macOS
        return len(os.sched_getaffinity(0))
    return os.cpu_count() or 1


def available_memory_mb() -> int:
    """Memory the workers may use: the container limit if set, otherwise what the machine has available"""
    try:
        with open("/sys/fs/cgroup/memory.max") as memory_max:
            limit = memory_max.read().strip()
        if limit != "max":
            return int(limit) // 2**20
    except (OSError, ValueError):
        pass
    try:
        with open("/proc/meminfo") as meminfo:
            for line in meminfo:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except OSError:  # not Linux, e.g. macOS
        pass
    # unknown - leave the limit to the CPUs and MAX_WORKERS
    return MB_PER_WORKER * MAX_WORKERS


def default_workers() -> int:
    """gunicorn's guideline for sync workers, 2 x CPUs + 1, capped by what fits in memory and by MAX_WORKERS"""
    return max(1, min(2 * available_cpus() + 1, available_memory_mb() // MB_PER_WORKER, MAX_WORKERS))


# sync workers - for the short CPU-bound status requests they kept p99 at 0.3-0.4 s where gthread 4x8 reached
# 3.5-11 s (replayed 5000-task Ares traffic, 2 CPUs); each one serves a single request at a time, so slow
# requests are absorbed by having more of them
# GUNICORN_WORKERS is taken as given, also above MAX_WORKERS - then raise Postgres' max_connections to match
workers = max(1, int(os.environ.get("GUNICORN_WORKERS") or default_workers()))
# lets large /results uploads finish instead of killing them mid-write after the default 30 s
timeout = int(os.environ.get("GUNICORN_TIMEOUT") or 300)
accesslog = "-"
bind = "0.0.0.0:6000"
