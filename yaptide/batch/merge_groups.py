"""Merges of an HPC simulation's results in two tiers on the cluster, for results too large for one merge to be quick.

The tasks are split into groups of consecutive tasks (merge_groups.json in the simulation's directory, written by the
first to need it, from the size of a task's result files): each group's files are merged on their own, and the last
merge takes one merged file per group instead of one file per task. Every merge streams one file at a time
(results_merger.py), so it needs about twice the largest estimator at either tier; the groups save reading time: the
group merges run on different nodes at once, and the last merge reads one task's worth of results per group.
Results whose files fit in GROUP_BYTES altogether are one group: a single merge, as without groups.

- partial results: a task's watcher starts the partial script for the task's group, holding the group's lock
  (partial.lock.<group>). The group's latest saves are merged into groups/<group>/<primaries>/, then the one getting
  the last lock (partial.lock.final) merges the latest of every group and uploads it.
- final results: the last task of a group to end merges the group's result files into groups/<group>/final/; the
  collect merges those, and the result files of a group whose merge is missing.

Merged files of a group are pymchelper's estimators pickled (INTERMEDIATE_SUFFIX), averages kept as float64 with their
primaries, so a second merge weighs them as the first did; only this simulation's scripts write and read them.

Planning groups and taking locks needs the standard library only (the watcher imports this module); merging imports
results_merger, which needs pymchelper.

    python3 merge_groups.py partial --root DIR --group N --sim_id ID --update_key KEY --backend_url URL
    python3 merge_groups.py task_end --root DIR --task N --ntasks N
    python3 merge_groups.py collect --root DIR --ntasks N --output_dir OUT
"""

import argparse
import json
import logging
import math
import os
import pickle
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import List, Optional

# the plan of the groups, in the simulation's directory
PLAN_FILE = "merge_groups.json"
# the groups' merged files, in the simulation's directory: groups/<group>/<primaries>/ and groups/<group>/final/
GROUPS_DIR = "groups"
FINAL_DIR = "final"
INTERMEDIATE_SUFFIX = ".pkl"
# the result files one merge reads at most, about: a merge reads some 0.5-1 GB/s from a cluster's shared filesystem
GROUP_BYTES = 2 << 30
# locks of the partial merges, in the simulation's directory: one per group, and the last merge's
PARTIAL_LOCK = "partial.lock"
# when the last partial merge started (partial.stamp.final), as the watchers stamp the merges of the groups
PARTIAL_STAMP = "partial.stamp"
FINAL_LOCK = "final"
# what holds a lock: the process group of the merge (the watcher stops it by that)
OWNER_FILE = "owner"
# a lock older than this was left by a merge that was killed (its task ended, or its node failed)
LOCK_SECONDS = 3600
# the last partial merge runs at most this often; the watchers start group merges as often (watcher.py)
PARTIAL_SECONDS = 120
# a last partial merge that failed is tried again this soon
RETRY_SECONDS = 20
# merged saves kept of each group: the latest, and the one before for a last merge still reading it
KEPT_MERGES = 2
# the collect waits this long for a group's merge still running (the group's last task ended a moment ago)
GROUP_WAIT_SECONDS = 600
GROUP_POLL_SECONDS = 5
# where the partial results are merged into before they are uploaded
PARTIAL_OUTPUT = "partial_output"


