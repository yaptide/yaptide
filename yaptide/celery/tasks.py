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
from ..converter.converter.api import get_parser_from_str, run_parser  # skipcq: FLK-E402


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

        self.update_state(state="PROGRESS", meta={"path": tmp_dir_path})
        is_run_ok = runner_obj.run(settings=settings)
        if not is_run_ok:
            self.update_state(state=states.FAILURE)
            raise celery_exceptions.TaskError

        estimators_dict: dict = runner_obj.get_data()

        result: dict = dummy_convert_output(estimators_dict)

        return {'status': 'COMPLETED', 'result': result}


def dummy_convert_output(estimators_dict: dict) -> dict:
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

        page: Page   # type is still marked as Never
        for page in estimator.pages:
            # currently we are handling for sure only 1-D results
            # 0-D and 2-D results aren't tested yet, due to testing problems

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
            # currently output is returned only when dimension == 1 due to
            # problems in efficient testing of other dimensions
            if page.dimension == 0:
                page_dict['data']['values'] = page.data_raw[0]

            elif page.dimension == 1:
                page_dict['data']['values'] = page.data_raw.tolist()

                axis: MeshAxis = page.plot_axis(0)
                page_dict['first_axis'] = {
                    'unit': str(axis.unit),
                    'name': str(axis.name),
                    'values': axis.data.tolist(),
                }

            elif page.dimension == 2:
                page_dict['data']['values'] = page.data_raw.tolist()

                axis: MeshAxis = page.plot_axis(0)
                page_dict['first_axis'] = {
                    'unit': str(axis.unit),
                    'name': str(axis.name),
                    'values': axis.data.tolist(),
                }
                axis: MeshAxis = page.plot_axis(1)
                page_dict['second_axis'] = {
                    'unit': str(axis.unit),
                    'name': str(axis.name),
                    'values': axis.data.tolist(),
                }

            else:
                # Add info about the location of the file containging to many dimensions
                raise ValueError(f'Invalid number of pages {page.dimensions}')

            est_dict['pages'].append(page_dict)
        result_dict['estimators'].append(est_dict)

    return result_dict


@celery_app.task
def simulation_task_status(task_id: str) -> dict:
    """Task responsible for returning simulation status"""
    task = AsyncResult(id=task_id, app=celery_app)

    result = {
        'status': 'OK',
        'message': {
            'state': task.state
        }
    }
    if task.state == "PENDING":
        result['message']['status'] = 'Pending...'
    elif task.state == "PROGRESS":
        result['message']['status'] = 'Calculations in progress...'
        sim_info = sim_status_from_logfile(path_to_file=os.path.join(
            task.info.get('path'), 'run_1', 'shieldhit0001.log'))
        result['message']['info'] = sim_info
    elif task.state != 'FAILURE':
        result['message']['status'] = task.info.get('status', '')
        if 'result' in task.info:
            result['message']['result'] = task.info.get('result')
    else:
        result['status'] = 'ERROR'
        result['message']['status'] = str(task.info)

    return result


def sim_status_from_logfile(path_to_file: str):
    """Extracts current simulation state from simulation logfile"""
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

        splited = last_result_line.split()
        sim_info = {
            'simulated_primaries': splited[3],
            'estimated': {
                'hours': splited[5],
                'minutes': splited[7],
                'seconds': splited[9],
            }
        }
        return sim_info
