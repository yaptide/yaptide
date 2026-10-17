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
import os
import queue
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import ray
from sqlalchemy import or_

from yaptide.batch.batch_methods import cancel_simulation, fail_submit, submit_simulation
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
    update_simulation_state,
)
from yaptide.persistence.models import (
    ENGINE_CHANNEL,
    BatchSimulationModel,
    CelerySimulationModel,
    LogfilesModel,
    SimulationModel,
    TaskModel,
)
from yaptide.routes.utils.utils import FINAL_STATES, update_state_from_tasks
from yaptide.utils.enums import EntityState, PlatformType

# SSH connections to the clusters at once; they ban accounts that log in often
CLUSTER_CONNECTIONS = 4
# how often the progress HPC tasks put into storage is read
HPC_PROGRESS_SECONDS = 10
# a task's progress object, and what its report may set
REPORT_KEY = re.compile(r".*/task_(\d{1,6})\.json")
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


HPC_ACTIVE_STATES = (
    EntityState.PENDING.value,
    EntityState.RUNNING.value,
    EntityState.MERGING_QUEUED.value,
    EntityState.MERGING_RUNNING.value,
)
# progress is saved in batches, not for every line the simulators log
PROGRESS_SECONDS = 1
# a task running longer is stopped, as the Celery workers did; checked once a minute
TASK_SECONDS_LIMIT = 10 * 3600
OVERDUE_CHECK_SECONDS = 60
# the engine gives up and restarts with its container after failing for this long
GIVE_UP_SECONDS = 60
# partial results are merged again once the saves of the tasks cover this much more of the requested primaries
PARTIAL_GROWTH = 0.05
RUNNING_STATES = (EntityState.RUNNING.value, EntityState.MERGING_QUEUED.value, EntityState.MERGING_RUNNING.value)


# restarted when it dies: only progress not saved yet is lost, final states come with the task results
@ray.remote(num_cpus=0, max_restarts=-1, max_task_retries=-1)
class ProgressInbox:
    """Keeps the latest progress and the latest save of every task until the engine takes them"""

    def __init__(self):
        """Empty inbox"""
        self.updates: dict[tuple[int, int], dict] = {}
        self.saves: dict[tuple[int, int], tuple[str, int]] = {}

    def report(self, simulation_id: int, task_id: int, update_dict: dict) -> None:
        """Merges a task's update into the one waiting to be saved"""
        self.updates.setdefault((simulation_id, task_id), {}).update(update_dict)

    def saved(self, simulation_id: int, task_id: int, snapshot_dir: str, primaries: int) -> None:
        """Replaces a task's save waiting to be taken"""
        self.saves[(simulation_id, task_id)] = (snapshot_dir, primaries)

    def drain(self) -> tuple[dict[tuple[int, int], dict], dict[tuple[int, int], tuple[str, int]]]:
        """Hands over the waiting updates and saves"""
        updates, saves, self.updates, self.saves = self.updates, self.saves, {}, {}
        return updates, saves


@ray.remote(num_cpus=1, max_retries=0)
def run_task(inbox, files_dict: dict, sim_type: str, simulation_id: int, task_id: int, work_dir: str) -> dict:
    """One simulation task; its progress goes to the inbox"""

    def report(update_dict: dict) -> None:
        """Hands a progress update to the inbox"""
        inbox.report.remote(simulation_id, task_id, update_dict)

    def saved(snapshot_dir: str, primaries: int) -> None:
        """Hands a save of the results to the inbox"""
        inbox.saved.remote(simulation_id, task_id, snapshot_dir, primaries)

    return run_simulation(files_dict, task_id, sim_type, Path(work_dir), simulation_id, report, saved)


# a merge killed for memory must not be retried forever, which Ray does unless retries are off;
# it takes no CPU slot, so a finished simulation does not wait behind the tasks of others (merges are short and rare)
@ray.remote(num_cpus=0, max_retries=0)
def merge_task(simulation_id: int, output_dirs: list[str]) -> bool:
    """Merges and stores the results of a simulation"""
    return merge_and_store(simulation_id, output_dirs)


