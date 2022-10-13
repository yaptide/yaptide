import requests

import tempfile

from pathlib import Path

from pymchelper.input_output import fromfile

from plgrid.string_templates import PLGDATA_GET_URL, PLGDATA_LIST_URL
from yaptide.celery.tasks import pymchelper_output_to_json

HTTP_PLGDATA = 'https://data.plgrid.pl'
HOSTNAME = 'ares'


def fetch_bdo_files(json_data: dict) -> tuple[dict, int]:
    """
    Fetching simulation results from the cluster.
    Return a tuple with a dictionary containing results and an integer error code.
    """
    session = requests.Session()
    headers = {
        "PROXY": json_data['grid_proxy']
    }
    # job_id format: "SLURM_JOB_ID.ares.cyfronet.pl" -> folder is named with SLURM_JOB_ID only
    slurm_job_id: str = json_data['job_id'].split('.')[0]
    # construct an URL with a path to the simulation workspace directory, based on jobid
    # this path may contain many different files: simulation output (i.e. BDO files), logs and simulation output
    list_url = PLGDATA_LIST_URL.format(
        http_plgdata=HTTP_PLGDATA,
        hostname=HOSTNAME,
        slurm_job_id=slurm_job_id,
    )
    # get a list of all files and directories in the simulation workspace directory
    res: requests.Response = session.get(list_url, headers=headers)
    res_json: dict = res.json()
    estimators_dict = {}
    with tempfile.TemporaryDirectory() as tmp_dir_path:
        for ls_obj in res_json:
            if not ls_obj['is_dir']:
                filename: str = ls_obj['name']
                local_file_path = Path(tmp_dir_path, filename)
                get_url = PLGDATA_GET_URL.format(
                    http_plgdata=HTTP_PLGDATA,
                    hostname=HOSTNAME,
                    slurm_job_id=slurm_job_id,
                    filename=filename
                )
                with session.get(get_url, headers=headers, stream=True) as reader:
                    reader.raise_for_status()
                    with open(local_file_path, 'wb') as writer:
                        for chunk in reader.iter_content(chunk_size=8192):
                            writer.write(chunk)

                estimators_dict[filename.split('.')[0]] = fromfile(str(local_file_path))

    result = pymchelper_output_to_json(estimators_dict=estimators_dict)
    return {"result": result}, 200
