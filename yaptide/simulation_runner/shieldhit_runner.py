#!/usr/bin/env python

import tempfile

from pymchelper.executor.options import SimulationSettings
from pymchelper.executor.runner import Runner as SHRunner
from pymchelper.estimator import Estimator
from pymchelper.page import Page
from pymchelper.axis import MeshAxis

from ..converter.converter.converter import DummmyParser
from ..converter.converter.converter import Runner as ConvRunner


def run_shieldhit(param_dict: dict, raw_input_dict: dict) -> dict:
    """Shieldhit runner"""
    # create temporary directory
    with tempfile.TemporaryDirectory() as tmp_output_path:

        # digest dictionary with project data (extracted from JSON file)
        # and generate SHIELD-HIT12A input files
        conv_runner = ConvRunner(parser=DummmyParser(),
                                 input_data=raw_input_dict,
                                 output_dir=tmp_output_path)

        conv_runner.run_parser()

        settings = SimulationSettings(input_path=tmp_output_path,
                                      simulator_exec_path=None,
                                      cmdline_opts='')

        runner_obj = SHRunner(jobs=param_dict['jobs'],
                              keep_workspace_after_run=False,
                              output_directory=tmp_output_path)

        isRunOk = runner_obj.run(settings=settings)
        if not isRunOk:
            return None

        estimators_dict: dict = runner_obj.get_data()

        return dummy_convert_output(estimators_dict)


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
            "name" : estimator_name,
            "pages": []}

        page: Page   # type is still marked as Never
        for page in estimator_obj.pages:

            # currently we are handling for sure only 1-D results
            # 0-D and 2-D results aren't tested yet, due to testing problems

            # page_dict contains:
            # "dimensions" indicating it is 1 dim page
            # "data" which has unit, name and list of data values
            page_dict = {
                "dimensions" : page.dimension
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