# like the merge; one that fails is skipped, the next saves bring the next partial results
@ray.remote(num_cpus=0, max_retries=0)
def partial_merge_task(simulation_id: int, snapshot_dirs: list[str], primaries: int) -> bool:
    """Merges the latest saves of the tasks of a running simulation and stores them as its partial results"""
    return merge_and_store_partial(simulation_id, snapshot_dirs, primaries)


@ray.remote(num_cpus=0, max_concurrency=CLUSTER_CONNECTIONS, max_restarts=-1)
class ClusterGateway:
    """Submits and cancels HPC simulations over SSH with the users' certificates, a few connections at a time"""

    @staticmethod
    def submit(simulation_id: int) -> None:
        """Submits a stored HPC simulation; it ends FAILED itself when it cannot be submitted"""
        with backend_app().app_context():
            try:
                submit_simulation(simulation_id)
            finally:
                db.session.remove()

    @staticmethod
    def cancel(simulation_id: int) -> None:
        """Cancels the jobs of a cancelled HPC simulation on its cluster"""
        with backend_app().app_context():
            try:
                cancel_simulation(simulation_id)
            finally:
                db.session.remove()


@dataclass
class Running:
    """A simulation the engine runs: its tasks still running, then its merge"""

    tasks: dict  # task ref -> task id
    work_dirs: dict[int, Path]
    requested_primaries: int = 0
    output_dirs: list[str] = field(default_factory=list)
    logfiles: dict = field(default_factory=dict)
    merge: Optional[ray.ObjectRef] = None
    # the latest results of every task, saved while running or final: task id -> (directory, primaries)
    saves: dict[int, tuple[str, int]] = field(default_factory=dict)
    partial: Optional[ray.ObjectRef] = None
    partial_primaries: int = 0

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
        # ETags of the progress reports HPC tasks put into storage, as last read
        self.report_etags: dict[str, str] = {}
        # HPC simulations being submitted (simulation id -> the submit's ref) and cancelled on their cluster
        self.submitting: dict[int, ray.ObjectRef] = {}
        self.cancelling: set[int] = set()
        self.running: dict[int, Running] = {}
        # (event, simulation id, platform): PENDING, CANCELED, DELETED from Postgres, FINISHED and SUBMITTED
        # from Ray, SWEEP
        self.events: queue.Queue = queue.Queue()

    def run(self, listener: Optional[threading.Thread] = None) -> None:
        """Handles events as they come, saves progress every second, until failing for a minute

        A listener thread that died would leave the engine without events, so the engine stops with it.
        """
        self.recover()
        self.events.put(("SWEEP", None))
        last_progress = last_overdue_check = last_hpc_progress = time.monotonic()
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
                    self.save_progress()
                if time.monotonic() - last_hpc_progress >= HPC_PROGRESS_SECONDS:
                    last_hpc_progress = time.monotonic()
                    self.read_hpc_progress()
                if time.monotonic() - last_overdue_check >= OVERDUE_CHECK_SECONDS:
                    last_overdue_check = time.monotonic()
                    self.stop_overdue()
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

    def handle(self, event: str, simulation_id: Optional[int], platform: Optional[str] = None) -> None:
        """Acts on one event"""
        if platform == PlatformType.BATCH.value:
            self.handle_batch(event, simulation_id)
        elif event == "SWEEP":
            self.sweep()
        elif event == "SUBMITTED":
            self.submitted(simulation_id)
        elif event == "CANCELLED_ON_CLUSTER":
            # done, or to be repeated by a sweep: the job directory stays in the database until it is done
            self.cancelling.discard(simulation_id)
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

    def handle_batch(self, event: str, simulation_id: int) -> None:
        """HPC simulations: the engine submits the stored ones and cancels the cancelled ones on their cluster"""
        if event == EntityState.PENDING.value:
            self.submit(simulation_id)
        elif event == EntityState.CANCELED.value:
            self.cancel(simulation_id)

    def cancel(self, simulation_id: int) -> None:
        """Cancels an HPC simulation: its tasks find the cancel in storage, and while the user's certificate lasts
        the cluster gateway also cancels the jobs at once (and removes the job directory)
        """
        try:
            if result_storage.configured():
                result_storage.put_cancel(simulation_id)
        except Exception:  # skipcq: PYL-W0703
            # put again by the cancel a sweep repeats, as long as the job directory is recorded
            logging.exception("Putting the cancel of simulation %d into storage failed", simulation_id)
        if simulation_id not in self.cancelling:
            self.cancelling.add(simulation_id)
            self.watch(self.cluster.cancel.remote(simulation_id), simulation_id, "CANCELLED_ON_CLUSTER")

    def read_hpc_progress(self) -> None:
        """Saves what the tasks of running HPC simulations put into storage since the last look

        A report that cannot be used is skipped (and not read again until it changes); storage out of reach ends
        the round - it is not a reason to stop the engine, and the next round tries again.
        """
        if not result_storage.configured():
            return
        # one completed since the last look still has the last reports of its tasks to read
        recently = datetime.now(timezone.utc) - timedelta(seconds=3 * HPC_PROGRESS_SECONDS)
        active = db.session.query(BatchSimulationModel.id).filter(
            BatchSimulationModel.array_id.isnot(None),
            or_(BatchSimulationModel.job_state.in_(HPC_ACTIVE_STATES), BatchSimulationModel.end_time >= recently),
        )
        seen: dict[str, str] = {}
        for (simulation_id,) in active.all():
            try:
                reports = result_storage.progress_reports(simulation_id)
                updates = [
                    update
                    for key, etag in reports.items()
                    if self.report_etags.get(key) != etag
                    for update in [self.read_report(key)]
                    if update
                ]
            except Exception:  # skipcq: PYL-W0703
                logging.exception("Reading HPC progress failed, trying again in %d s", HPC_PROGRESS_SECONDS)
                return
            try:
                if updates:
                    self.save_task_updates(simulation_id, updates)
            except DATABASE_FAILURES:
                raise
            except Exception:  # skipcq: PYL-W0703
                logging.exception("Progress of simulation %d refused", simulation_id)
            seen.update(reports)
        # finished simulations are forgotten
        self.report_etags = seen

    @staticmethod
    def read_report(key: str) -> Optional[dict]:
        """A task's report as a task update: the task comes from the object's name, only valid fields count"""
        match = REPORT_KEY.fullmatch(key)
        if not match:
            return None
        try:
            report = result_storage.read_report(key)
            update = clean_report(report["update"])
        except (KeyError, TypeError, ValueError):
            logging.warning("Unreadable progress report %s", key)
            return None
        return {"task_id": int(match.group(1)), "update_dict": update} if update else None

    def submit(self, simulation_id: int) -> None:
        """Hands a stored HPC simulation to the cluster gateway, once"""
        if simulation_id not in self.submitting:
            self.submitting[simulation_id] = self.cluster.submit.remote(simulation_id)
            self.watch(self.submitting[simulation_id], simulation_id, "SUBMITTED")

    def submitted(self, simulation_id: int) -> None:
        """A submit ended; it reports its own failures. One that crashed (the gateway died) is repeated if it had
        not started yet; otherwise the simulation fails and whatever reached the cluster is cancelled.
        """
        ref = self.submitting.pop(simulation_id, None)
        try:
            ray.get(ref)
        except Exception as error:  # skipcq: PYL-W0703
            simulation = db.session.get(BatchSimulationModel, simulation_id)
            if simulation is None or simulation.job_state != EntityState.PENDING.value:
                return
            if simulation.job_dir is None:
                self.submit(simulation_id)
                return
            fail_submit(simulation, {"error": f"Submitting crashed: {error}"})
            self.cancel(simulation_id)

    def watch(self, ref, simulation_id: int, event: str = "FINISHED") -> None:
        """Ray puts an event into the queue when the task, merge or submit finishes"""
        ref.future().add_done_callback(lambda _: self.events.put((event, simulation_id)))

    def recover(self) -> None:
        """Simulations running when the engine stopped lost their tasks with it; pending ones are started again"""
        lost = db.session.query(CelerySimulationModel).filter(CelerySimulationModel.job_state.in_(RUNNING_STATES)).all()
        for simulation in lost:
            logging.warning("Simulation %d was running when the engine stopped, marking it failed", simulation.id)
            self.fail(simulation.id)
        # an HPC submit stopped half way: the jobs may or may not be on the cluster, so it is not repeated
        interrupted = (
            db.session.query(BatchSimulationModel)
            .filter(
                BatchSimulationModel.job_state == EntityState.PENDING.value,
                BatchSimulationModel.job_dir.isnot(None),
                BatchSimulationModel.array_id.is_(None),
            )
            .all()
        )
        for simulation in interrupted:
            fail_submit(simulation, {"error": "Submitting was interrupted, its jobs are cancelled"})
            self.cancel(simulation.id)

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
        waiting = db.session.query(BatchSimulationModel.id).filter(
            BatchSimulationModel.job_state == EntityState.PENDING.value, BatchSimulationModel.job_dir.is_(None)
        )
        for (simulation_id,) in waiting:
            self.submit(simulation_id)
        # cancels whose event was lost, or that could not reach the cluster: the job directory is still recorded
        to_cancel = db.session.query(BatchSimulationModel.id).filter(
            BatchSimulationModel.job_state == EntityState.CANCELED.value, BatchSimulationModel.job_dir.isnot(None)
        )
        for (simulation_id,) in to_cancel:
            self.cancel(simulation_id)

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
        files_ref = ray.put(simulation.inputs[0].data["input_files"])
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
        snapshot_dirs = [snapshot_dir for snapshot_dir, _ in running.saves.values()]
        running.partial = partial_merge_task.remote(simulation_id, snapshot_dirs, primaries)
        running.partial_primaries = primaries
        self.watch(running.partial, simulation_id, "PARTIAL")

    @staticmethod
    def partial_merged(simulation_id: int, running: Running) -> None:
        """Partial results that could not be merged are skipped, the simulation goes on"""
        try:
            ray.get(running.partial)
        except Exception as error:  # skipcq: PYL-W0703
            logging.warning("Partial results of simulation %d failed: %s", simulation_id, error)
        running.partial = None

    @staticmethod
    def save_task_updates(simulation_id: int, updates: list[dict]) -> None:
        """Saves task updates and moves the simulation's state when a task's state changed"""
        bulk_update_task_states(simulation_id, updates)
        if any("task_state" in update["update_dict"] for update in updates):
            simulation = db.session.get(SimulationModel, simulation_id)
            if simulation:
                update_state_from_tasks(simulation)

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
                # a failed task's directory is gone, its saves with it
                running.saves.pop(task_id, None)
                if "output_dir" in result:
                    running.output_dirs.append(result["output_dir"])
                    running.saves[task_id] = (result["output_dir"], result["final_update"]["simulated_primaries"])
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
        if not running.output_dirs:
            self.fail(simulation_id)
            return
        update_simulation_state(simulation, {"job_state": EntityState.MERGING_QUEUED.value})
        running.merge = merge_task.remote(simulation_id, running.output_dirs)
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
        """Kills what still runs for a simulation and removes its directories"""
        running = self.running.pop(simulation_id, None)
        if running is None:
            return
        # not forced: that kills the worker process, maybe just as it takes a task of another simulation;
        # a running simulator is killed by its task (execute_simulation_subprocess)
        for ref in running.refs():
            ray.cancel(ref)
        for work_dir in running.work_dirs.values():
            shutil.rmtree(work_dir, ignore_errors=True)

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
    catches what was committed while nobody listened"""

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
