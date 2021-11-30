from yaptide.celery.worker import celery_app

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
    with tempfile.TemporaryDirectory() as tmp_output_path:

        # digest dictionary with project data (extracted from JSON file)
        # and generate SHIELD-HIT12A input files
        conv_parser = get_parser_from_str(param_dict['sim_type'])
        run_parser(parser=conv_parser, input_data=raw_input_dict, output_dir=tmp_output_path)

        settings = SimulationSettings(input_path=tmp_output_path,  # skipcq: PYL-W0612
                                      simulator_exec_path=None,
                                      cmdline_opts='')

        runner_obj = SHRunner(jobs=param_dict['jobs'],
                              keep_workspace_after_run=False,
                              output_directory=tmp_output_path)

        isRunOk = runner_obj.run(settings=settings)
        if not isRunOk:
            self.update_state(state=states.FAILURE)
            raise celery_exceptions.TaskError

        estimators_dict: dict = runner_obj.get_data()

        result: dict = dummy_convert_output(estimators_dict)

        return {'status': 'COMPLETED', 'result': result}


def dummy_convert_output(estimators_dict: dict) -> dict:
    """Dummy function for converting simulation output to dictionary"""
    if not estimators_dict:
        return {"message": "No estimators"}

    # result_dict is the dictionary object, which is later converted to json
    # to provide readable api response for fronted

    # result_dict contains the list of estimators
    result_dict = {"estimators": []}
    estimator_obj: Estimator
    for estimator_name, estimator_obj in estimators_dict.items():

        # est_dict contains list of pages
        est_dict = {
            "name": estimator_name,
            "pages": []}

        page: Page   # type is still marked as Never
        for page in estimator_obj.pages:

            # currently we are handling for sure only 1-D results
            # 0-D and 2-D results aren't tested yet, due to testing problems

            # page_dict contains:
            # "dimensions" indicating it is 1 dim page
            # "data" which has unit, name and list of data values
            page_dict = {
                "dimensions": page.dimension
            }
            # currently output is returned only when dimension == 1 due to
            # problems in efficient testing of other dimensions
            if page.dimension == 1:
                page_dict["data"] = {
                    "unit": str(page.unit),
                    "name": str(page.name),
                    "values": page.data_raw.flatten().tolist()
                }
                axis: MeshAxis = page.plot_axis(0)
                page_dict["first_axis"] = {
                    "unit": str(axis.unit),
                    "name": str(axis.name),
                    "values": axis.data.tolist()
                }

            est_dict["pages"].append(page_dict)
        result_dict["estimators"].append(est_dict)

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
    elif task.state != 'FAILURE':
        result['message']['status'] = task.info.get('status', '')
        if 'result' in task.info:
            result['message']['result'] = task.info.get('result')
    else:
        result['status'] = 'ERROR'
        result['message']['status'] = str(task.info)

    return result
