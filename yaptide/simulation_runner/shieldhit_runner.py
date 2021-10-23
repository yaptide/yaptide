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

input_cfg_templ = {}
input_cfg_templ['beam.dat'] = """
RNDSEED      	89736501     ! Random seed
JPART0       	2            ! Incident particle type
TMAX0      	{energy:3.6f}   0.0  ! Incident energy; (MeV/nucl)
NSTAT       {nstat:d}    -1 ! NSTAT, Step of saving
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
    R 0.0 10.0 {cyl_nr:d}
    Z 0.0 30.0 {cyl_nz:d}

Geometry Mesh
    Name MyMesh_YZ
    X -5.0  5.0    {mesh_nx:d}
    Y -5.0  5.0    {mesh_ny:d}
    Z  0.0  30.0   {mesh_nz:d}

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
    """Shieldhit runner"""
    import pymchelper

    input_dict = input_cfg_templ.copy()

    input_dict['beam.dat'] = input_dict['beam.dat'].format(
        energy=param_dict['energy'],
        nstat=param_dict['nstat']
    )

    input_dict['detect.dat'] = input_dict['detect.dat'].format(
        cyl_nr=param_dict['cyl_nr'],
        cyl_nz=param_dict['cyl_nz'],
        mesh_nx=param_dict['mesh_nx'],
        mesh_ny=param_dict['mesh_ny'],
        mesh_nz=param_dict['mesh_nz']
    )

    # create temporary directory
    with tempfile.TemporaryDirectory() as tmp_output_path:

        for config_filename in input_dict:
            abs_input_path = os.path.join(tmp_output_path, config_filename)
            with open(abs_input_path, 'w') as temp_input_file:
                temp_input_file.write(input_dict[config_filename])

        settings = SimulationSettings(input_path=tmp_output_path,
                                      simulator_exec_path=None,
                                      cmdline_opts='')

        runner_obj = Runner(jobs=param_dict['jobs'],
                            keep_workspace_after_run=False,
                            output_directory=tmp_output_path)

        start_time = timeit.default_timer()
        isRunOk = runner_obj.run(settings=settings)
        if not isRunOk:
            return None

        elapsed = timeit.default_timer() - start_time
        print("MC simulation took {:.3f} seconds".format(elapsed))

        estimator = runner_obj.get_data()

        return estimator


if __name__ == '__main__':
    sys.exit(run_shieldhit(sys.argv[1:]))
