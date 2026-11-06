"""Merges of an HPC simulation's results in two tiers on the cluster, for results too large for one merge to be quick.

The tasks are split into groups of consecutive tasks (merge_groups.json in the simulation's directory, written by the
first to need it, from the size of a task's result files): each group's files are merged on their own, and the last
merge takes one merged file per group instead of one file per task. Every merge streams one file at a time
(results_merger.py), so it needs about twice the largest estimator at either tier; the groups save reading time: the
group merges run on different nodes at once, and the last merge reads one task's worth of results per group.
Results whose files fit in GROUP_BYTES altogether are one group: a single merge, as without groups.

- live partial results (points and lines, result_format.partial_mode), while someone looks at the simulation (the
  wanted object in storage, result_format.parse_wanted): a task's watcher starts the partial script for the task's
  group, holding the group's lock (partial.lock.<group>). The group's latest saves are merged into
  groups/<group>/<primaries>/, then the one getting the last lock (partial.lock.final) merges the latest of every
  group and uploads it, with stubs of the maps (their numbers, names and dimensions, no values) so the user can ask
  for one. Only the live pages are read (bdo_pages.py); nothing is uploaded when no save changed since the last.
- maps asked for (on demand): a watcher holding partial.lock.on_demand starts the partial script for the pages the
  wanted object lists, each by its estimator and number: the latest saves of all tasks, those pages only, merged and
  uploaded at once. The backend keeps the other pages as they were, and takes the pages off the list.
- a lock is a directory with its owner; a merge holding one touches it every HEARTBEAT_SECONDS, and a lock left
  untouched for LOCK_SECONDS (its merge was killed: out of memory, its task's time limit, a failed node) is taken
  over, so a failed task holds up the partial results of the others for a minute or two at most.
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

import threading

try:
    from yaptide.batch import result_format
except ImportError:  # on a cluster, next to this script
    import result_format

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
# a merge holding a lock touches it this often; a lock untouched for LOCK_SECONDS was left by a merge that was killed
# (its task ended, it ran out of memory, or its node failed) and is taken over
HEARTBEAT_SECONDS = 15
LOCK_SECONDS = 90
# the last partial merge runs at most this often by default (the watchers pass the live interval of the simulation,
# result_format.live_interval); the watchers start group merges as often (watcher.py)
PARTIAL_SECONDS = result_format.LIVE_MIN_SECONDS
# the lock of the on-demand merge
ON_DEMAND_LOCK = result_format.ON_DEMAND
# a last partial merge that failed is tried again this soon
RETRY_SECONDS = 20
# merged saves kept of each group: the latest, and the one before for a last merge still reading it
KEPT_MERGES = 2
# the collect waits this long for a group's merge still running (the group's last task ended a moment ago)
GROUP_WAIT_SECONDS = 600
GROUP_POLL_SECONDS = 5
# where the partial results are merged into before they are uploaded
PARTIAL_OUTPUT = "partial_output"
# what the last live partial results were merged from (the saves, or the groups' merges): the same is not uploaded again
UPLOADED_FILE = "partial.uploaded"
# the pages the groups merge for partial results: the live ones only, the on-demand ones are merged apart
GROUP_PARTIAL_MODES = result_format.kind_modes(result_format.LIVE)


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


def lock_age(path: Path) -> float:
    """Seconds since the lock was taken or last touched by its merge"""
    stamps = [path.stat().st_mtime]
    try:
        stamps.append((path / OWNER_FILE).stat().st_mtime)
    except FileNotFoundError:
        pass
    return time.time() - max(stamps)


def take_lock(path: Path, max_age: float = LOCK_SECONDS) -> bool:
    """Takes a lock (a directory: making one is atomic on a shared filesystem); one untouched for max_age is taken
    over: renamed aside first, which only one of the merges taking it over at once manages. False when another
    holds it
    """
    try:
        path.mkdir()
        return True
    except FileExistsError:
        pass
    try:
        if lock_age(path) < max_age:
            return False
        stale = path.with_name(f".{path.name}.stale.{uuid.uuid4().hex}")
        path.rename(stale)
        shutil.rmtree(str(stale), ignore_errors=True)
        path.mkdir()
        logging.warning("Took over %s, left by a merge that stopped", path.name)
        return True
    except OSError:
        # another took it meanwhile
        return False


# the locks this process holds, each with the event that stops its heartbeat
_heartbeats: dict = {}


def _heartbeat(owner: Path, stop: threading.Event) -> None:
    """Touches the lock's owner file until stopped: the lock is alive while its merge is"""
    while not stop.wait(HEARTBEAT_SECONDS):
        try:
            owner.touch()
        except OSError:
            pass


def own_lock(path: Path) -> None:
    """Marks the lock as held by this process's group, and keeps it alive while this process runs: the watcher that
    started the merge frees it when it stops the merge, and a merge killed leaves it to go stale
    """
    try:
        (path / OWNER_FILE).write_text(str(os.getpgrp()))
    except OSError:
        return
    if path in _heartbeats:
        return
    stop = threading.Event()
    _heartbeats[path] = stop
    threading.Thread(target=_heartbeat, args=(path / OWNER_FILE, stop), daemon=True).start()


