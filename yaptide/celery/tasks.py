from ..converter.converter.api import get_parser_from_str, run_parser  # skipcq: FLK-E402
from yaptide.celery.worker import celery_app

import os
import sys
import tempfile

from celery import states
from celery import exceptions as celery_exceptions
from celery.result import AsyncResult

from pymchelper.executor.options import SimulationSettings
from pymchelper.executor.runner import Runner as SHRunner
from pymchelper.estimator import Estimator
from pymchelper.page import Page
from pymchelper.axis import MeshAxis

# dirty hack needed to properly handle relative imports in the converter submodule
sys.path.append('yaptide/converter')


@celery_app.task(bind=True)
def run_simulation(self, param_dict: dict, raw_input_dict: dict):
    """Simulation runner"""
    # create temporary directory
    with tempfile.TemporaryDirectory() as tmp_dir_path:

        # digest dictionary with project data (extracted from JSON file)
        # and generate simulation input files
        conv_parser = get_parser_from_str(param_dict['sim_type'])
        run_parser(parser=conv_parser, input_data=raw_input_dict, output_dir=tmp_dir_path)
        # we assume here that the simulation executable is available in the PATH so pymchelper will discover it
        settings = SimulationSettings(input_path=tmp_dir_path,  # skipcq: PYL-W0612
                                      simulator_exec_path=None,
                                      cmdline_opts='')

        runner_obj = SHRunner(jobs=param_dict['jobs'],
                              keep_workspace_after_run=True,
                              output_directory=tmp_dir_path)

        self.update_state(state="PROGRESS", meta={"path": tmp_dir_path, "sim_type": param_dict['sim_type']})
        try:
            is_run_ok = runner_obj.run(settings=settings)
            if not is_run_ok:
                raise Exception
        except Exception:  # skipcq: PYL-W0703
            logfile = simulation_logfile(path=os.path.join(tmp_dir_path, 'run_1', 'shieldhit0001.log'))
            input_files = simulation_input_files(path=tmp_dir_path)
            return {'logfile': logfile, 'input_files': input_files}

        estimators_dict: dict = runner_obj.get_data()

        result: dict = pymchelper_output_to_json(estimators_dict)

        return {'result': result}


def pymchelper_output_to_json(estimators_dict: dict) -> dict:
    """Dummy function for converting simulation output to dictionary"""
    if not estimators_dict:
        return {'message': 'No estimators'}

    # result_dict is a dictionary, which is later converted to json
    # to provide readable API response for fronted
    # keys in results_dict are estimator names, values are the estimator objects
    result_dict = {'estimators': []}
    estimator: Estimator
    for estimator_key, estimator in estimators_dict.items():
        # est_dict contains list of pages
        est_dict = {
            'name': estimator_key,
            'pages': [],
        }

        for page in estimator.pages:
            # page_dict contains:
            # 'dimensions' indicating it is 1 dim page
            # 'data' which has unit, name and list of data values
            page_dict = {
                'dimensions': page.dimension,
                'data': {
                    'unit': str(page.unit),
                    'name': str(page.name),
                }
            }
            if page.dimension == 0:
                page_dict['data']['values'] = [page.data_raw.tolist()]
            else:
                page_dict['data']['values'] = page.data_raw.tolist()
            # currently output is returned only when dimension == 1 due to
            # problems in efficient testing of other dimensions

            if page.dimension in {1, 2}:
                axis: MeshAxis = page.plot_axis(0)
                page_dict['first_axis'] = {
                    'unit': str(axis.unit),
                    'name': str(axis.name),
                    'values': axis.data.tolist(),
                }
            if page.dimension == 2:
                axis: MeshAxis = page.plot_axis(1)
                page_dict['second_axis'] = {
                    'unit': str(axis.unit),
                    'name': str(axis.name),
                    'values': axis.data.tolist(),
                }
            if page.dimension > 2:
                # Add info about the location of the file containging to many dimensions
                raise ValueError(f'Invalid number of pages {page.dimension}')

            est_dict['pages'].append(page_dict)
        result_dict['estimators'].append(est_dict)

    return result_dict


