import asyncio
import logging

import ray

from yaptide.batch.batch_methods import submit_job

SUBMITTER_NAME = "batch-submitter"


@ray.remote(num_cpus=0)
class BatchSubmitter:
    """Submits HPC jobs on the Ray cluster, each in its own thread; one long-lived actor serves all requests"""

    def __init__(self):
        """Keeps the submits in progress, so they are not garbage collected while running"""
        self.submitting: set[asyncio.Task] = set()

    async def submit(self, **submit_kwargs) -> None:
        """Starts a submit and returns at once - the submit reports its outcome to the backend itself"""
        task = asyncio.get_running_loop().create_task(asyncio.to_thread(submit_job, **submit_kwargs))
        self.submitting.add(task)
        task.add_done_callback(self._done)

    def _done(self, task: asyncio.Task) -> None:
        """Forgets a finished submit, logging what submit_job could not report to the backend"""
        self.submitting.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logging.error("Submitting an HPC job failed", exc_info=task.exception())