def free_lock(path: Path, owner: Optional[int] = None) -> None:
    """Frees a lock this process holds, or one held by owner's merge (or by no one yet)"""
    stop = _heartbeats.pop(path, None)
    if stop is not None:
        stop.set()
    try:
        held_by = int((path / OWNER_FILE).read_text())
    except FileNotFoundError:
        held_by = None
    except (OSError, ValueError):
        return
    if held_by is None or held_by == (os.getpgrp() if owner is None else owner):
        shutil.rmtree(str(path), ignore_errors=True)


def free_locks(root: Path, owner: int, group, kind: str = result_format.LIVE) -> None:
    """Frees the locks a stopped merge held: the group's it was started for and the last merge's, or the on-demand
    merge's
    """
    names = (ON_DEMAND_LOCK,) if kind == result_format.ON_DEMAND else (group, FINAL_LOCK)
    for name in names:
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


def write_merged(files: List[str], target: Path, modes: Optional[set] = None) -> int:
    """Merges the files into one pickled estimator each in target, whole or not at all (written aside, then renamed);
    the primaries merged. With modes, only the pages of those modes (results_merger.merge_estimator_files)
    """
    try:
        from yaptide.batch import results_merger
    except ImportError:  # on a cluster, next to this script
        import results_merger

    partial = target.parent / f".{target.name}.{uuid.uuid4().hex}"
    partial.mkdir(parents=True)
    primaries = 0
    try:
        for name, estimator in results_merger.merged_estimators(files, modes):
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
            write_merged([file for unit in units for file in unit], target, GROUP_PARTIAL_MODES)
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
    return latest_saves(root, n_tasks)


def units_signature(units: List[List[str]]) -> str:
    """What a merge read: the directories of its units (each named by its primaries, so a new save is another)"""
    return json.dumps(sorted(str(Path(unit[0]).parent) for unit in units if unit))


def live_merge_due(root: Path, group: int, n_tasks: int) -> bool:
    """Whether a live merge of the group would merge anything new: a save of its tasks newer than the group's latest
    merge, or units of the last tier other than the last uploaded. Checked by the watchers before they start the
    partial script, so that a merge with nothing new does not start a Python process on the task's core
    """
    size = read_plan(root)
    if size is None:
        return True
    if size < n_tasks:
        saves = [latest_save(task_dir(root, task)) for task in group_tasks(group, size, n_tasks)]
        saves = [save for save in saves if save is not None]
        if saves and not (root / GROUPS_DIR / str(group) / str(sum(int(save.name) for save in saves))).exists():
            return True
    units = [unit for unit in partial_units(root, size, n_tasks) if unit]
    # no saves found where the plan says (another layout): the script decides
    return not units or read_text(root / f"{UPLOADED_FILE}.{result_format.LIVE}") != units_signature(units)


def merge_and_upload(
    root: Path,
    units: List[List[str]],
    args,
    kind: str = result_format.LIVE,
    pages: Optional[dict] = None,
) -> int:
    """Merges the units' files into partial results and uploads them (results_uploader.py, beside this script): the
    live pages with stubs of the maps, or (kind ON_DEMAND) the pages asked for (estimator -> page numbers); a unit with
    a file that cannot be read whole is left out. Live results merged from the same units as the last ones uploaded
    are not merged again
    """
    try:
        from yaptide.batch import results_merger
    except ImportError:  # on a cluster, next to this script
        import results_merger

    units = [unit for unit in units if unit]
    live = kind == result_format.LIVE
    modes = result_format.kind_modes(kind) if live else None
    uploaded = root / f"{UPLOADED_FILE}.{kind}"
    # the two kinds run at once, each into its own directory
    output = root / f"{PARTIAL_OUTPUT}.{kind}"
    try:
        while True:
            if not units:
                return 0
            if live and read_text(uploaded) == units_signature(units):
                logging.info("No new saves since the last partial results")
                return 0
            shutil.rmtree(str(output), ignore_errors=True)
            output.mkdir()
            files = [file for unit in units for file in unit]
            # the maps there are, from a save (a group's merges hold the live pages only)
            stubs = results_merger.page_stubs(stub_files(root, units, args), {result_format.ON_DEMAND}) if live else None
            try:
                manifest = results_merger.write_directory(files, output, modes=modes, pages=pages, stubs=stubs)
                break
            except ValueError as err:
                index = unreadable(err, units)
                if index is None:
                    raise
                logging.warning("Left out %s from the partial results: %s", Path(units[index][0]).parent, err)
                del units[index]
        if not manifest["estimators"]:
            # nothing of the kind (no maps, say): nothing to upload, and nothing to retry
            logging.info("No %s pages in %d files", kind, len(files))
            return 0
        logging.info("Merged %d files into %s partial results of %d primaries", len(files), kind, manifest["primaries"])
        uploader = Path(__file__).resolve().parent / "results_uploader.py"
        command = [sys.executable, str(uploader), "--partial", f"--output_dir={output}", "--attempts=3"]
        command += [f"--sim_id={args.sim_id}", f"--update_key={args.update_key}", f"--backend_url={args.backend_url}"]
        code = subprocess.run(command, check=False).returncode
        if live and code == 0:
            uploaded.write_text(units_signature(units))
        return code
    finally:
        shutil.rmtree(str(output), ignore_errors=True)


