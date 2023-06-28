import logging
import os
import subprocess
import tempfile
from datetime import datetime
from multiprocessing import Process
from pathlib import Path

import eventlet
from pymchelper.executor.options import SimulationSettings
from pymchelper.executor.runner import Runner as SHRunner
from yaptide.admin.simulators import SimulatorType, install_simulator

from yaptide.celery.utils.utils import (read_file, send_simulation_results, send_task_update,
                                        send_simulation_logfiles, run_single_shieldhit)
from yaptide.celery.worker import celery_app
from yaptide.utils.sim_utils import (check_and_convert_payload_to_files_dict, pymchelper_output_to_json,
                                     simulation_logfiles, write_simulation_input_files)  # skipcq: FLK-E101


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


@celery_app.task(bind=True)
def run_simulation(self, payload_dict: dict, files_dict: dict,
                   update_key: str = None, simulation_id: int = None) -> dict:
    """
    Simulation runner
    `payload_dict` parameter holds all the data needed to run the simulation
    `update_key` and `simulation_id` parameters are required for monitoring purposes
    If one or both of them are missing, monitoring will not be performed
    """
    result = {}
    logging.getLogger(__name__).setLevel(logging.WARNING)
    logging.debug("run_simulation task created with payload_dict keys: %s", payload_dict.keys())

    with tempfile.TemporaryDirectory() as tmp_dir_path:
        # digest dictionary with project data (extracted from JSON file)
        # and generate simulation input files
        logging.debug("preparing the files for simulation %s", files_dict.keys())

        write_simulation_input_files(files_dict=files_dict, output_dir=Path(tmp_dir_path))

        # we assume here that the simulation executable is available in the PATH so pymchelper will discover it
        logging.debug("PATH is: %s", os.environ["PATH"])
        settings = SimulationSettings(
            input_path=tmp_dir_path,  # skipcq: PYL-W0612
            simulator_exec_path=None,
            cmdline_opts="")
        logging.debug("preparing simulation command: %s", settings)

        # we may face the situation that payload_dict has no key named `ntasks`
        # this is why we use `payload_dict.get("ntasks")` and not `payload_dict["ntasks"]`
        # `payload_dict["ntasks"]` would throw an exception if `ntasks` is missing, while
        # `payload_dict.get("ntasks")` will give us `None` if `ntasks` is missing
        # `SHRunner` will gladly accept `jobs=None`  and will allocate then max possible amount of cores
        logging.debug("starting SHRunner with ntasks = %s", payload_dict.get("ntasks"))
        logging.debug("working in temporary directory: %s", tmp_dir_path)

        runner_obj = SHRunner(settings=settings,
                              jobs=payload_dict.get("ntasks"),
                              keep_workspace_after_run=True,
                              output_directory=tmp_dir_path)

        ntasks = runner_obj.jobs
        logging.debug("allocated %s jobs", ntasks)

        logs_list = [Path(tmp_dir_path) / f"run_{1+i}" / f"shieldhit_{1+i:04d}.log" for i in range(ntasks)]
        logging.debug("expecting logfiles: %s", logs_list)

        new_state_meta = {"path": tmp_dir_path, "sim_type": payload_dict["sim_type"]}
        self.update_state(state="PROGRESS", meta=new_state_meta)
        logging.debug("state updated to PROGRESS, meta: %s", new_state_meta)

        monitoring_processes = []
        if update_key is not None and simulation_id is not None:
            logging.debug("starting monitoring processes")
            monitoring_processes = [Process(
                target=read_file,
                args=(logs_list[i], simulation_id, f"{self.request.id}_{i+1}", update_key)) for i in range(ntasks)]
            for process in monitoring_processes:
                process.start()
            logging.debug("started %d monitoring processes", len(monitoring_processes))
        else:
            logging.debug("no monitoring processes started")

        try:
            logging.debug("starting simulation")
            is_run_ok = runner_obj.run()

            if update_key is not None and simulation_id is not None:
                logging.debug("joining monitoring processes")
                for process in monitoring_processes:
                    process.join()

            if not is_run_ok:
                raise Exception
            logging.debug("simulation finished")
        except Exception:  # skipcq: PYL-W0703
            logfiles = simulation_logfiles(path=Path(tmp_dir_path))
            logging.info("simulation failed, logfiles: %s", logfiles.keys())
            send_simulation_logfiles(simulation_id=simulation_id,
                                     update_key=update_key,
                                     logfiles=logfiles)
            raise Exception

        logging.debug("getting simulation results")
        estimators_dict: dict = runner_obj.get_data()

        logging.debug("converting simulation results to JSON")
        simulation_result: dict = pymchelper_output_to_json(estimators_dict=estimators_dict,
                                                            dir_path=Path(tmp_dir_path))

        if not send_simulation_results(simulation_id=simulation_id,
                                       update_key=update_key,
                                       estimators=simulation_result):
            result["result"] = simulation_result
        result["end_time"] = datetime.utcnow().isoformat(sep=" ")
        logging.debug("simulation result keys: %s", result.keys())

        return result


