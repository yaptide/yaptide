"""Long-lived engine running direct simulations on the Ray cluster it is started on.

Flask only stores simulations in the database. The engine starts the pending ones, runs their tasks on Ray,
writes their progress and results to the database itself and stops the ones cancelled there.

It acts on events, handled one at a time from one queue: Postgres sends one when a direct simulation is stored,
cancelled or deleted (the trigger in yaptide/persistence/models.py), Ray when a task or merge finishes.
A sweep through the database catches what came while the engine was not listening: at start, after it lost
the connection to the database and after a failed event.
"""

import json
import logging
import math
import os
import queue
import re
import shutil
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import ray
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import and_, func, or_, text

from yaptide.batch.batch_methods import SUBMIT_SECONDS, cancel_simulation, fail_submit, submit_simulation
from yaptide.engine.pymc import get_tmp_dir
from yaptide.engine.simulation import (
    WORK_DIR_PREFIX,
    backend_app,
    merge_and_store,
    merge_and_store_partial,
    run_simulation,
)
from yaptide.persistence import result_storage
from yaptide.persistence.database import db, listen_to
from yaptide.persistence.db_methods import (
    DATABASE_FAILURES,
    add_object_to_db,
    bulk_update_task_states,
    update_reported_tasks,
    update_simulation_state,
)
from yaptide.persistence.models import (
    ENGINE_CHANNEL,
    BatchSimulationModel,
    CelerySimulationModel,
    ClusterModel,
    LogfilesModel,
    SimulationModel,
    TaskModel,
    UserActivityModel,
)
from yaptide.routes.utils.utils import FINAL_STATES, update_state_from_tasks
from yaptide.utils.enums import EntityState, PlatformType, SimulationType
from yaptide.utils.sim_utils import set_shieldhit_save_step

# SSH connections to the clusters at once; they ban accounts that log in often
CLUSTER_CONNECTIONS = 4
# how often the progress HPC tasks put into storage is read
HPC_PROGRESS_SECONDS = 10
# how long after an HPC simulation ended its tasks' reports are still read
ENDED_READ_SECONDS = 600
# processes reading the reports of a round, each the reports of some of the simulations: one reads about 5000 a
# second on an M4 (its CPU, under the GIL), two as many as Garage serves; more only burn Garage's CPU
HPC_READERS = 2
# a user follows their simulations this long after a status stream of theirs or a status they asked for wrote it down
# (db_methods.note_watching: at most every 30 s, while an open stream wakes at least every 25 s)
WATCHED_SECONDS = 120
# the progress of the HPC simulations of the other users is read this rarely, to spare the storage reads
UNWATCHED_PROGRESS_SECONDS = int(os.environ.get("HPC_UNWATCHED_PROGRESS_SECONDS", 300))
# what a task's report may set
REPORTED_STATES = {
    EntityState.RUNNING.value,
    EntityState.COMPLETED.value,
    EntityState.FAILED.value,
    EntityState.CANCELED.value,
}
REPORTED_NUMBERS = ("simulated_primaries", "requested_primaries", "estimated_time")
REPORTED_TIMES = ("start_time", "end_time")
MAX_REPORTED_NUMBER = 2**31 - 1


def clean_report(update: dict) -> dict:
    """The fields of a task's report that may go into the database, as written by the jobs (yaptide/batch/watcher.py)

    Reports come from the cluster, so states, numbers and times are checked; anything else is left out.
    """
    clean = {}
    if update.get("task_state") in REPORTED_STATES:
        clean["task_state"] = update["task_state"]
    for name in REPORTED_NUMBERS:
        value = update.get(name)
        if type(value) is int and 0 <= value <= MAX_REPORTED_NUMBER:
            clean[name] = value
    for name in REPORTED_TIMES:
        value = update.get(name)
        if isinstance(value, str):
            try:
                datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                continue
            clean[name] = value
    return clean


def read_report(simulation_id: int, key: str) -> Optional[dict]:
    """A task's report as a task update: the task comes from the object's name, only valid fields count

    A report that cannot be used gives None; storage out of reach is raised and ends the round.
    """
    match = re.fullmatch(result_storage.progress_prefix(simulation_id) + r"task_(\d{1,6})\.json", key)
    if not match:
        return None
    try:
        report = result_storage.read_report(key)
        if not isinstance(report, dict) or not isinstance(report.get("update"), dict):
            raise ValueError("not a report")
        update = {"task_id": int(match.group(1)), "update_dict": clean_report(report["update"])}
    except (BotoCoreError, ClientError, OSError):
        raise
    # anything the job wrote, also JSON too deep to parse (RecursionError)
    except Exception:  # skipcq: PYL-W0703
        logging.warning("Unreadable progress report %s", key)
        return None
    return update if update["update_dict"] else None


def read_reports(etags: dict[int, dict[str, str]]) -> dict[int, dict[str, str]]:
    """Saves what the tasks of HPC simulations (simulation id -> ETags of the reports as last read) put into storage
    since; for each simulation its reports (key -> ETag)

    Many reports are read at once, and a simulation's updates are saved while the next ones are read: one statement
    for its tasks and one event for its streams. A report that cannot be used is skipped (and not read again until
    it changes), a simulation whose progress is refused too; storage or database out of reach raises.
    """
    # one listing at a time and none while reports are read: Garage otherwise burns several times the CPU (SQLite
    # or LMDB metadata alike) and serves no faster
    listings = {simulation_id: result_storage.progress_reports(simulation_id) for simulation_id in etags}
    pool = ThreadPoolExecutor(result_storage.REPORT_CONNECTIONS)
    # reads not started yet are dropped when one fails: the round ends at once, also with storage out of reach
    try:
        reads = {
            simulation_id: [
                pool.submit(read_report, simulation_id, key)
                for key, etag in listings[simulation_id].items()
                if last.get(key) != etag
            ]
            for simulation_id, last in etags.items()
        }
        for simulation_id, futures in reads.items():
            save_reports(simulation_id, [update for update in (future.result() for future in futures) if update])
    finally:
        pool.shutdown(cancel_futures=True)
    return listings


def save_reports(simulation_id: int, updates: list[dict]) -> None:
    """Saves the checked updates of a simulation's tasks and moves the simulation's state when a task's state
    changed, in one transaction; progress the database refuses is left out, the database out of reach raises
    """
    if not updates:
        return
    try:
        update_reported_tasks(simulation_id, updates)
        simulation = db.session.get(SimulationModel, simulation_id)
        if simulation:
            update_state_from_tasks(simulation, any("task_state" in update["update_dict"] for update in updates))
        db.session.commit()
    except DATABASE_FAILURES:
        raise
    except Exception:  # skipcq: PYL-W0703
        db.session.rollback()
        logging.exception("Progress of simulation %d refused", simulation_id)


