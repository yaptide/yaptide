import logging
import os
import tempfile

from datetime import datetime
from multiprocessing import Process
from pathlib import Path

# import eventlet
from pymchelper.executor.options import SimulationSettings
from pymchelper.executor.runner import Runner as SHRunner
from yaptide.admin.simulators import SimulatorType, install_simulator

from yaptide.celery.utils.pymc import run_shieldhit, read_file, average_estimators
from yaptide.celery.utils.requests import send_simulation_logfiles, send_simulation_results, send_task_update
from yaptide.celery.worker import celery_app
from yaptide.utils.sim_utils import (check_and_convert_payload_to_files_dict, estimators_to_list,
                                     simulation_logfiles, write_simulation_input_files)


# this is not being used now but we can use such hook to install simulations on the worker start
# needs from celery.signals import worker_ready
# @worker_ready.connect
# def on_worker_ready(**kwargs):
#     """This function will be called when celery worker is ready to accept tasks"""
#     logging.info("on_worker_ready signal received")
#     # ask celery to install simulator on the worker and wait for it to finish
#     job = install_simulators.delay()
#     # we need to do some hackery here to make blocking calls work
#     # method described in https://stackoverflow.com/questions/33280456 doesn't work.
#     try:
#         job.wait()
#     except RuntimeError as e:
#         logging.info("the only way for blocking calls to work is to catch RuntimeError %s", e)
#         raise e


@celery_app.task()
def install_simulators() -> bool:
    """Task responsible for installing simulators on the worker"""
    result = install_simulator(SimulatorType.shieldhit)
    return result


@celery_app.task
def convert_input_files(payload_dict: dict) -> dict:
    """Function converting output"""
    files_dict = check_and_convert_payload_to_files_dict(payload_dict=payload_dict)
    return {"input_files": files_dict}


@celery_app.task
def run_single_simulation(files_dict: dict, task_id: int, update_key: str = None, simulation_id: int = None) -> dict:
    """Function running single shieldhit simulation"""
    with tempfile.TemporaryDirectory() as tmp_dir_path:
        logging.debug("Task %d saves the files for simulation %s", task_id ,files_dict.keys())
        write_simulation_input_files(files_dict=files_dict, output_dir=Path(tmp_dir_path))

        # gt_watcher = eventlet.spawn(read_file, "logfile_path", simulation_id, task_id, update_key)

        monitoring_process = None
        if update_key is not None and simulation_id is not None:
            monitoring_process = Process(
                target=read_file,
                args=(Path(tmp_dir_path) / "shieldhit_{:04d}.log".format(task_id), simulation_id, str(task_id), update_key))
            monitoring_process.start()
            logging.info("Started monitoring process for task %d", task_id)
        else:
            logging.info("No monitoring processes started for task %d", task_id)

        logging.info("Running SHIELDHIT simulation in %s", tmp_dir_path)
        estimators_dict = run_shieldhit(dir_path=Path(tmp_dir_path), task_id=task_id)

        if update_key is not None and simulation_id is not None:
            logging.info("Joining monitoring processes for task %d", task_id)
            monitoring_process.join(timeout=5)

        if len(estimators_dict.keys()) == 0:
            logfiles = simulation_logfiles(path=Path(tmp_dir_path))
            logging.info("Simulation failed, logfiles: %s", logfiles.keys())
            send_simulation_logfiles(simulation_id=simulation_id,
                                     update_key=update_key,
                                     logfiles=logfiles)
            raise Exception

        # gt_watcher.kill()

        logging.debug("Converting simulation results to JSON")
        estimators: list = estimators_to_list(estimators_dict=estimators_dict,
                                              dir_path=Path(tmp_dir_path))

        end_time = datetime.utcnow().isoformat(sep=" ")

        send_task_update(simulation_id, task_id, update_key, {"task_state": "COMPLETED", "end_time": end_time})

        return {
            "estimators": estimators,
            "simulation_id": simulation_id,
            "update_key": update_key
        }


@celery_app.task
def merge_results(results: list[dict]) -> dict:
    """Merge results from multiple simulation's tasks"""
    logging.debug("Merging results from %d tasks", len(results))

    averaged_estimators = results[0]["estimators"]
    simulation_id = results[0].pop("simulation_id", None)
    update_key = results[0].pop("simulation_id", None)
    for i, result in enumerate(results, 1):
        if simulation_id is None:
            simulation_id = result.pop("simulation_id", None)
        if update_key is None:
            update_key = result.pop("update_key", None)

        averaged_estimators = average_estimators(averaged_estimators, result["estimators"], i)

    if not send_simulation_results(simulation_id=simulation_id,
                                   update_key=update_key,
                                   estimators=averaged_estimators):
        return {
            "estimators": averaged_estimators,
            "end_time": datetime.utcnow().isoformat(sep=" ")
        }
    return {}
