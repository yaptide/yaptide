#!/usr/bin/env python

import os
import logging
import sys
import argparse
import timeit

from pymchelper.executor.options import SimulationSettings
from pymchelper.executor.runner import OutputDataType, Runner
from pymchelper.writers.plots import PlotDataWriter, ImageWriter


def main(args=None):
    import pymchelper

    hardcode_inputpath = '/home/pitrus/workspaces/pymchelper_2709/pymchelper/runner_example/'
    hardcode_simulator_exec_path = '/home/shared/shieldhit/shieldhit'
    hardcode_cmdline_opts = ''
    hardcode_jobs = 12
    hardcode_outputpath = '/home/pitrus/workspaces/pymchelper_2709/pymchelper/output'

    settings = SimulationSettings(input_path=hardcode_inputpath,
                                  simulator_exec_path=hardcode_simulator_exec_path,
                                  cmdline_opts=hardcode_cmdline_opts)

    # create runner object based on MC options and dedicated parallel jobs number
    # note that runner object is only created here, no simulation is started at this point
    # and no directories are being created
    runner_obj = Runner(jobs=hardcode_jobs, settings=settings)

    # start parallel execution of MC simulation
    # temporary directories needed for parallel execution as well as the output are being saved in `outdir`
    # in case of successful execution this would return list of temporary workspaces directories
    # containing partial results from simultaneous parallel executions
    start_time = timeit.default_timer()
    workspaces = runner_obj.run(output_directory=hardcode_outputpath)
    elapsed = timeit.default_timer() - start_time
    print("MC simulation took {:.3f} seconds".format(elapsed))

    # if simulation was successful proceed to data extraction by combining partial results from simultaneous executions
    # each simulation can produce multiple files
    # results are stored in a dictionary (`data_dict`) with keys being filenames
    # and values being pymchelper `Estimator` objects (which keep i.e. numpy arrays with results)
    data_dict = runner_obj.get_data(hardcode_outputpath)
    
    runner_obj.clean(workspaces)

    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