HPC_ACTIVE_STATES = (
    EntityState.PENDING.value,
    EntityState.RUNNING.value,
    EntityState.MERGING_QUEUED.value,
    EntityState.MERGING_RUNNING.value,
)
# progress is saved in batches, not for every line the simulators log
PROGRESS_SECONDS = 1
# a new task state saves the progress at once, but not more often than this: many short tasks change states often,
# and every save notifies the users' status streams
NEW_STATE_SAVE_SECONDS = 0.5
# a task running longer is stopped, as the Celery workers did; checked once a minute
TASK_SECONDS_LIMIT = 10 * 3600
OVERDUE_CHECK_SECONDS = 60
# a cancel that did not reach the cluster is repeated (looked for with the overdue tasks), at most this often for
# each simulation: logins count against the user's account; one whose certificate expired is not repeated
# (cancel_simulation then forgets the job directory)
CANCEL_RETRY_SECONDS = 10 * 60
# the engine gives up and restarts with its container after failing for this long
GIVE_UP_SECONDS = 60
# partial results are merged again once the saves of the tasks cover this much more of the requested primaries
PARTIAL_GROWTH = 0.05
# partial merges at once over all simulations, next to the simulators (an HPC simulation's are merged on its cluster)
MAX_PARTIAL_MERGES = 2
# besides the delete events, the engine looks this often for objects under hpc/ and work/ of simulations no longer in
# the database: deletes made while it was not listening, removals that failed (their pages stay: storage cost only)
ORPHAN_SWEEP_SECONDS = 3600
RUNNING_STATES = (EntityState.RUNNING.value, EntityState.MERGING_QUEUED.value, EntityState.MERGING_RUNNING.value)
# a cluster whose SLURM did not answer this many submits and cancels in a row gets none for a while (longer each time
# it still does not answer), then one to try it; its simulations wait PENDING meanwhile
BREAKER_FAILURES = int(os.environ.get("CLUSTER_BREAKER_FAILURES", "3"))
BREAKER_SECONDS = [int(seconds) for seconds in os.environ.get("CLUSTER_BREAKER_SECONDS", "180,300,600").split(",")]
# another call tries the cluster if the answer to the one trying it never comes (the simulation was deleted meanwhile)
TRIAL_SECONDS = 2 * SUBMIT_SECONDS
# a simulation not submitted this long after it was sent (its cluster did not answer) fails, the user tries later
CLUSTER_WAIT_HOURS = float(os.environ.get("CLUSTER_WAIT_HOURS", "24"))


# restarted when it dies: only progress not saved yet is lost, final states come with the task results;
# state_changed waits in a thread of its own, the other calls run one at a time in the order each task made them
# (an async actor would run a task's reports out of order, an older update over a newer one)
@ray.remote(num_cpus=0, max_restarts=-1, max_task_retries=-1, concurrency_groups={"wait": 1})
class ProgressInbox:
    """Keeps the latest progress and the latest save of every task until the engine takes them"""

    def __init__(self):
        """Empty inbox"""
        self.updates: dict[tuple[int, int], dict] = {}
        self.saves: dict[tuple[int, int], tuple[str, int]] = {}
        self.new_state = threading.Event()

    def report(self, simulation_id: int, task_id: int, update_dict: dict) -> None:
        """Merges a task's update into the one waiting to be saved"""
        self.updates.setdefault((simulation_id, task_id), {}).update(update_dict)
        if "task_state" in update_dict:
            self.new_state.set()

    def saved(self, simulation_id: int, task_id: int, key: str, primaries: int) -> None:
        """Replaces a task's save waiting to be taken"""
        self.saves[(simulation_id, task_id)] = (key, primaries)

    def drain(self) -> tuple[dict[tuple[int, int], dict], dict[tuple[int, int], tuple[str, int]]]:
        """Hands over the waiting updates and saves"""
        self.new_state.clear()
        updates, saves, self.updates, self.saves = self.updates, self.saves, {}, {}
        return updates, saves

    @ray.method(concurrency_group="wait")
    def state_changed(self) -> None:
        """Returns once a waiting update changes a task's state, e.g. to RUNNING"""
        self.new_state.wait()


@ray.remote(num_cpus=1, max_retries=0)
def run_task(inbox, files_dict: dict, sim_type: str, simulation_id: int, task_id: int, work_dir: str) -> dict:
    """One simulation task; its progress goes to the inbox"""

    def report(update_dict: dict) -> None:
        """Hands a progress update to the inbox"""
        inbox.report.remote(simulation_id, task_id, update_dict)

    def saved(key: str, primaries: int) -> None:
        """Hands a save of the results to the inbox"""
        inbox.saved.remote(simulation_id, task_id, key, primaries)

    return run_simulation(files_dict, task_id, sim_type, Path(work_dir), simulation_id, report, saved)


# a merge killed for memory must not be retried forever, which Ray does unless retries are off;
# it takes no CPU slot, so a finished simulation does not wait behind the tasks of others (merges are short and rare)
@ray.remote(num_cpus=0, max_retries=0)
def merge_task(simulation_id: int, keys: list[str]) -> bool:
    """Merges and stores the results of a simulation"""
    return merge_and_store(simulation_id, keys)


# like the merge; one that fails is skipped, the next saves bring the next partial results
@ray.remote(num_cpus=0, max_retries=0)
def partial_merge_task(simulation_id: int, keys: list[str], primaries: int, max_bytes: float = float("inf")) -> bool:
    """Merges the latest saves of the tasks of a running simulation, at most max_bytes of result files, and stores
    them as its partial results
    """
    return merge_and_store_partial(simulation_id, keys, primaries, max_bytes)


# a task cancelled meanwhile may still store its save, and removes it itself
@ray.remote(num_cpus=0)
def delete_task_results(simulation_id: int) -> None:
    """Removes what the tasks of a simulation stored for the merges"""
    result_storage.delete_objects(result_storage.work_prefix(simulation_id))


def deleted_for_good(simulation_id: int) -> bool:
    """Whether the simulation is gone from the database and no new simulation can get its id: a database restored
    from an older backup hands out again the ids of the simulations made after that backup, and the new simulations
    store their pages under the same keys. Any doubt (no sequence, a failed query) keeps the objects.
    """
    if db.session.query(SimulationModel.id).filter_by(id=simulation_id).first():
        return False
    if db.engine.dialect.name == "postgresql":
        # the id last handed out, NULL before the first; later ones are higher
        last = db.session.execute(
            text("""SELECT pg_sequence_last_value(pg_get_serial_sequence('"Simulation"', 'id')::regclass)""")
        ).scalar()
    else:
        # SQLite gives the highest id + 1
        last = db.session.query(func.max(SimulationModel.id)).scalar()
    return last is not None and simulation_id <= last