def simulation_logfile(path: str) -> str:
    """Proto version of returning errors -> returning shieldhit.log"""
    try:
        with open(path, 'r') as reader:
            return reader.read()
    except FileNotFoundError:
        return "logfile not found"


def simulation_input_files(path: str) -> dict:
    """Function returning a dictionary with simulation input filenames as keys and their content as values"""
    result = {}
    try:
        for p in [os.path.join(path, 'geo.dat'),
                  os.path.join(path, 'detect.dat'),
                  os.path.join(path, 'beam.dat'),
                  os.path.join(path, 'mat.dat')]:
            with open(p, 'r') as reader:
                result[p.split('/')[-1]] = reader.read()
    except FileNotFoundError:
        result['info'] = "No input present"
    return result


@celery_app.task
def simulation_task_status(task_id: str) -> dict:
    """Task responsible for returning simulation status"""
    task = AsyncResult(id=task_id, app=celery_app)

    result = {
        'status': 'OK',
        'content': {
            'state': task.state,
        }
    }
    if task.state == 'PENDING':
        pass
    elif task.state == 'PROGRESS':
        if not task.info.get('sim_type') in {'shieldhit', 'sh_dummy'}:
            return result
        sim_info = sh12a_simulation_status(path_to_file=os.path.join(task.info.get('path'),
                                                                     'run_1', 'shieldhit0001.log'))
        result['content']['info'] = sim_info
    elif task.state != 'FAILURE':
        if 'result' in task.info:
            result['content']['result'] = task.info.get('result')
        elif 'logfile' in task.info:
            result['content']['state'] = 'FAILURE'
            result['content']['error'] = 'Simulation error'
            result['content']['logfile'] = task.info.get('logfile')
            result['content']['input_files'] = task.info.get('input_files')
    else:
        result['content']['error'] = str(task.info)

    return result


def sh12a_simulation_status(path_to_file: str) -> dict:
    """Extracts current SHIELD-HIT12A simulation state from first available logfile"""
    # This is dummy version because pymchelper currently doesn't privide any information about progress
    with open(path_to_file, 'r') as reader:
        found_line_which_starts_status_block = False
        last_result_line = ""
        for line in reader:
            if not found_line_which_starts_status_block:
                # We are searching for lines containing progress info
                # They are preceded by line starting with "Starting transport"
                found_line_which_starts_status_block = line.lstrip().startswith("Starting transport")
            else:
                # Searching for latest line
                if line.lstrip().startswith("Primary particle"):
                    last_result_line = line
        if last_result_line == "":
            return {'simulated_primaries': 0}
        splited = last_result_line.split()
        return {
            'simulated_primaries': splited[3],
            'estimated': {
                'hours': splited[5],
                'minutes': splited[7],
                'seconds': splited[9],
            }
        }


@celery_app.task
def get_input_files(task_id: str) -> dict:
    """Task responsible for returning simulation input files generated by converter"""
    task = AsyncResult(id=task_id, app=celery_app)

    result = {
        'info': 'Input files',
        'content': {}
    }
    if task.state == "PROGRESS":
        try:
            for path in [os.path.join(task.info.get('path'), 'geo.dat'),
                         os.path.join(task.info.get('path'), 'detect.dat'),
                         os.path.join(task.info.get('path'), 'beam.dat'),
                         os.path.join(task.info.get('path'), 'mat.dat')]:
                with open(path, 'r') as reader:
                    result['content'][path.split('/')[-1]] = reader.read()
        except FileNotFoundError:
            result['info'] = "No input present"
    else:
        result['info'] = "No input present"
    return result


@celery_app.task
def cancel_simulation(task_id: str) -> bool:
    """Task responsible for canceling simulation in progress"""
    # Currently this task does nothing because to working properly it requires changes in pymchelper
    return False