def group_size(task_bytes: int, n_tasks: int) -> int:
    """Tasks in a group: all of them when their files fit in GROUP_BYTES; otherwise as many as fit, but at least
    the square root of the tasks, so that neither tier reads many more files than the other
    """
    if n_tasks <= 2 or task_bytes * n_tasks <= GROUP_BYTES:
        return max(1, n_tasks)
    size = max(math.ceil(math.sqrt(n_tasks)), GROUP_BYTES // max(1, task_bytes), 2)
    return min(size, n_tasks)


def groups(size: int, n_tasks: int) -> int:
    """Groups of size tasks"""
    return max(1, math.ceil(n_tasks / size))


def group_of(task: int, size: int, n_tasks: int) -> int:
    """The group of a task (numbered from 1, as SLURM's array tasks); groups are numbered from 0"""
    return min((task - 1) // size, groups(size, n_tasks) - 1)


def group_tasks(group: int, size: int, n_tasks: int) -> range:
    """The tasks of a group"""
    return range(group * size + 1, min((group + 1) * size, n_tasks) + 1)


def task_dir(root: Path, task: int) -> Path:
    """A task's directory, as the submit script makes it"""
    return root / "workspaces" / f"task_{task:04d}"


def files_size(directory: Path) -> int:
    """Bytes of the result files in a directory"""
    return sum(path.stat().st_size for path in directory.glob("*.bdo"))


def read_plan(root: Path) -> Optional[int]:
    """The group size, if planned already"""
    try:
        return int(json.loads((root / PLAN_FILE).read_text())["group_size"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def plan(root: Path, n_tasks: int, task_bytes: int) -> int:
    """The group size: the one planned, or planned now from the size of a task's result files. The first to plan
    wins (a link fails when the file exists), so every task and the collect agree
    """
    size = read_plan(root)
    if size is not None:
        return size
    temporary = root / f".{PLAN_FILE}.{uuid.uuid4().hex}"
    temporary.write_text(
        json.dumps({"group_size": group_size(task_bytes, n_tasks), "tasks": n_tasks, "task_bytes": task_bytes})
    )
    try:
        os.link(str(temporary), str(root / PLAN_FILE))
    except FileExistsError:
        pass
    finally:
        temporary.unlink()
    return read_plan(root) or n_tasks


def lock_path(root: Path, name) -> Path:
    """A lock of the partial merges: a group's (by its number) or the last merge's (FINAL_LOCK)"""
    return root / f"{PARTIAL_LOCK}.{name}"


def take_lock(path: Path, max_age: float = LOCK_SECONDS) -> bool:
    """Takes a lock (a directory: making one is atomic on a shared filesystem); one older than max_age is taken
    over. False when another holds it
    """
    try:
        path.mkdir()
        return True
    except FileExistsError:
        pass
    try:
        if time.time() - path.stat().st_mtime < max_age:
            return False
        shutil.rmtree(str(path))
        path.mkdir()
        return True
    except OSError:
        # another took it meanwhile
        return False


def own_lock(path: Path) -> None:
    """Marks the lock as held by this process's group: the watcher that started the merge frees it when it stops
    the merge
    """
    try:
        (path / OWNER_FILE).write_text(str(os.getpgrp()))
    except OSError:
        pass


def free_lock(path: Path, owner: Optional[int] = None) -> None:
    """Frees a lock this process holds, or one held by owner's merge (or by no one yet)"""
    try:
        held_by = int((path / OWNER_FILE).read_text())
    except FileNotFoundError:
        held_by = None
    except (OSError, ValueError):
        return
    if held_by is None or held_by == (os.getpgrp() if owner is None else owner):
        shutil.rmtree(str(path), ignore_errors=True)


def free_locks(root: Path, owner: int, group: int) -> None:
    """Frees the locks a stopped merge held: the group's it was started for, and the last merge's"""
    for name in (group, FINAL_LOCK):
        free_lock(lock_path(root, name), owner)


def stamp_due(path: Path, seconds: float) -> bool:
    """Whether the stamp is older than seconds (or missing); touches it then"""
    try:
        if time.time() - path.stat().st_mtime < seconds:
            return False
    except FileNotFoundError:
        pass
    path.touch()
    return True


def numbered_dirs(directory: Path) -> List[Path]:
    """The directories named by a number (primaries) in a directory, from the lowest"""
    if not directory.is_dir():
        return []
    return sorted(
        (path for path in directory.iterdir() if path.is_dir() and path.name.isdigit()), key=lambda p: int(p.name)
    )


def latest_save(task_path: Path) -> Optional[Path]:
    """A task's latest whole save (the watcher names each by its primaries)"""
    saves = numbered_dirs(task_path / "saves")
    return saves[-1] if saves else None


def write_merged(files: List[str], target: Path) -> int:
    """Merges the files into one pickled estimator each in target, whole or not at all (written aside, then renamed);
    the primaries merged
    """
    try:
        from yaptide.batch import results_merger
    except ImportError:  # on a cluster, next to this script
        import results_merger

    partial = target.parent / f".{target.name}.{uuid.uuid4().hex}"
    partial.mkdir(parents=True)
    primaries = 0
    try:
        for name, estimator in results_merger.merged_estimators(files):
            with open(partial / f"{name}{INTERMEDIATE_SUFFIX}", "wb") as file:
                pickle.dump(estimator, file, protocol=pickle.HIGHEST_PROTOCOL)
            primaries = max(primaries, int(estimator.number_of_primaries))
            del estimator
            results_merger.collect_garbage()
        shutil.rmtree(str(target), ignore_errors=True)
        partial.rename(target)
    finally:
        shutil.rmtree(str(partial), ignore_errors=True)
    return primaries


def merged_files(directory: Path) -> List[str]:
    """The merged files of a group in a directory"""
    return sorted(str(path) for path in directory.glob(f"*{INTERMEDIATE_SUFFIX}"))


def unreadable(err: Exception, units: List[List[str]]) -> Optional[int]:
    """Which of the merge's units (a task's save, a group's merge) holds the file it could not read whole
    (results_merger.ResultFileError: cut short, or removed meanwhile); None for another error
    """
    file = getattr(err, "file", None)
    return next((index for index, unit in enumerate(units) if file is not None and file in unit), None)


def merge_group_saves(root: Path, group: int, size: int, n_tasks: int) -> None:
    """Merges the latest saves of the group's tasks into groups/<group>/<their primaries>/, unless merged already;
    a save that cannot be read whole is left out (the next merge takes the task's next save). The older merges but
    the latest KEPT_MERGES go
    """
    saves = [latest_save(task_dir(root, task)) for task in group_tasks(group, size, n_tasks)]
    saves = [save for save in saves if save is not None]
    units = [[str(path) for path in sorted(save.glob("*.bdo"))] for save in saves]
    group_dir = root / GROUPS_DIR / str(group)
    while saves:
        target = group_dir / str(sum(int(save.name) for save in saves))
        if target.exists():
            return
        try:
            write_merged([file for unit in units for file in unit], target)
            break
        except ValueError as err:
            index = unreadable(err, units)
            if index is None:
                raise
            logging.warning("Left out the save %s of group %d: %s", saves[index], group, err)
            del saves[index], units[index]
    if not saves:
        return
    logging.info("Merged the saves of group %d: %d tasks, %s primaries", group, len(saves), target.name)
    for old in numbered_dirs(group_dir)[:-KEPT_MERGES]:
        shutil.rmtree(str(old), ignore_errors=True)


def partial_units(root: Path, size: int, n_tasks: int) -> List[List[str]]:
    """What the last partial merge reads: the latest merge of every group that has one, or with one group, the
    latest saves of its tasks. A group without a merge yet waits for it: reading its tasks' saves instead took
    minutes with large results, while the tasks removed them for newer ones
    """
    if size < n_tasks:
        merges = (numbered_dirs(root / GROUPS_DIR / str(group)) for group in range(groups(size, n_tasks)))
        return [merged_files(group_merges[-1]) for group_merges in merges if group_merges]
    saves = (latest_save(task_dir(root, task)) for task in range(1, n_tasks + 1))
    return [[str(path) for path in sorted(save.glob("*.bdo"))] for save in saves if save is not None]


def merge_and_upload(root: Path, units: List[List[str]], args) -> int:
    """Merges the units' files into partial results and uploads them (results_uploader.py, beside this script); a
    unit with a file that cannot be read whole is left out
    """
    try:
        from yaptide.batch import results_merger
    except ImportError:  # on a cluster, next to this script
        import results_merger

    units = [unit for unit in units if unit]
    output = root / PARTIAL_OUTPUT
    try:
        while True:
            if not units:
                return 0
            shutil.rmtree(str(output), ignore_errors=True)
            output.mkdir()
            files = [file for unit in units for file in unit]
            try:
                manifest = results_merger.write_directory(files, output)
                break
            except ValueError as err:
                index = unreadable(err, units)
                if index is None:
                    raise
                logging.warning("Left out %s from the partial results: %s", Path(units[index][0]).parent, err)
                del units[index]
        if not manifest["estimators"]:
            return 1
        logging.info("Merged %d files into partial results of %d primaries", len(files), manifest["primaries"])
        uploader = Path(__file__).resolve().parent / "results_uploader.py"
        command = [sys.executable, str(uploader), "--partial", f"--output_dir={output}", "--attempts=3"]
        command += [f"--sim_id={args.sim_id}", f"--update_key={args.update_key}", f"--backend_url={args.backend_url}"]
        return subprocess.run(command, check=False).returncode
    finally:
        shutil.rmtree(str(output), ignore_errors=True)


def partial(args) -> int:
    """Partial results, started by a task's watcher holding the lock of its group: the group's latest saves merged,
    then, by the one getting the last lock, the latest of every group merged and uploaded. One group: its saves are
    the whole simulation's, merged and uploaded at once
    """
    root = Path(args.root)
    group_lock = lock_path(root, args.group)
    own_lock(group_lock)
    try:
        size = read_plan(root)
        n_tasks = args.ntasks
        if size is None:
            return 1
        if size >= n_tasks:
            return merge_and_upload(root, partial_units(root, size, n_tasks), args)
        merge_group_saves(root, args.group, size, n_tasks)
    finally:
        free_lock(group_lock)
    final_lock = lock_path(root, FINAL_LOCK)
    stamp = root / f"{PARTIAL_STAMP}.{FINAL_LOCK}"
    if not stamp_due(stamp, PARTIAL_SECONDS) or not take_lock(final_lock):
        return 0
    own_lock(final_lock)
    code = 1
    try:
        code = merge_and_upload(root, partial_units(root, size, n_tasks), args)
        return code
    finally:
        free_lock(final_lock)
        if code:
            retry_soon(stamp)


def retry_soon(stamp: Path) -> None:
    """A last partial merge that failed is tried again by a group merge RETRY_SECONDS later, not PARTIAL_SECONDS"""
    try:
        when = time.time() - PARTIAL_SECONDS + RETRY_SECONDS
        os.utime(str(stamp), (when, when))
    except OSError:
        pass


def done(root: Path, task: int) -> bool:
    """Whether the task ended (the array script marks it)"""
    return (root / "done" / f"task_{task}").exists()


def task_end(args) -> int:
    """The task ended: the last of its group to end merges the group's result files into groups/<group>/final/"""
    root = Path(args.root)
    size = plan(root, args.ntasks, files_size(task_dir(root, args.task)))
    if size >= args.ntasks:
        return 0
    group = group_of(args.task, size, args.ntasks)
    tasks = group_tasks(group, size, args.ntasks)
    if not all(done(root, task) for task in tasks):
        return 0
    group_dir = root / GROUPS_DIR / str(group)
    group_dir.mkdir(parents=True, exist_ok=True)
    lock = group_dir / f"{FINAL_DIR}.lock"
    if (group_dir / FINAL_DIR).exists() or not take_lock(lock):
        return 0
    try:
        files = [str(path) for task in tasks for path in sorted(task_dir(root, task).glob("*.bdo"))]
        write_merged(files, group_dir / FINAL_DIR)
    finally:
        shutil.rmtree(str(lock), ignore_errors=True)
    logging.info("Merged the results of tasks %d-%d", tasks.start, tasks.stop - 1)
    return 0


def final_files(root: Path, n_tasks: int, wait_seconds: float = GROUP_WAIT_SECONDS) -> List[str]:
    """What the collect merges: the final merge of every group (waiting a while for one still running), or the
    result files of a group's tasks when the group has none
    """
    files = []
    size = read_plan(root)
    if size is None:
        first = next((task_dir(root, task) for task in range(1, n_tasks + 1) if files_size(task_dir(root, task))), None)
        size = plan(root, n_tasks, files_size(first)) if first else n_tasks
    deadline = time.monotonic() + wait_seconds
    for group in range(groups(size, n_tasks)):
        tasks = group_tasks(group, size, n_tasks)
        group_dir = root / GROUPS_DIR / str(group)
        if size < n_tasks:
            lock = group_dir / f"{FINAL_DIR}.lock"
            while not (group_dir / FINAL_DIR).exists() and lock.exists() and time.monotonic() < deadline:
                time.sleep(GROUP_POLL_SECONDS)
            if (group_dir / FINAL_DIR).exists():
                files.extend(merged_files(group_dir / FINAL_DIR))
                continue
            logging.info("No merge of tasks %d-%d, merging their files", tasks.start, tasks.stop - 1)
        files.extend(str(path) for task in tasks for path in sorted(task_dir(root, task).glob("*.bdo")))
    return files


def collect(args) -> int:
    """Merges the simulation's results into pages in the output directory; non-zero without any result"""
    try:
        from yaptide.batch import results_merger
    except ImportError:  # on a cluster, next to this script
        import results_merger

    files = final_files(Path(args.root), args.ntasks)
    if not files:
        logging.error("No result files to merge")
        return 1
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    manifest = results_merger.write_directory(files, output)
    if not manifest["estimators"]:
        logging.error("No estimators in %d result files", len(files))
        return 1
    logging.info("Merged %d files into %d estimators", len(files), len(manifest["estimators"]))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """The merges of the scripts on the cluster"""
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("partial", "task_end", "collect"):
        command = commands.add_parser(name)
        command.add_argument("--root", required=True, help="the simulation's directory")
        command.add_argument("--ntasks", type=int, required=True)
    commands.choices["partial"].add_argument("--group", type=int, required=True)
    for name in ("sim_id", "update_key", "backend_url"):
        commands.choices["partial"].add_argument(f"--{name}", required=True)
    commands.choices["task_end"].add_argument("--task", type=int, required=True)
    commands.choices["collect"].add_argument("--output_dir", required=True)
    args = parser.parse_args(argv)
    return {"partial": partial, "task_end": task_end, "collect": collect}[args.command](args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