# one removal at a time: a large simulation has tens of thousands of objects, removing many at once would swamp the
# storage. A call lost with the actor (a restart, the engine's) loses nothing: what is under hpc/ and work/ the engine's
# next look for orphans removes, the pages stay as orphans - only a delete event removes pages, never a guess
@ray.remote(num_cpus=0, max_restarts=-1)
class StorageCleaner:
    """Removes the stored objects of deleted simulations, so the user's delete does not wait for them"""

    @staticmethod
    def delete(simulation_id: int, pages: bool) -> None:
        """Removes the objects of a deleted simulation, its result pages too when pages is set; checks the database
        again first, the call may have waited long behind others
        """
        with backend_app().app_context():
            try:
                if not deleted_for_good(simulation_id):
                    logging.warning("Simulation %d is in the database or its id may come again, kept", simulation_id)
                    return
            finally:
                db.session.remove()
        result_storage.delete_simulation(simulation_id, pages)


@ray.remote(num_cpus=0, max_concurrency=CLUSTER_CONNECTIONS, max_restarts=-1)
class ClusterGateway:
    """Submits and cancels HPC simulations over SSH with the users' certificates, a few connections at a time"""

    @staticmethod
    def submit(simulation_id: int) -> Optional[bool]:
        """Submits a stored HPC simulation; it ends FAILED itself when it cannot be submitted. Returns whether the
        cluster's SLURM answered, None when it was not asked.
        """
        with backend_app().app_context():
            try:
                return submit_simulation(simulation_id)
            finally:
                db.session.remove()

    @staticmethod
    def cancel(simulation_id: int) -> Optional[bool]:
        """Cancels the jobs of a cancelled HPC simulation on its cluster; returns whether the cluster's SLURM
        answered, None when it was not asked
        """
        with backend_app().app_context():
            try:
                return cancel_simulation(simulation_id)
            finally:
                db.session.remove()


# a process of its own, so the reports of a round are read on several cores; no CPU slot, like the merges
@ray.remote(num_cpus=0, max_restarts=-1)
class HpcReader:
    """Reads and saves the progress HPC tasks put into storage, for some of the simulations of a round"""

    @staticmethod
    def read(etags: dict[int, dict[str, str]]) -> dict[int, dict[str, str]]:
        """read_reports with a database session of its own"""
        with backend_app().app_context():
            try:
                return read_reports(etags)
            finally:
                db.session.remove()


@dataclass
class Breaker:
    """Whether the engine calls a cluster (a circuit breaker): closed, every submit and cancel goes; open after
    BREAKER_FAILURES calls in a row met a SLURM that did not answer, none goes until the cool-down ends; then one goes
    to try it (half-open), and its answer closes the breaker or opens it for longer
    """

    failures: int = 0
    # times opened in a row, which picks the cool-down
    opened: int = 0
    # time.monotonic() when the cool-down or the trial ends, 0 while closed
    until: float = 0.0
    # the call trying the cluster: ("submit" or "cancel", simulation id)
    trial: Optional[tuple[str, int]] = None

    def allows(self, call: tuple[str, int]) -> bool:
        """Whether the call may go to the cluster now"""
        if not self.until:
            return True
        if time.monotonic() < self.until:
            return False
        self.trial, self.until = call, time.monotonic() + TRIAL_SECONDS
        return True

    def record(self, call: tuple[str, int], answered: Optional[bool]) -> Optional[bool]:
        """Counts the answer of a call: whether SLURM answered, None when the call did not ask it; returns True when
        this closed the breaker, False when it opened it
        """
        if answered:
            closed = bool(self.until)
            self.failures, self.opened, self.until, self.trial = 0, 0, 0.0, None
            return True if closed else None
        if self.until and call != self.trial:
            # sent before the breaker opened: the cool-down already counts it
            return None
        if answered is None:
            if call == self.trial:
                # nothing learnt, another call tries
                self.until = time.monotonic()
            return None
        self.failures += 1
        if self.failures < BREAKER_FAILURES:
            return None
        self.until = time.monotonic() + BREAKER_SECONDS[min(self.opened, len(BREAKER_SECONDS) - 1)]
        self.opened += 1
        self.trial = None
        return False


@dataclass
class Running:
    """A simulation the engine runs: its tasks still running, then its merge"""

    tasks: dict  # task ref -> task id
    work_dirs: dict[int, Path]
    requested_primaries: int = 0
    result_keys: list[str] = field(default_factory=list)
    logfiles: dict = field(default_factory=dict)
    merge: Optional[ray.ObjectRef] = None
    # the latest results of every task, saved while running or final: task id -> (key in storage, primaries)
    saves: dict[int, tuple[str, int]] = field(default_factory=dict)
    partial: Optional[ray.ObjectRef] = None
    # primaries of the stored partial results, and of the ones being merged
    partial_primaries: int = 0
    merging_primaries: int = 0

    def refs(self) -> list:
        """What the engine waits for"""
        return [*self.tasks, self.merge] if self.merge else list(self.tasks)


def now() -> str:
    """Current time as the task and simulation updates carry it"""
    return datetime.utcnow().isoformat(sep=" ")


