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

        print(os.listdir(tmp_output_path))
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
    for estimator in estimators_dict:

        # estimator_dict contains list of pages
        estimator_dict = {
            "name" : estimator,
            "pages": []}
        for page in estimators_dict[estimator].pages:

            page_dim = page.dimension

            # handling 1 dimension page
            if page_dim == 1:
                axis = page.plot_axis(0)
                x_values = axis.data
                y_values = page.data_raw.flatten()

                # for 1 dimension page, dict contains:
                # "dimensions" indicating it is 1 dim page
                # "unit"
                # "x_y_pairs" which is list of x any y values pairs
                page_dict = {
                    "dimensions" : page_dim,
                    "unit": str(axis.unit),
                    "x_y_pairs": []
                }
                for i in range(axis.n):
                    page_dict["x_y_pairs"].append({
                        "x" : x_values[i],
                        "y" : y_values[i]
                    })
                estimator_dict["pages"].append(page_dict)
            else:
                # handlers for more dimensions aren't implemented yet
                return {"message": "Wrong dimension"}
        result_dict["estimators"].append(estimator_dict)

    return result_dict
