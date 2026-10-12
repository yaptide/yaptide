"""gunicorn settings, read automatically from the working directory of the Flask image"""

import os

# measured: ~110-150 MB per sync worker, up to ~300 MB while it handles a large /results upload
MB_PER_WORKER = 300


def available_cpus() -> int:
    """CPUs the container may use: its cgroup quota if set, otherwise the CPUs it may run on"""
    try:
        with open("/sys/fs/cgroup/cpu.max") as cpu_max:
            quota, period = cpu_max.read().split()
        if quota != "max":
            return max(1, int(quota) // int(period))
    except (OSError, ValueError):
        pass
    return len(os.sched_getaffinity(0))


def available_memory_mb() -> int:
    """Memory the workers may use: the container limit if set, otherwise what the machine has available"""
    try:
        with open("/sys/fs/cgroup/memory.max") as memory_max:
            limit = memory_max.read().strip()
        if limit != "max":
            return int(limit) // 2**20
    except (OSError, ValueError):
        pass
    with open("/proc/meminfo") as meminfo:
        for line in meminfo:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    return MB_PER_WORKER


def default_workers() -> int:
    """gunicorn's guideline for sync workers, 2 x CPUs + 1, capped by what fits in memory"""
    return max(1, min(2 * available_cpus() + 1, available_memory_mb() // MB_PER_WORKER))


# sync workers - for the short CPU-bound status requests they kept p99 at 0.3-0.4 s where gthread 4x8 reached
# 3.5-11 s (replayed 5000-task Ares traffic, 2 CPUs); each one serves a single request at a time, so slow
# requests are absorbed by having more of them
workers = int(os.environ.get("GUNICORN_WORKERS") or default_workers())
# lets large /results uploads finish instead of killing them mid-write after the default 30 s
timeout = int(os.environ.get("GUNICORN_TIMEOUT") or 300)
accesslog = "-"
bind = "0.0.0.0:6000"
