#!/usr/bin/env python

import os
import logging
import sys
import argparse
import timeit
import shutil
import tempfile

from pymchelper.executor.options import SimulationSettings
from pymchelper.executor.runner import OutputDataType, Runner
from pymchelper.writers.plots import PlotDataWriter, ImageWriter


def run_shieldhit(args=None):
    import pymchelper

    # hardcoded path on ubuntu
    hardcode_inputpath = '/home/ubuntu/shield_hit12a_x86_64_demo_gfortran_v0.9.2/examples/simple'
    # alternative hardcoded path on ubuntu
    # hardcode_inputpath = '/home/ubuntu/yaptide/pymchelper_example/runner_example'

    # hardcoded path on ubuntu
    hardcode_simulator_exec_path = '/home/ubuntu/shield_hit12a_x86_64_demo_gfortran_v0.9.2/bin/shieldhit'
    hardcode_cmdline_opts = ''
    hardcode_jobs = 12

    # hardcoded path on ubuntu
    tmp_output_directory_path = tempfile.mkdtemp()

    settings = SimulationSettings(input_path=hardcode_inputpath,
                                  simulator_exec_path=hardcode_simulator_exec_path,
                                  cmdline_opts=hardcode_cmdline_opts)

    # create runner object based on MC options and dedicated parallel jobs number
    # note that runner object is only created here, no simulation is started at this point
    # and no directories are being created
    runner_obj = Runner(jobs=hardcode_jobs, keep_workspace_after_run=False, output_directory=tmp_output_directory_path)

    # start parallel execution of MC simulation
    # temporary directories needed for parallel execution as well as the output are being saved in `outdir`
    # in case of successful execution this would return list of temporary workspaces directories
    # containing partial results from simultaneous parallel executions
    start_time = timeit.default_timer()
    isRunOk = runner_obj.run(settings=settings)
    elapsed = timeit.default_timer() - start_time
    print("MC simulation took {:.3f} seconds".format(elapsed))

    # if simulation was successful proceed to data extraction by combining partial results from simultaneous executions
    # each simulation can produce multiple files
    # results are stored in a dictionary (`data_dict`) with keys being filenames
    # and values being pymchelper `Estimator` objects (which keep i.e. numpy arrays with results)
    data_dict = runner_obj.get_data()
    
    # runner_obj.clean()

    shutil.rmtree(tmp_output_directory_path)

    return data_dict


if __name__ == '__main__':
    sys.exit(run_shieldhit(sys.argv[1:]))
