#!/usr/bin/env python

import os
import logging
import sys
import argparse
import timeit
import shutil
import tempfile
import pathlib

from pymchelper.executor.options import SimulationSettings
from pymchelper.executor.runner import Runner as SHRunner

from ..converter.converter.converter import DummmyParser
from ..converter.converter.converter import Runner as ConvRunner


def run_shieldhit(param_dict, raw_input_dict):
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

        start_time = timeit.default_timer()

        isRunOk = runner_obj.run(settings=settings)
        if not isRunOk:
            return None

        elapsed = timeit.default_timer() - start_time
        print("MC simulation took {:.3f} seconds".format(elapsed))

        estimators_dict = runner_obj.get_data()

        return dummy_convert_output(estimators_dict)


def dummy_convert_output(estimators_dict):
    """Dummy function for converting simulation output to dictionary"""
    if not estimators_dict:
        return {"message": "No estimators"}

    # result_dict is the dictionary object, which is later converted to json
    # to provide readable api response for fronted

    # result_dict contains the list of estimators
    result_dict = {"estimators": []}
    for estimator_name, estimator_obj in estimators_dict.items():

        # est_dict contains list of pages
        est_dict = {
            "name" : estimator_name,
            "pages": []}
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
                axis = page.plot_axis(0)
                page_dict["first_axis"] = {
                    "unit": str(axis.unit),
                    "name": str(axis.name),
                    "values": axis.data.tolist()
                }
            # if page.dimension > 0:
            # if page.dimension > 1:
            #     axis = page.plot_axis(1)
            #     page_dict["second_axis"] = {
            #         "unit": str(axis.unit),
            #         "name": str(axis.name),
            #         "values": axis.data.tolist()
            #     }

            est_dict["pages"].append(page_dict)
        result_dict["estimators"].append(est_dict)

    return result_dict
