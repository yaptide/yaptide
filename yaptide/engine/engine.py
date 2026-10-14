"""Long-lived engine running direct simulations on the Ray cluster it is started on.

Flask only stores simulations in the database. The engine picks up the pending ones, runs their tasks on Ray,
writes their progress and results to the database itself and stops the ones cancelled there.
"""

import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import ray

from yaptide.engine.pymc import get_tmp_dir
from yaptide.engine.simulation import WORK_DIR_PREFIX, backend_app, merge_and_store, run_simulation
from yaptide.persistence.database import db
from yaptide.persistence.db_methods import add_object_to_db, bulk_update_task_states, update_simulation_state
from yaptide.persistence.models import CelerySimulationModel, LogfilesModel, SimulationModel, TaskModel
from yaptide.routes.utils.utils import FINAL_STATES, update_direct_state_from_tasks
from yaptide.utils.enums import EntityState

# how often the engine looks for new and cancelled simulations and saves progress
TICK_SECONDS = 2
# a task running longer is stopped, as the Celery workers did
TASK_SECONDS_LIMIT = 10 * 3600
# the engine gives up and restarts with its container after failing this many ticks in a row (about a minute)
FAILED_TICKS_LIMIT = 30
RUNNING_STATES = (EntityState.RUNNING.value, EntityState.MERGING_QUEUED.value, EntityState.MERGING_RUNNING.value)


# restarted when it dies: only progress since the last tick is lost, final states come with the task results
@ray.remote(num_cpus=0, max_restarts=-1, max_task_retries=-1)
class ProgressInbox:
    """Keeps the latest progress of every task until the engine saves it"""

    def __init__(self):
        """Empty inbox"""
        self.updates: dict[tuple[int, int], dict] = {}

    def report(self, simulation_id: int, task_id: int, update_dict: dict) -> None:
        """Merges a task's update into the one waiting to be saved"""
        self.updates.setdefault((simulation_id, task_id), {}).update(update_dict)

    def drain(self) -> dict[tuple[int, int], dict]:
        """Hands over the waiting updates"""
        updates, self.updates = self.updates, {}
        return updates


@ray.remote(num_cpus=1, max_retries=0)
def run_task(inbox, files_dict: dict, sim_type: str, simulation_id: int, task_id: int, work_dir: str) -> dict:
    """One simulation task; its progress goes to the inbox"""

    def report(update_dict: dict) -> None:
        """Hands a progress update to the inbox"""
        inbox.report.remote(simulation_id, task_id, update_dict)

    return run_simulation(files_dict, task_id, sim_type, Path(work_dir), simulation_id, report)


# a merge killed for memory must not be retried forever, which Ray does unless retries are off;
# it takes no CPU slot, so a finished simulation does not wait behind the tasks of others (merges are short and rare)
@ray.remote(num_cpus=0, max_retries=0)
def merge_task(simulation_id: int, output_dirs: list[str]) -> bool:
    """Merges and stores the results of a simulation"""
    return merge_and_store(simulation_id, output_dirs)


@dataclass
class Running:
    """A simulation the engine runs: its tasks still running, then its merge"""

    tasks: dict  # task ref -> task id
    work_dirs: dict[int, Path]
    output_dirs: list[str] = field(default_factory=list)
    logfiles: dict = field(default_factory=dict)
    merge: Optional[ray.ObjectRef] = None

    def refs(self) -> list:
        """What the engine waits for"""
        return [*self.tasks, self.merge] if self.merge else list(self.tasks)


def now() -> str:
    """Current time as the task and simulation updates carry it"""
    return datetime.utcnow().isoformat(sep=" ")