def read_text(path: Path) -> Optional[str]:
    """A small file's text, None when it is missing"""
    try:
        return path.read_text()
    except OSError:
        return None


def latest_saves(root: Path, n_tasks: int) -> List[List[str]]:
    """The result files of the latest save of every task that has one"""
    saves = (latest_save(task_dir(root, task)) for task in range(1, n_tasks + 1))
    return [[str(path) for path in sorted(save.glob("*.bdo"))] for save in saves if save is not None]


def stub_files(root: Path, units: List[List[str]], args) -> List[str]:
    """Result files to read the maps there are from: a task's save among the units, else the first task's save"""
    files = [file for file in units[0] if file.endswith(".bdo")] if units else []
    return files or first_save(root, getattr(args, "ntasks", 0) or 0)


def first_save(root: Path, n_tasks: int) -> List[str]:
    """The result files of a task's latest save, the first found"""
    for task in range(1, n_tasks + 1):
        save = latest_save(task_dir(root, task))
        if save is not None:
            return [str(path) for path in sorted(save.glob("*.bdo"))]
    return []


def partial_on_demand(args) -> int:
    """The pages the user asked for (--pages, result_format.pages_argument), started by a watcher holding the
    on-demand lock: those pages of the latest saves of all tasks, merged and uploaded at once (no other page is read).
    The on-demand stamp is touched when it ends, so the watchers that still see the request before the backend took
    it off do not merge the pages again at once
    """
    root = Path(args.root)
    lock = lock_path(root, ON_DEMAND_LOCK)
    own_lock(lock)
    try:
        pages = result_format.parse_pages_argument(getattr(args, "pages", None))
        if not pages:
            return 0
        return merge_and_upload(root, latest_saves(root, args.ntasks), args, result_format.ON_DEMAND, pages)
    finally:
        (root / f"{PARTIAL_STAMP}.{ON_DEMAND_LOCK}").touch()
        free_lock(lock)


def partial(args) -> int:
    """Partial results, started by a task's watcher holding the lock of its group: the group's latest saves merged
    (their live pages), then, by the one getting the last lock, the latest of every group merged and uploaded. One
    group: its saves are the whole simulation's, merged and uploaded at once. With --kind on_demand, the maps
    (partial_on_demand)
    """
    if getattr(args, "kind", result_format.LIVE) == result_format.ON_DEMAND:
        return partial_on_demand(args)
    root = Path(args.root)
    interval = getattr(args, "interval", None) or PARTIAL_SECONDS
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
    if not stamp_due(stamp, interval) or not take_lock(final_lock):
        return 0
    own_lock(final_lock)
    code = 1
    try:
        code = merge_and_upload(root, partial_units(root, size, n_tasks), args)
        return code
    finally:
        free_lock(final_lock)
        if code:
            retry_soon(stamp, interval)


def retry_soon(stamp: Path, interval: float = PARTIAL_SECONDS) -> None:
    """A last partial merge that failed is tried again by a group merge RETRY_SECONDS later, not an interval later"""
    try:
        when = time.time() - interval + min(RETRY_SECONDS, interval)
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
    own_lock(lock)
    try:
        files = [str(path) for task in tasks for path in sorted(task_dir(root, task).glob("*.bdo"))]
        write_merged(files, group_dir / FINAL_DIR)
    finally:
        free_lock(lock)
    logging.info("Merged the results of tasks %d-%d", tasks.start, tasks.stop - 1)
    return 0


def lock_alive(path: Path) -> bool:
    """Whether a lock is held by a merge still running (touched within LOCK_SECONDS)"""
    try:
        return lock_age(path) < LOCK_SECONDS
    except FileNotFoundError:
        return False


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
            # a merge killed meanwhile leaves its lock untouched: not waited for
            while not (group_dir / FINAL_DIR).exists() and lock_alive(lock) and time.monotonic() < deadline:
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
    commands.choices["partial"].add_argument("--group", type=int, default=0)
    commands.choices["partial"].add_argument("--kind", choices=result_format.PARTIAL_KINDS, default=result_format.LIVE)
    commands.choices["partial"].add_argument("--interval", type=float, help="seconds between the last partial merges")
    commands.choices["partial"].add_argument("--pages", help="the pages asked for (on_demand): JSON [[estimator, n]]")
    for name in ("sim_id", "update_key", "backend_url"):
        commands.choices["partial"].add_argument(f"--{name}", required=True)
    commands.choices["task_end"].add_argument("--task", type=int, required=True)
    commands.choices["collect"].add_argument("--output_dir", required=True)
    args = parser.parse_args(argv)
    return {"partial": partial, "task_end": task_end, "collect": collect}[args.command](args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
