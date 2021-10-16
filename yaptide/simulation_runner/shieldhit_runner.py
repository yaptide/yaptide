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
from pymchelper.executor.runner import OutputDataType, Runner
from pymchelper.writers.plots import PlotDataWriter, ImageWriter

input_cfg_templ = {}
input_cfg_templ['beam.dat'] = """
RNDSEED      	89736501     ! Random seed
JPART0       	2            ! Incident particle type
TMAX0      	{energy:3.6f}   0.0  ! Incident energy; (MeV/nucl)
NSTAT           1000    -1 ! NSTAT, Step of saving
STRAGG          2            ! Straggling: 0-Off 1-Gauss, 2-Vavilov
MSCAT           2            ! Mult. scatt 0-Off 1-Gauss, 2-Moliere
NUCRE           0            ! Nucl.Reac. switcher: 1-ON, 0-OFF
"""
input_cfg_templ['mat.dat'] = """
MEDIUM 1
ICRU 276
END
"""
input_cfg_templ['detect.dat'] = """
Geometry Cyl
    Name ScoringCylinder
        R 0.0 10.0 1
        Z 0.0 30.0 3000
Output
    Filename mesh.bdo
    Geo ScoringCylinder
    Quantity Dose
"""
input_cfg_templ['geo.dat'] = """
*---><---><--------><------------------------------------------------>
    0    0           protons, H2O 30 cm cylinder, r=10, 1 zone
*---><---><--------><--------><--------><--------><--------><-------->
  RCC    1       0.0       0.0       0.0       0.0       0.0      30.0
                10.0
  RCC    2       0.0       0.0      -5.0       0.0       0.0      35.0
                15.0
  RCC    3       0.0       0.0     -10.0       0.0       0.0      40.0
                20.0
  END
  001          +1
  002          +2     -1
  003          +3     -2
  END
* material codes: 1 - liquid water (ICRU material no 276), 1000 - vacuum, 0 - black body
    1    2    3
    1 1000    0
"""


def run_shieldhit(param_dict):
    import pymchelper

    input_dict = input_cfg_templ.copy()
    # TODO: change energy to parsed argument
    input_dict['beam.dat'] = input_dict['beam.dat'].format(energy=param_dict['energy'])

    # create temporary directory 
    tmp_output_directory_path = tempfile.mkdtemp()

    for config_filename in input_dict:
        absolute_path_temp_input_file = os.path.join(tmp_output_directory_path, config_filename)
        with open(absolute_path_temp_input_file, 'w') as temp_input_file:
            temp_input_file.write(input_dict[config_filename])

    # path to example input
    # example_inputpath = str(pathlib.Path().resolve())+"\\runner_example"
    

    # TODO: remove hardcoded path -> load from env
    hardcode_simulator_exec_path = '/home/ubuntu/shield_hit12a_x86_64_demo_gfortran_v0.9.2/bin/shieldhit'

    settings = SimulationSettings(input_path=tmp_output_directory_path,
                                  simulator_exec_path=hardcode_simulator_exec_path,
                                  cmdline_opts='')

    # create runner object based on MC options and dedicated parallel jobs number
    # note that runner object is only created here, no simulation is started at this point
    # and no directories are being created
    runner_obj = Runner(jobs=param_dict['jobs'], keep_workspace_after_run=False, output_directory=tmp_output_directory_path)

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