@celery_app.task
def convert_input_files(payload_dict: dict) -> dict:
    """Function converting output"""
    files_dict = check_and_convert_payload_to_files_dict(payload_dict=payload_dict)
    return {"input_files": files_dict}


@celery_app.task(bind=True)
def run_single_simulation(self, files_dict: dict, update_key: str = None, simulation_id: int = None) -> dict:
    """Function running single shieldhit simulation"""
    task_id = self.request.id

    with tempfile.TemporaryDirectory() as tmp_dir_path:
        logging.debug("Task %s saves the files for simulation %s", task_id ,files_dict.keys())
        write_simulation_input_files(files_dict=files_dict, output_dir=Path(tmp_dir_path))

        # gt_watcher = eventlet.spawn(read_file, "logfile_path", simulation_id, task_id, update_key)

        runner_obj = SHRunner(jobs=1,
                              keep_workspace_after_run=True,
                              output_directory=tmp_dir_path)

        settings = SimulationSettings(input_path=tmp_dir_path,  # skipcq: PYL-W0612
                                      simulator_exec_path=None,
                                      cmdline_opts="")

        monitoring_process = None
        if update_key is not None and simulation_id is not None:
            logging.debug("starting monitoring processes")
            monitoring_process = Process(
                target=read_file,
                args=(Path(tmp_dir_path) / "shieldhit.log", simulation_id, task_id, update_key))
            monitoring_process.start()
            logging.debug("started monitoring process")
        else:
            logging.debug("no monitoring processes started")

        try:
            logging.debug("starting simulation")
            is_run_ok = runner_obj.run(settings=settings)

            if update_key is not None and simulation_id is not None:
                logging.debug("joining monitoring processes")
                monitoring_process.join()

            if not is_run_ok:
                raise Exception
            logging.debug("simulation finished")
        except Exception:  # skipcq: PYL-W0703
            logfiles = simulation_logfiles(path=Path(tmp_dir_path))
            logging.info("simulation failed, logfiles: %s", logfiles.keys())
            send_simulation_logfiles(simulation_id=simulation_id,
                                     update_key=update_key,
                                     logfiles=logfiles)
            raise Exception

        # gt_watcher.kill()

        logging.debug("getting simulation results")
        estimators_dict: dict = runner_obj.get_data()

        logging.debug("converting simulation results to JSON")
        simulation_result: dict = pymchelper_output_to_json(estimators_dict=estimators_dict,
                                                            dir_path=Path(tmp_dir_path))

        result = {}

        if not send_simulation_results(simulation_id=simulation_id,
                                       update_key=update_key,
                                       estimators=simulation_result):
            result["result"] = simulation_result
        result["end_time"] = datetime.utcnow().isoformat(sep=" ")
        logging.debug("simulation result keys: %s", result.keys())

        send_task_update(simulation_id, task_id, update_key, result)
