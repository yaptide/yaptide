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


def run_shieldhit(param_dict, json_to_convert):
    """Shieldhit runner"""
    input_dict = input_cfg_templ.copy()

    if json_to_convert:
        print("deepsource please be quiet for now")

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

        runner_obj = SHRunner(jobs=param_dict['jobs'],
                              keep_workspace_after_run=False,
                              output_directory=tmp_output_path)

        start_time = timeit.default_timer()
        if not runner_obj.run(settings=settings):
            return None

        elapsed = timeit.default_timer() - start_time
        print("MC simulation took {:.3f} seconds".format(elapsed))

        estimators_dict = runner_obj.get_data()

        return dummy_convert_output(estimators_dict)


def dummy_convert_output(estimators_dict):
    """Dummy function for converting simulation output to dictionary"""
    if not estimators_dict:
        return {"result": "None"}

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
            # page_dict contains the list axes and number of dimensions
            page_dict = {
                "dimensions" : page_dim,
                "axes": []
            }
            for i in range(page_dim):
                axis = page.plot_axis(i)
                axis_dict = {
                    "n": int(axis.n),
                    "min_val": float(axis.min_val),
                    "max_val": float(axis.max_val),
                    "name": str(axis.name),
                    "unit": str(axis.unit),
                    "binning": str(axis.binning),
                    "data": []
                }
                for val in axis.data:
                    axis_dict["data"].append(float(val))
                page_dict["axes"].append(axis_dict)
            estimator_dict["pages"].append(page_dict)
        result_dict["estimators"].append(estimator_dict)

    return result_dict
