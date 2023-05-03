import logging
import tempfile

from pathlib import Path
from datetime import datetime

from multiprocessing import Process

from celery.result import AsyncResult

from pymchelper.executor.options import SimulationSettings
from pymchelper.executor.runner import Runner as SHRunner

from yaptide.celery.worker import celery_app
from yaptide.utils.sim_utils import (
    pymchelper_output_to_json,
    check_and_convert_payload_to_files_dict,
    files_dict_with_adjusted_primaries,
    simulation_logfiles,
    simulation_input_files,
    write_simulation_input_files
)

from yaptide.celery.utils.utils import (
    SharedResourcesManager,
    SimulationStats,
    read_file
)


@celery_app.task(bind=True)
def run_simulation(self, payload_dict: dict):
    """Simulation runner"""
    # create temporary directory

    logging.debug("run_simulation task created with payload_dict keys: %s", payload_dict.keys())

    with tempfile.TemporaryDirectory() as tmp_dir_path:
        # we may face the situation that payload_dict has no key named `ntasks`
        # this is why we use `payload_dict.get("ntasks")` and not `payload_dict["ntasks"]`
        # `payload_dict["ntasks"]` would throw an exception if `ntasks` is missing, while
        # `payload_dict.get("ntasks")` will give us `None` if `ntasks` is missing
        # `SHRunner` will gladly accept `jobs=None`  and will allocate then max possible amount of cores

        logging.debug("starting SHRunner with ntasks = %s", payload_dict.get("ntasks"))
        logging.debug("working in temporary directory: %s", tmp_dir_path)

        runner_obj = SHRunner(jobs=payload_dict.get("ntasks"),
                              keep_workspace_after_run=True,
                              output_directory=tmp_dir_path)

        ntasks = runner_obj.jobs
        logging.debug("allocated %s jobs", ntasks)

        # digest dictionary with project data (extracted from JSON file)
        # and generate simulation input files
        files_dict = files_dict_with_adjusted_primaries(payload_dict=payload_dict)
        logging.debug("preparing the files for simulation %s", files_dict.keys())

        write_simulation_input_files(files_dict=files_dict, output_dir=Path(tmp_dir_path))

        # we assume here that the simulation executable is available in the PATH so pymchelper will discover it
        settings = SimulationSettings(input_path=tmp_dir_path,  # skipcq: PYL-W0612
                                      simulator_exec_path=None,
                                      cmdline_opts="")
        logging.debug("preparing simulation command: %s", settings)

        logs_list = [Path(tmp_dir_path) / f"run_{1+i}" / f"shieldhit_{1+i:04d}.log" for i in range(ntasks)]
        logging.debug("expecting logfiles: %s", logs_list)

        new_state_meta = {"path": tmp_dir_path, "sim_type": payload_dict["sim_type"]}
        self.update_state(state="PROGRESS", meta=new_state_meta)
        logging.debug("state updated to PROGRESS, meta: %s", new_state_meta)

        SharedResourcesManager.register('SimulationStats', SimulationStats)
        logging.debug("starting monitoring processes")

        with SharedResourcesManager() as manager:
            logging.debug("created SharedResourcesManager object")
            stats: SimulationStats = manager.SimulationStats(ntasks, self, self.request.id)
            logging.debug("created SimulationStats object for id %s", self.request.id)

            monitoring_processes = [Process(target=read_file, args=(stats, logs_list[i], i+1)) for i in range(ntasks)]
            for process in monitoring_processes:
                process.start()
            logging.debug("started %d monitoring processes", len(monitoring_processes))

            try:
                is_run_ok = runner_obj.run(settings=settings)
                if not is_run_ok:
                    raise Exception
            except Exception:  # skipcq: PYL-W0703
                logfiles = simulation_logfiles(path=Path(tmp_dir_path))
                return {"logfiles": logfiles, "input_files": files_dict}

            for process in monitoring_processes:
                process.join()

            logging.debug("final stats %s", stats)
            #final_stats = stats.to_list()

            estimators_dict: dict = runner_obj.get_data()

            result: dict = pymchelper_output_to_json(estimators_dict=estimators_dict, dir_path=Path(tmp_dir_path))

            return {
                "result": result,
                "input_json": payload_dict["sim_data"] if "metadata" in payload_dict["sim_data"] else None,
                "input_files": files_dict,
                "end_time": datetime.utcnow(),
             #   "job_tasks_status": final_stats
            }


@celery_app.task
def convert_input_files(payload_dict: dict):
    """Function converting output"""
    files_dict = check_and_convert_payload_to_files_dict(payload_dict=payload_dict)
    return {"input_files": files_dict}


@celery_app.task
def get_input_files(job_id: str) -> dict:
    """Task responsible for returning simulation input files generated by converter"""
    job = AsyncResult(id=job_id, app=celery_app)

    if job.state == "PROGRESS":
        result = {"info": "Input files"}
        input_files = simulation_input_files(job.info.get("path"))
        for key, value in input_files.items():
            result[key] = value
        return result
    return {"info": "No input present"}


@celery_app.task
def cancel_simulation(job_id: str) -> bool:
    """Task responsible for canceling simulation in progress"""
    # Currently this task does nothing because to working properly it requires changes in pymchelper
    print(job_id)
    return False
