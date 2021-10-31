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


def run_shieldhit(param_dict, json_to_conv):
    """Shieldhit runner"""
    # create temporary directory
    with tempfile.TemporaryDirectory() as tmp_output_path:

        convert_runner = ConvRunner(parser=DummmyParser(),
                                       input_data=json_to_conv,
                                       output_dir=tmp_output_path)

        convert_runner.run_parser()

        print(os.listdir(tmp_output_path))
        settings = SimulationSettings(input_path=tmp_output_path,
                                      simulator_exec_path=None,
                                      cmdline_opts='')

        runner_obj = SHRunner(jobs=param_dict['jobs'],
                              keep_workspace_after_run=False,
                              output_directory=tmp_output_path)

        start_time = timeit.default_timer()
        if not runner_obj.run(settings=settings):
            return None

        elapsed = timeit.default_timer() - start_time
        print("MC simulation took {:.3f} seconds".format(elapsed))

        estimator = runner_obj.get_data()

        return estimator['mesh_']