class Engine:
    """Runs the direct simulations stored in the database, one event at a time"""

    def __init__(self):
        """Engine with nothing running yet"""
        self.inbox = ProgressInbox.remote()
        self.cluster = ClusterGateway.remote()
        self.cleaner = StorageCleaner.remote()
        # deleted simulations whose objects the cleaner removes: (simulation id, with pages) -> the removal's ref
        self.removing: dict[tuple[int, bool], ray.ObjectRef] = {}
        # started with the first round: processes of their own
        self.hpc_readers: list = []
        # ETags of the progress reports HPC tasks put into storage, as last read: simulation id -> key -> ETag
        self.report_etags: dict[int, dict[str, str]] = {}
        # the round reading them: the ref of each reader
        self.hpc_reading: list[ray.ObjectRef] = []
        # the simulations of the round (id, state, whether their user follows them) and when it started
        self.hpc_round: list[tuple[int, str, bool]] = []
        self.hpc_round_started = 0.0
        # when the reports of each simulation were last read (time.monotonic(), when that round started)
        self.hpc_read_at: dict[int, float] = {}
        # whether HPC simulations may have reports to read: at start, after a submit, until a read finds none
        self.hpc_active = True
        # HPC simulations being submitted and cancelled on their cluster: simulation id -> the call's ref
        self.submitting: dict[int, ray.ObjectRef] = {}
        self.cancelling: dict[int, ray.ObjectRef] = {}
        # whether the SLURM of each cluster answers (cluster id -> its breaker), and the cluster of each call on its way
        self.breakers: dict[int, Breaker] = defaultdict(Breaker)
        self.calling: dict[tuple[str, int], int] = {}
        # when the jobs of a simulation were last cancelled on its cluster (time.monotonic())
        self.cancel_tried: dict[int, float] = {}
        self.running: dict[int, Running] = {}
        self.progress_saved = 0.0
        # (event, simulation id, platform): PENDING, CANCELED, DELETED from Postgres, FINISHED and SUBMITTED
        # from Ray, SWEEP
        self.events: queue.Queue = queue.Queue()

    def run(self, listener: Optional[threading.Thread] = None) -> None:  # skipcq: PY-R1000
        """Handles events as they come, saves progress every second while simulations run and at once when a task
        changes its state, until failing for a minute

        A listener thread that died would leave the engine without events, so the engine stops with it.
        """
        self.recover()
        self.watch_inbox()
        self.events.put(("SWEEP", None))
        last_progress = last_overdue_check = last_hpc_progress = time.monotonic()
        last_orphan_sweep = float("-inf")
        failing_since = None
        while True:
            try:
                event = self.events.get(timeout=PROGRESS_SECONDS)
            except queue.Empty:
                event = None
            try:
                if event:
                    self.handle(*event)
                if time.monotonic() - last_progress >= PROGRESS_SECONDS:
                    last_progress = time.monotonic()
                    if listener and not listener.is_alive():
                        raise SystemExit("the thread listening for database events died")
                    # what tasks of stopped simulations report is dropped anyway, so it can wait in the inbox
                    if self.running:
                        self.save_progress()
                # a round starts after the last one ended
                if (
                    self.hpc_active
                    and not self.hpc_reading
                    and time.monotonic() - last_hpc_progress >= HPC_PROGRESS_SECONDS
                ):
                    last_hpc_progress = time.monotonic()
                    self.read_hpc_progress()
                if time.monotonic() - last_overdue_check >= OVERDUE_CHECK_SECONDS:
                    last_overdue_check = time.monotonic()
                    self.stop_overdue()
                    self.retry_cancels()
                    self.submit_waiting()
                if time.monotonic() - last_orphan_sweep >= ORPHAN_SWEEP_SECONDS:
                    last_orphan_sweep = time.monotonic()
                    self.delete_orphans()
                failing_since = None
            except Exception:  # skipcq: PYL-W0703
                logging.exception("Handling %s failed", event)
                failing_since = failing_since or time.monotonic()
                if time.monotonic() - failing_since > GIVE_UP_SECONDS:
                    raise
                # what the failed step missed, e.g. while the database is down, is caught by a sweep
                time.sleep(1)
                self.events.put(("SWEEP", None))
            finally:
                db.session.remove()

    def handle(  # skipcq: PY-R1000
        self, event: str, simulation_id: Optional[int], platform: Optional[str] = None
    ) -> None:
        """Acts on one event"""
        if platform == PlatformType.BATCH.value:
            self.handle_batch(event, simulation_id)
        elif event == "SWEEP":
            self.sweep()
        elif event == "SUBMITTED":
            self.submitted(simulation_id)
        elif event == "HPC_PROGRESS":
            self.hpc_progress_read()
        elif event == "NEW_STATE":
            # watched again after the drain, which resets the notice; also when the save fails
            try:
                # otherwise the next round of progress saves it, within a second
                if time.monotonic() - self.progress_saved >= NEW_STATE_SAVE_SECONDS:
                    self.save_progress()
            finally:
                self.watch_inbox()
        elif event == "CANCELLED_ON_CLUSTER":
            self.cancelled_on_cluster(simulation_id)
        elif event == EntityState.PENDING.value:
            simulation = db.session.get(CelerySimulationModel, simulation_id)
            if simulation and simulation.job_state == EntityState.PENDING.value and simulation_id not in self.running:
                self.start_guarded(simulation)
        elif event in (EntityState.CANCELED.value, "DELETED"):
            self.stop(simulation_id)
        elif event == "PARTIAL" and simulation_id in self.running:
            self.partial_merged(simulation_id, self.running[simulation_id])
        elif event == "FINISHED" and simulation_id in self.running:
            running = self.running[simulation_id]
            ready, _ = ray.wait(running.refs(), num_returns=len(running.refs()), timeout=0)
            self.collect_guarded(simulation_id, running, set(ready))
        # after its tasks were stopped above
        if event == "DELETED" and result_storage.configured():
            self.delete_stored({simulation_id}, pages=True)

    def delete_stored(self, simulation_ids: set[int], pages: bool) -> None:
        """Has the cleaner remove the objects of the simulations not in the database, their result pages too when
        pages is set (a delete event, never a guess), each simulation once at a time; reports the removals that ended
        with an error
        """
        for removal, ref in list(self.removing.items()):
            if ray.wait([ref], timeout=0)[0]:
                del self.removing[removal]
                try:
                    ray.get(ref)
                except Exception:  # skipcq: PYL-W0703
                    logging.exception("Removing the objects of deleted simulation %d failed", removal[0])
        wanted = {simulation_id for simulation_id in simulation_ids if (simulation_id, pages) not in self.removing}
        existing = db.session.query(SimulationModel.id).filter(SimulationModel.id.in_(wanted))
        for simulation_id in sorted(wanted - {simulation_id for (simulation_id,) in existing}):
            self.removing[(simulation_id, pages)] = self.cleaner.delete.remote(simulation_id, pages)

    def delete_orphans(self) -> None:
        """Removes what HPC jobs and tasks left in storage (never result pages) of simulations no longer in the
        database, which their delete events missed

        Only of ids below the newest simulation's: an engine given an empty database, or one restored from an older
        backup, must not empty the storage (the cleaner checks again).
        """
        if not result_storage.configured():
            return
        try:
            stored = result_storage.stored_simulations()
        except Exception:  # skipcq: PYL-W0703
            logging.exception("Looking for objects of deleted simulations failed, trying again later")
            return
        newest = db.session.query(func.max(SimulationModel.id)).scalar() or 0
        self.delete_stored({simulation_id for simulation_id in stored if simulation_id < newest}, pages=False)

    def handle_batch(self, event: str, simulation_id: int) -> None:
        """HPC simulations: the engine submits the stored ones and cancels the cancelled ones on their cluster"""
        if event == EntityState.PENDING.value:
            self.submit(simulation_id)
        elif event == EntityState.CANCELED.value:
            self.cancel(simulation_id)

    def cancel(self, simulation_id: int) -> None:
        """Cancels an HPC simulation: its tasks find the cancel in storage, and while the user's certificate lasts
        the cluster gateway also cancels the jobs at once (and removes the job directory) - later, when the cluster's
        SLURM answers again, if it does not now
        """
        try:
            if result_storage.configured():
                result_storage.put_cancel(simulation_id)
        except Exception:  # skipcq: PYL-W0703
            # put again by the cancel repeated within minutes, as long as the job directory is recorded
            logging.exception("Putting the cancel of simulation %d into storage failed", simulation_id)
        tried = self.cancel_tried.get(simulation_id)
        if simulation_id in self.cancelling or (tried is not None and time.monotonic() - tried < CANCEL_RETRY_SECONDS):
            return
        if not self.may_call("cancel", simulation_id):
            return
        self.cancel_tried[simulation_id] = time.monotonic()
        self.cancelling[simulation_id] = self.cluster.cancel.remote(simulation_id)
        self.watch(self.cancelling[simulation_id], simulation_id, "CANCELLED_ON_CLUSTER")

    def cancelled_on_cluster(self, simulation_id: int) -> None:
        """A cancel on the cluster ended: done, or repeated within minutes (retry_cancels), or once the cluster's SLURM
        answers if it did not - the job directory stays in the database until it is done
        """
        ref = self.cancelling.pop(simulation_id, None)
        try:
            answered = ray.get(ref) if ref else None
        except Exception:  # skipcq: PYL-W0703
            logging.exception("Cancelling simulation %d on its cluster crashed", simulation_id)
            answered = None
        if answered is False:
            # paced by the cluster's breaker instead: it goes again as soon as SLURM answers
            self.cancel_tried.pop(simulation_id, None)
        self.answered(("cancel", simulation_id), answered)

    def may_call(self, kind: str, simulation_id: int) -> bool:
        """Whether a submit or cancel of the simulation may go to its cluster now: not while the cluster's SLURM does
        not answer (its breaker is open); remembers the cluster of the call
        """
        cluster_id = db.session.query(BatchSimulationModel.cluster_id).filter_by(id=simulation_id).scalar()
        if cluster_id is None or not self.breakers[cluster_id].allows((kind, simulation_id)):
            return False
        self.calling[(kind, simulation_id)] = cluster_id
        return True

    def answered(self, call: tuple[str, int], answered: Optional[bool]) -> None:
        """Counts whether the cluster's SLURM answered a call. When the cluster's breaker opens, the users see when it
        is tried again; when it closes, what waited for it goes at once.
        """
        cluster_id = self.calling.pop(call, None)
        if cluster_id is None:
            return
        breaker = self.breakers[cluster_id]
        closed = breaker.record(call, answered)
        if closed is None:
            return
        if closed:
            logging.info("SLURM of cluster %d answers again", cluster_id)
            self.show_busy(cluster_id, None)
            self.submit_waiting()
            self.retry_cancels()
        else:
            seconds = breaker.until - time.monotonic()
            logging.warning(
                "SLURM of cluster %d did not answer %d calls in a row, its submits and cancels wait %d s",
                cluster_id,
                breaker.failures,
                seconds,
            )
            self.show_busy(cluster_id, datetime.now(timezone.utc) + timedelta(seconds=seconds))

    @staticmethod
    def show_busy(cluster_id: int, until: Optional[datetime]) -> None:
        """Stores when the cluster is tried again (None: it answers) and wakes the status streams of the simulations
        waiting for it
        """
        db.session.query(ClusterModel).filter(ClusterModel.id == cluster_id).update(
            {ClusterModel.busy_until: until}, synchronize_session=False
        )
        batch = BatchSimulationModel.__table__
        waiting = db.select(batch.c.id).where(batch.c.cluster_id == cluster_id, batch.c.array_id.is_(None))
        db.session.query(SimulationModel).filter(
            SimulationModel.id.in_(waiting), SimulationModel.job_state == EntityState.PENDING.value
        ).update({SimulationModel.progress_revision: SimulationModel.progress_revision + 1}, synchronize_session=False)
        db.session.commit()

    @staticmethod
    def cancels_left() -> set[int]:
        """HPC simulations with jobs still to cancel on the cluster: the job directory is still recorded - cancelled
        ones, and failed submits (no array id: a simulation that ran keeps its directory)
        """
        failed_submit = and_(
            BatchSimulationModel.job_state == EntityState.FAILED.value, BatchSimulationModel.array_id.is_(None)
        )
        query = db.session.query(BatchSimulationModel.id).filter(
            BatchSimulationModel.job_dir.isnot(None),
            or_(BatchSimulationModel.job_state == EntityState.CANCELED.value, failed_submit),
        )
        return {simulation_id for (simulation_id,) in query}

    def retry_cancels(self) -> None:
        """Repeats the cancels whose event was lost, or that could not reach the cluster"""
        to_cancel = self.cancels_left()
        # the ones done are forgotten
        self.cancel_tried = {key: value for key, value in self.cancel_tried.items() if key in to_cancel}
        for simulation_id in sorted(to_cancel):
            self.cancel(simulation_id)

    def read_hpc_progress(self) -> None:
        """Starts a round saving what the tasks of running HPC simulations put into storage since the last look,
        spread over the readers; each reader's end comes as an event, the last one ends the round (hpc_progress_read)
        """
        if not result_storage.configured():
            return
        # one that ended recently may still have the last reports of its tasks to read: the last task completes it
        # seconds after its report, and the engine may be restarting or the storage out of reach meanwhile
        recently = datetime.now(timezone.utc) - timedelta(seconds=ENDED_READ_SECONDS)
        watched_since = datetime.now(timezone.utc) - timedelta(seconds=WATCHED_SECONDS)
        active = (
            db.session.query(
                BatchSimulationModel.id, BatchSimulationModel.job_state, UserActivityModel.seen_at >= watched_since
            )
            .outerjoin(UserActivityModel, UserActivityModel.user_id == BatchSimulationModel.user_id)
            .filter(
                BatchSimulationModel.array_id.isnot(None),
                or_(BatchSimulationModel.job_state.in_(HPC_ACTIVE_STATES), BatchSimulationModel.end_time >= recently),
            )
        )
        self.hpc_round = active.order_by(BatchSimulationModel.id).all()
        self.hpc_round_started = time.monotonic()
        # followed or ended lately: every round, so the last reports are read within ENDED_READ_SECONDS however
        # long rounds take
        often = {
            sim_id for sim_id, job_state, watched in self.hpc_round if watched or job_state not in HPC_ACTIVE_STATES
        }
        # the others a share each round, the longest unread first: each about every UNWATCHED_PROGRESS_SECONDS
        # (later while rounds take longer than HPC_PROGRESS_SECONDS)
        unwatched = sorted(
            (simulation_id for simulation_id, _, _ in self.hpc_round if simulation_id not in often),
            key=lambda simulation_id: self.hpc_read_at.get(simulation_id, float("-inf")),
        )
        due = unwatched[: math.ceil(len(unwatched) * HPC_PROGRESS_SECONDS / UNWATCHED_PROGRESS_SECONDS)]
        simulation_ids = sorted([*due, *often])
        if simulation_ids and not self.hpc_readers:
            self.hpc_readers = [HpcReader.remote() for _ in range(HPC_READERS)]
        # ponytail: simulations dealt out in turn, even while they have about as many tasks; by tasks if not
        for number, reader in enumerate(self.hpc_readers):
            group = simulation_ids[number :: len(self.hpc_readers)]
            if group:
                ref = reader.read.remote({sim_id: self.report_etags.get(sim_id, {}) for sim_id in group})
                self.hpc_reading.append(ref)
                self.watch(ref, None, "HPC_PROGRESS")
        if not self.hpc_reading:
            self.hpc_progress_read()

    def hpc_progress_read(self) -> None:
        """Ends the round once every reader is done: keeps what was read

        A reader that failed, e.g. with storage out of reach, leaves its simulations to the next round, which reads
        their reports again (the unwatched ones first); it is not a reason to stop the engine.
        """
        refs = self.hpc_reading
        if refs and len(ray.wait(refs, num_returns=len(refs), timeout=0)[0]) < len(refs):
            return
        # finished simulations are forgotten, the ones not read this round keep what was read before
        active = {simulation_id for simulation_id, _, _ in self.hpc_round}
        self.report_etags = {sim_id: etags for sim_id, etags in self.report_etags.items() if sim_id in active}
        self.hpc_read_at = {sim_id: read_at for sim_id, read_at in self.hpc_read_at.items() if sim_id in active}
        for ref in self.hpc_reading:
            try:
                read = ray.get(ref)
            except Exception:  # skipcq: PYL-W0703
                logging.exception("Reading HPC progress failed, trying again in %d s", HPC_PROGRESS_SECONDS)
                continue
            for simulation_id, reports in read.items():
                self.report_etags[simulation_id] = reports
                self.hpc_read_at[simulation_id] = self.hpc_round_started
        self.hpc_reading = []
        self.hpc_active = bool(self.hpc_round)

    def partial_merges(self) -> int:
        """Partial merges running"""
        return sum(1 for running in self.running.values() if running.partial)

    def submit(self, simulation_id: int) -> None:
        """Hands a stored HPC simulation to the cluster gateway, once at a time; not while its cluster's SLURM does
        not answer - it then waits PENDING for submit_waiting
        """
        if simulation_id not in self.submitting and self.may_call("submit", simulation_id):
            self.submitting[simulation_id] = self.cluster.submit.remote(simulation_id)
            self.watch(self.submitting[simulation_id], simulation_id, "SUBMITTED")

    def submit_waiting(self) -> None:
        """Submits the HPC simulations waiting for it: stored, or left PENDING by a cluster that did not answer (their
        submit first cancels what the attempt left on the cluster); the ones waiting longer than CLUSTER_WAIT_HOURS
        fail instead
        """
        waiting = (
            db.session.query(BatchSimulationModel)
            .filter(
                BatchSimulationModel.job_state == EntityState.PENDING.value, BatchSimulationModel.array_id.is_(None)
            )
            .order_by(BatchSimulationModel.id)
            .all()
        )
        given_up = datetime.now(timezone.utc) - timedelta(hours=CLUSTER_WAIT_HOURS)
        for simulation in waiting:
            # SQLite drops the time zone of the UTC time stored
            sent = simulation.start_time.replace(tzinfo=simulation.start_time.tzinfo or timezone.utc)
            if sent >= given_up or simulation.id in self.submitting:
                self.submit(simulation.id)
                continue
            error = f"The cluster did not answer for {CLUSTER_WAIT_HOURS:g} h, submit the simulation again later"
            fail_submit(simulation, {"error": error})
            if simulation.job_dir:
                # what an attempt left on the cluster
                self.cancel(simulation.id)

    def submitted(self, simulation_id: int) -> None:
        """A submit ended; it reports its own failures and leaves PENDING a simulation whose cluster did not answer.
        One that crashed (the gateway died) is repeated if it had not started yet; otherwise the simulation fails and
        whatever reached the cluster is cancelled.
        """
        ref = self.submitting.pop(simulation_id, None)
        # its jobs report from now on (read only while some HPC simulation may report)
        self.hpc_active = True
        try:
            answered = ray.get(ref)
        except Exception as error:  # skipcq: PYL-W0703
            self.answered(("submit", simulation_id), None)
            simulation = db.session.get(BatchSimulationModel, simulation_id)
            if simulation is None or simulation.job_state != EntityState.PENDING.value:
                return
            if simulation.job_dir is None:
                self.submit(simulation_id)
                return
            fail_submit(simulation, {"error": f"Submitting crashed: {error}"})
            self.cancel(simulation_id)
            return
        self.answered(("submit", simulation_id), answered)

    def watch(self, ref, simulation_id: Optional[int], event: str = "FINISHED") -> None:
        """Ray puts an event into the queue when the task, merge or submit finishes"""
        ref.future().add_done_callback(lambda _: self.events.put((event, simulation_id)))

    def watch_inbox(self) -> None:
        """An event comes when a task reports a new state, so e.g. RUNNING is saved without waiting for the next
        round of progress
        """
        self.watch(self.inbox.state_changed.remote(), None, "NEW_STATE")

    def recover(self) -> None:
        """Simulations running when the engine stopped lost their tasks with it; pending ones are started again (HPC
        ones too, after what an interrupted submit left on the cluster is cancelled)
        """
        try:
            if result_storage.configured():
                result_storage.expire_objects()
        except Exception:  # skipcq: PYL-W0703
            logging.exception("Setting the expiry of what tasks leave in storage failed")
        # cancels tried before the restart wait their turn: a restarting engine must not log in again each time
        self.cancel_tried = dict.fromkeys(self.cancels_left(), time.monotonic())
        # the breakers start closed: the clusters are tried again
        db.session.query(ClusterModel).update({ClusterModel.busy_until: None}, synchronize_session=False)
        db.session.commit()
        lost = db.session.query(CelerySimulationModel).filter(CelerySimulationModel.job_state.in_(RUNNING_STATES)).all()
        for simulation in lost:
            logging.warning("Simulation %d was running when the engine stopped, marking it failed", simulation.id)
            self.fail(simulation.id)
            # what its lost tasks stored is of no use; objects of others left behind expire
            try:
                result_storage.delete_objects(result_storage.work_prefix(simulation.id))
            except Exception:  # skipcq: PYL-W0703
                logging.exception("Removing the results stored by the lost tasks of %d failed", simulation.id)

    def sweep(self) -> None:
        """Brings the engine in line with the database: stops what was cancelled, starts what waits, takes results"""
        self.stop_cancelled()
        self.start_pending()
        self.collect_finished()

    def start_pending(self) -> None:
        """Submits the tasks of every simulation waiting to start"""
        pending = (
            db.session.query(CelerySimulationModel)
            .filter(
                CelerySimulationModel.job_state == EntityState.PENDING.value,
                CelerySimulationModel.id.notin_(self.running),
            )
            .order_by(CelerySimulationModel.id)
            .all()
        )
        for simulation in pending:
            self.start_guarded(simulation)
        # an HPC submit the engine's restart stopped half way is repeated too:
        # its jobs are cancelled by their comment first
        self.submit_waiting()
        self.retry_cancels()

    def start_guarded(self, simulation: CelerySimulationModel) -> None:
        """Starts a simulation; one that cannot start fails alone, without stopping the engine"""
        try:
            self.start(simulation)
        except DATABASE_FAILURES:
            # the database, not the simulation: the event fails and a sweep repeats it
            raise
        except Exception:  # skipcq: PYL-W0703
            logging.exception("Starting simulation %d failed", simulation.id)
            self.fail(simulation.id)

    def start(self, simulation: CelerySimulationModel) -> None:
        """Submits the tasks of a simulation"""
        files = dict(simulation.inputs[0].data["input_files"])
        if simulation.sim_type == SimulationType.SHIELDHIT.value:
            # saves along the way for partial results, in the tasks' copy only: the stored input stays the user's
            set_shieldhit_save_step(files, max(task.requested_primaries or 0 for task in simulation.tasks))
        files_ref = ray.put(files)
        task_ids = sorted(task.task_id for task in simulation.tasks)
        work_dirs = {task_id: get_tmp_dir() / f"{WORK_DIR_PREFIX}{simulation.id}_{task_id}" for task_id in task_ids}
        tasks = {
            run_task.remote(self.inbox, files_ref, simulation.sim_type, simulation.id, task_id, str(work_dir)): task_id
            for task_id, work_dir in work_dirs.items()
        }
        requested_primaries = sum(task.requested_primaries or 0 for task in simulation.tasks)
        self.running[simulation.id] = Running(tasks=tasks, work_dirs=work_dirs, requested_primaries=requested_primaries)
        for ref in tasks:
            self.watch(ref, simulation.id)
        logging.info("Started simulation %d with %d tasks", simulation.id, len(tasks))

    def save_progress(self) -> None:
        """Saves the progress the tasks reported since the last save, merges partial results when they are due"""
        self.progress_saved = time.monotonic()
        task_updates, saves = ray.get(self.inbox.drain.remote())
        by_simulation: dict[int, list[dict]] = {}
        for (simulation_id, task_id), update_dict in task_updates.items():
            by_simulation.setdefault(simulation_id, []).append({"task_id": task_id, "update_dict": update_dict})
        for simulation_id, updates in by_simulation.items():
            if simulation_id in self.running:
                self.save_task_updates(simulation_id, updates)
        for (simulation_id, task_id), save in saves.items():
            # a save reported after its task finished is older than the task's final results
            running = self.running.get(simulation_id)
            if running and task_id in running.tasks.values():
                running.saves[task_id] = save
        for simulation_id, running in self.running.items():
            self.merge_partial(simulation_id, running)

    def merge_partial(self, simulation_id: int, running: Running) -> None:
        """Merges the latest results of the tasks into partial results, when they cover enough new primaries"""
        primaries = sum(primaries for _, primaries in running.saves.values())
        grown = primaries - running.partial_primaries
        if running.partial or running.merge or grown <= 0 or grown < PARTIAL_GROWTH * running.requested_primaries:
            return
        # with every task finished the final merge is next
        if not running.tasks or self.partial_merges() >= MAX_PARTIAL_MERGES:
            return
        keys = [key for key, _ in running.saves.values()]
        running.partial = partial_merge_task.remote(simulation_id, keys, primaries)
        running.merging_primaries = primaries
        self.watch(running.partial, simulation_id, "PARTIAL")

    @staticmethod
    def partial_merged(simulation_id: int, running: Running) -> None:
        """Partial results that could not be merged are skipped, the simulation goes on; the next ones are due
        from the last stored ones
        """
        try:
            if ray.get(running.partial):
                running.partial_primaries = running.merging_primaries
        except Exception as error:  # skipcq: PYL-W0703
            logging.warning("Partial results of simulation %d failed: %s", simulation_id, error)
        running.partial = None

    @staticmethod
    def save_task_updates(simulation_id: int, updates: list[dict]) -> None:
        """Saves task updates and moves the simulation's state when a task's state changed; the streams of the
        simulation get one event for the whole batch
        """
        bulk_update_task_states(simulation_id, updates)
        simulation = db.session.get(SimulationModel, simulation_id)
        if simulation:
            update_state_from_tasks(simulation, any("task_state" in update["update_dict"] for update in updates))

    def collect_finished(self) -> None:
        """Takes the results of finished tasks; when all tasks of a simulation finished, merges them"""
        refs = [ref for running in self.running.values() for ref in running.refs()]
        if not refs:
            return
        ready, _ = ray.wait(refs, num_returns=len(refs), timeout=0)
        ready = set(ready)
        for simulation_id, running in list(self.running.items()):
            self.collect_guarded(simulation_id, running, ready)

    def collect_guarded(self, simulation_id: int, running: Running, ready: set) -> None:
        """Takes what finished of a simulation; one that cannot be handled fails alone, without stopping the engine"""
        try:
            self.collect(simulation_id, running, ready)
        except DATABASE_FAILURES:
            # the database, not the simulation: the event fails and a sweep repeats it
            raise
        except Exception:  # skipcq: PYL-W0703
            logging.exception("Handling simulation %d failed", simulation_id)
            self.fail(simulation_id)

    def collect(self, simulation_id: int, running: Running, ready: set) -> None:
        """Takes the finished tasks of one simulation, then its merge"""
        if running.merge in ready:
            self.finish_merge(simulation_id, running)
            return
        results = {ref: self.task_result(simulation_id, running, ref) for ref in running.tasks if ref in ready}
        if results:
            # saved before they are forgotten, so a failing save is repeated by the next sweep
            updates = [{"task_id": running.tasks[ref], "update_dict": r["final_update"]} for ref, r in results.items()]
            self.save_task_updates(simulation_id, updates)
            for ref, result in results.items():
                task_id = running.tasks.pop(ref)
                # a failed task's saves are left out
                running.saves.pop(task_id, None)
                if "result_key" in result:
                    running.result_keys.append(result["result_key"])
                    running.saves[task_id] = (result["result_key"], result["final_update"]["simulated_primaries"])
                running.logfiles.update(result.get("logfiles", {}))
        if not running.tasks and running.merge is None:
            self.start_merge(simulation_id, running)

    @staticmethod
    def task_result(simulation_id: int, running: Running, ref) -> dict:
        """Result of a finished task; a task that crashed or was stopped counts as failed"""
        task_id = running.tasks[ref]
        try:
            return ray.get(ref)
        except Exception as error:  # skipcq: PYL-W0703
            logging.error("Task %d of simulation %d crashed: %s", task_id, simulation_id, error)
            shutil.rmtree(running.work_dirs[task_id], ignore_errors=True)
            return {"final_update": {"task_state": EntityState.FAILED.value, "end_time": now()}}

    def start_merge(self, simulation_id: int, running: Running) -> None:
        """Stores the logs of failed tasks and merges the results of the others, if there are any"""
        simulation = db.session.get(SimulationModel, simulation_id)
        if simulation is None or simulation.job_state == EntityState.CANCELED.value:
            self.stop(simulation_id)
            return
        if running.logfiles:
            logfiles = LogfilesModel(simulation_id=simulation_id)
            logfiles.data = running.logfiles
            add_object_to_db(logfiles)
        if not running.result_keys:
            self.fail(simulation_id)
            return
        update_simulation_state(simulation, {"job_state": EntityState.MERGING_QUEUED.value})
        running.merge = merge_task.remote(simulation_id, running.result_keys)
        self.watch(running.merge, simulation_id)

    def finish_merge(self, simulation_id: int, running: Running) -> None:
        """A merge with nothing stored, or one that crashed, fails the simulation"""
        try:
            stored = ray.get(running.merge)
        except Exception as error:  # skipcq: PYL-W0703
            logging.error("Merging simulation %d crashed: %s", simulation_id, error)
            stored = False
        if not stored:
            self.fail(simulation_id)
        else:
            del self.running[simulation_id]
            delete_task_results.remote(simulation_id)
            logging.info("Simulation %d finished", simulation_id)

    def stop_cancelled(self) -> None:
        """Kills the tasks of simulations cancelled or deleted in the database"""
        if not self.running:
            return
        states = dict(
            db.session.query(SimulationModel.id, SimulationModel.job_state).filter(SimulationModel.id.in_(self.running))
        )
        for simulation_id in list(self.running):
            if states.get(simulation_id, EntityState.CANCELED.value) == EntityState.CANCELED.value:
                logging.info("Stopping simulation %d, cancelled or deleted", simulation_id)
                self.stop(simulation_id)

    def stop_overdue(self) -> None:
        """Kills tasks running longer than allowed; they then finish as failed"""
        if not self.running:
            return
        overdue = db.session.query(TaskModel.simulation_id, TaskModel.task_id).filter(
            TaskModel.simulation_id.in_(self.running),
            TaskModel.task_state == EntityState.RUNNING.value,
            TaskModel.start_time < datetime.utcnow() - timedelta(seconds=TASK_SECONDS_LIMIT),
        )
        for simulation_id, task_id in overdue:
            for ref, running_task_id in self.running[simulation_id].tasks.items():
                if running_task_id == task_id:
                    logging.warning("Task %d of simulation %d runs too long, stopping it", task_id, simulation_id)
                    ray.cancel(ref)

    def stop(self, simulation_id: int) -> None:
        """Kills what still runs for a simulation and removes its directories and what its tasks stored"""
        running = self.running.pop(simulation_id, None)
        if running is None:
            return
        # not forced: that kills the worker process, maybe just as it takes a task of another simulation;
        # a running simulator is killed by its task (execute_simulation_subprocess)
        for ref in running.refs():
            ray.cancel(ref)
        for work_dir in running.work_dirs.values():
            shutil.rmtree(work_dir, ignore_errors=True)
        delete_task_results.remote(simulation_id)

    def fail(self, simulation_id: int) -> None:
        """Marks a simulation and its unfinished tasks failed, unless it reached a final state meanwhile, then stops it

        Written first: if the database fails, the simulation stays with the engine and a sweep tries again.
        """
        db.session.query(TaskModel).filter(
            TaskModel.simulation_id == simulation_id, TaskModel.task_state.notin_(FINAL_STATES)
        ).update({TaskModel.task_state: EntityState.FAILED.value}, synchronize_session=False)
        db.session.commit()
        simulation = db.session.get(SimulationModel, simulation_id)
        if simulation:
            update_simulation_state(simulation, {"job_state": EntityState.FAILED.value, "end_time": now()})
        self.stop(simulation_id)


def listen(database_uri: str, events: queue.Queue) -> None:
    """Puts the database's events for the engine into the queue, and a sweep after every (re)connection, which
    catches what was committed while nobody listened
    """

    def notified(payload: str) -> None:
        """Queues one event"""
        event = json.loads(payload)
        events.put((event["event"], event["simulation"], event.get("platform")))

    listen_to(database_uri, ENGINE_CHANNEL, lambda: events.put(("SWEEP", None)), notified)


def main() -> None:
    """Runs the engine on the Ray cluster started next to it, until it fails for about a minute"""
    logging.basicConfig(level=os.environ.get("LOG_LEVEL_ROOT", "INFO"))
    ray.init(address="auto")
    app = backend_app()
    with app.app_context():
        engine = Engine()
        listener = threading.Thread(
            target=listen, args=(app.config["SQLALCHEMY_DATABASE_URI"], engine.events), daemon=True
        )
        listener.start()
        engine.run(listener)


if __name__ == "__main__":
    main()
