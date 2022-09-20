import requests

import tempfile

from pathlib import Path

from plgrid.string_templates import plgdata_get_url, plgdata_list_url

from pymchelper.input_output import fromfile

from yaptide.celery.tasks import pymchelper_output_to_json

http_plgdata = 'https://data.plgrid.pl'
hostname = 'ares'


def fetch_bdo_files(json_data: dict) -> tuple[dict, int]:
    """Function fetching result bdo files from cluster"""
    session = requests.Session()
    headers = {
        "PROXY": json_data['grid_proxy']
    }
    job_id: str = json_data['job_id'].split('.')[0]
    list_url = plgdata_list_url.format(
        http_plgdata=http_plgdata,
        hostname=hostname,
        job_id=job_id,
    )
    res: requests.Response = session.get(list_url, headers=headers)
    res_json: dict = res.json()
    estimators_dict = {}
    with tempfile.TemporaryDirectory() as tmp_dir_path:
        for ls_obj in res_json:
            if not ls_obj['is_dir']:
                filename: str = ls_obj['name']
                local_file_path = Path(tmp_dir_path, filename)
                get_url = plgdata_get_url.format(
                    http_plgdata=http_plgdata,
                    hostname=hostname,
                    job_id=job_id,
                    filename=filename
                )
                with session.get(get_url, headers=headers, stream=True) as reader:
                    reader.raise_for_status()
                    with open(local_file_path, 'wb') as writer:
                        for chunk in reader.iter_content(chunk_size=8192):
                            writer.write(chunk)

                estimators_dict[filename.split('.')[0]] = fromfile(local_file_path)

    result = pymchelper_output_to_json(estimators_dict=estimators_dict)
    return result, 200