class Engine:
    """Runs the direct simulations stored in the database, one tick at a time"""

    def __init__(self):
        """Engine with nothing running yet"""
        self.inbox = ProgressInbox.remote()
        self.running: dict[int, Running] = {}

    def recover(self) -> None:
        """Simulations running when the engine stopped lost their tasks with it; pending ones are started again"""
        lost = db.session.query(CelerySimulationModel).filter(CelerySimulationModel.job_state.in_(RUNNING_STATES)).all()
        for simulation in lost:
            logging.warning("Simulation %d was running when the engine stopped, marking it failed", simulation.id)
            self.fail(simulation.id)

    def tick(self) -> None:
        """Starts new simulations, saves progress, handles finished tasks and stops cancelled or overdue ones"""
        try:
            self.stop_cancelled()
            self.start_pending()
            self.save_progress()
            self.collect_finished()
            self.stop_overdue()
        finally:
            db.session.remove()

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
            try:
                self.start(simulation)
            except Exception:  # skipcq: PYL-W0703
                # one broken simulation must not keep the engine from the others
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
        self.running[simulation.id] = Running(tasks=tasks, work_dirs=work_dirs)
        logging.info("Started simulation %d with %d tasks", simulation.id, len(tasks))

    def save_progress(self) -> None:
        """Saves the progress the tasks reported since the last tick"""
        by_simulation: dict[int, list[dict]] = {}
        for (simulation_id, task_id), update_dict in ray.get(self.inbox.drain.remote()).items():
            by_simulation.setdefault(simulation_id, []).append({"task_id": task_id, "update_dict": update_dict})
        for simulation_id, updates in by_simulation.items():
            if simulation_id in self.running:
                self.save_task_updates(simulation_id, updates)

    def save_task_updates(self, simulation_id: int, updates: list[dict]) -> None:
        """Saves task updates and moves the simulation's state when a task's state changed"""
        bulk_update_task_states(simulation_id, updates)
        if any("task_state" in update["update_dict"] for update in updates):
            simulation = db.session.get(SimulationModel, simulation_id)
            if simulation:
                update_direct_state_from_tasks(simulation)

    def collect_finished(self) -> None:
        """Takes the results of finished tasks; when all tasks of a simulation finished, merges them"""
        refs = [ref for running in self.running.values() for ref in running.refs()]
        if not refs:
            return
        ready, _ = ray.wait(refs, num_returns=len(refs), timeout=0)
        ready = set(ready)
        for simulation_id, running in list(self.running.items()):
            try:
                self.collect(simulation_id, running, ready)
            except Exception:  # skipcq: PYL-W0703
                # one broken simulation must not keep the engine from the others
                logging.exception("Handling simulation %d failed", simulation_id)
                self.fail(simulation_id)

    def collect(self, simulation_id: int, running: Running, ready: set) -> None:
        """Takes the finished tasks of one simulation, then its merge"""
        if running.merge in ready:
            self.finish_merge(simulation_id, running)
            return
        results = {ref: self.task_result(simulation_id, running, ref) for ref in running.tasks if ref in ready}
        if results:
            # saved before they are forgotten, so a failing save is repeated on the next tick
            updates = [{"task_id": running.tasks[ref], "update_dict": r["final_update"]} for ref, r in results.items()]
            self.save_task_updates(simulation_id, updates)
            for ref, result in results.items():
                del running.tasks[ref]
                if "output_dir" in result:
                    running.output_dirs.append(result["output_dir"])
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
        """Marks a simulation and its unfinished tasks failed, unless it reached a final state meanwhile"""
        self.stop(simulation_id)
        db.session.query(TaskModel).filter(
            TaskModel.simulation_id == simulation_id, TaskModel.task_state.notin_(FINAL_STATES)
        ).update({TaskModel.task_state: EntityState.FAILED.value}, synchronize_session=False)
        db.session.commit()
        simulation = db.session.get(SimulationModel, simulation_id)
        if simulation:
            update_simulation_state(simulation, {"job_state": EntityState.FAILED.value, "end_time": now()})


def main() -> None:
    """Runs the engine on the Ray cluster started next to it, until it fails for about a minute"""
    logging.basicConfig(level=os.environ.get("LOG_LEVEL_ROOT", "INFO"))
    ray.init(address="auto")
    with backend_app().app_context():
        engine = Engine()
        engine.recover()
        failed_ticks = 0
        while True:
            try:
                engine.tick()
                failed_ticks = 0
            except Exception:  # skipcq: PYL-W0703
                failed_ticks += 1
                logging.exception("Engine tick failed (%d in a row)", failed_ticks)
                if failed_ticks >= FAILED_TICKS_LIMIT:
                    raise
            time.sleep(TICK_SECONDS)


if __name__ == "__main__":
    main()
