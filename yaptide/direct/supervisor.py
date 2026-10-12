import asyncio
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

import ray

from yaptide.direct.backend_client import FINAL_POST_ATTEMPTS, send_job_state, send_task_updates
from yaptide.direct.pymc import get_tmp_dir
from yaptide.direct.simulation import WORK_DIR_PREFIX, finish_simulation, run_simulation
from yaptide.utils.enums import EntityState

NAMESPACE = "yaptide"
FLUSH_INTERVAL_SECONDS = 2
# tasks waiting for a free core report nothing; this keeps them from looking abandoned (see direct_routes)
HEARTBEAT_SECONDS = 60


def supervisor_name(simulation_id: int) -> str:
    """Name of the supervisor actor of a simulation, used to find it again, e.g. to cancel"""
    return f"supervisor-{simulation_id}"


@ray.remote(num_cpus=1, max_retries=0)
def run_simulation_task(
    supervisor, files_dict: dict, task_id: int, sim_type: str, work_dir: str, simulation_id: int
) -> dict:
    """Runs one simulation task on the cluster; its progress goes to the supervisor, not to the backend"""

    def report(update_dict: dict) -> None:
        """Hands a task state update to the supervisor, which sends the updates in batches"""
        supervisor.update_task.remote(task_id, update_dict)

    return run_simulation(files_dict, task_id, sim_type, Path(work_dir), simulation_id, report)


@ray.remote(num_cpus=0, max_restarts=0)
class SimulationSupervisor:
    """Runs one simulation: starts its tasks, sends their states in batches, merges the results, then exits"""

    def __init__(self, simulation_id: int, update_key: str):
        """Supervisor of one simulation, reporting to the backend with the simulation's update key"""
        self.simulation_id = simulation_id
        self.update_key = update_key
        self.updates: dict[int, dict] = {}
        self.refs: list = []
        self.work_dirs: list[Path] = []
        self.finished: set[int] = set()
        self.cancelled = False
        self.supervising: Optional[asyncio.Task] = None

    async def start(self, files_dict: dict, ntasks: int, sim_type: str) -> int:
        """Submits the tasks and returns at once; supervising continues in the background"""
        me = ray.get_runtime_context().current_actor
        # the supervisor owns the paths, so it can remove them even when a task is killed
        self.work_dirs = [
            get_tmp_dir() / f"{WORK_DIR_PREFIX}{self.simulation_id}_{task_id}" for task_id in range(ntasks)
        ]
        files_ref = ray.put(files_dict)
        self.refs = [
            run_simulation_task.remote(me, files_ref, task_id, sim_type, str(work_dir), self.simulation_id)
            for task_id, work_dir in enumerate(self.work_dirs)
        ]
        self.supervising = asyncio.get_running_loop().create_task(self._supervise())
        return ntasks

    async def update_task(self, task_id: int, update_dict: dict) -> None:
        """Keeps the latest state of a task until the next batch is sent"""
        # progress can arrive after the task's final state, it must not overwrite it
        if not self.cancelled and task_id not in self.finished:
            self.updates.setdefault(task_id, {}).update(update_dict)

    async def cancel(self) -> None:
        """Kills the running tasks - a task waiting for the simulator does not react to a gentle cancel"""
        self.cancelled = True
        self.updates.clear()
        for ref in self.refs:
            ray.cancel(ref, force=True)

    async def _flush(self) -> None:
        """Sends the collected task states in one request, keeping them for the next try if the backend is down"""
        if not self.updates or self.cancelled:
            return
        updates, self.updates = self.updates, {}
        # refused for good (e.g. the simulation was deleted) - sending them again would not help
        if await asyncio.to_thread(send_task_updates, self.simulation_id, self.update_key, updates) is None:
            for task_id, update_dict in updates.items():
                self.updates[task_id] = {**update_dict, **self.updates.get(task_id, {})}

    async def _supervise(self) -> None:
        """Waits for the tasks while sending their states, then finishes the simulation and exits"""
        try:
            await self._wait_for_tasks()
        except Exception:  # skipcq: PYL-W0703
            logging.exception("Supervising simulation %d failed", self.simulation_id)
            if not self.cancelled:
                end_time = datetime.utcnow().isoformat(sep=" ")
                update = {"job_state": EntityState.FAILED.value, "end_time": end_time}
                await asyncio.to_thread(
                    send_job_state, self.simulation_id, self.update_key, update, FINAL_POST_ATTEMPTS
                )
        finally:
            ray.kill(ray.get_runtime_context().current_actor, no_restart=True)

    async def _wait_for_tasks(self) -> None:
        """Collects the task results, then merges them, or only cleans up after a cancel"""
        futures = {asyncio.wrap_future(ref.future()): task_id for task_id, ref in enumerate(self.refs)}
        results = []
        pending = set(futures)
        last_heartbeat = asyncio.get_running_loop().time()
        while pending:
            done, pending = await asyncio.wait(pending, timeout=FLUSH_INTERVAL_SECONDS)
            for future in done:
                results.append(self._task_result(futures[future], future))
            if asyncio.get_running_loop().time() - last_heartbeat > HEARTBEAT_SECONDS:
                last_heartbeat = asyncio.get_running_loop().time()
                # an empty update still refreshes the task's last_update_time
                for task_id in set(range(len(self.refs))) - self.finished:
                    self.updates.setdefault(task_id, {})
            await self._flush()

        if self.cancelled:
            for work_dir in self.work_dirs:
                shutil.rmtree(work_dir, ignore_errors=True)
            return
        await asyncio.to_thread(finish_simulation, results, self.simulation_id, self.update_key, lambda: self.cancelled)

    def _task_result(self, task_id: int, future: asyncio.Future) -> dict:
        """Result of a finished task, with its final state queued for the next batch; a crashed task counts as failed"""
        self.finished.add(task_id)
        error: Optional[BaseException] = future.exception()
        if error is None:
            result = future.result()
        else:
            if not self.cancelled:
                logging.error("Task %d of simulation %d crashed: %s", task_id, self.simulation_id, error)
            shutil.rmtree(self.work_dirs[task_id], ignore_errors=True)
            result = {
                "logfiles": {},
                "final_update": {
                    "task_state": EntityState.FAILED.value,
                    "end_time": datetime.utcnow().isoformat(sep=" "),
                },
            }
        if not self.cancelled:
            self.updates.setdefault(task_id, {}).update(result["final_update"])
        return result
