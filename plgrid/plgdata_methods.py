import requests
import os
from pathlib import Path
import sys
import tempfile

http_plgdata = 'https://data.plgrid.pl'


# def save_files_locally(files_dict: dict, dir_path: str):
#     """Function used to save files from dict"""
#     for key in files_dict:
#         with open(Path(dir_path, key), 'w') as writer:
#             writer.write(files_dict[key])


# def send_simulation_files(json_data: dict):
#     """"""
#     files_dict = {
#         "beam.dat": json_data['beam.dat'],
#         "detect.dat": json_data['detect.dat'],
#         "geo.dat": json_data['geo.dat'],
#         "mat.dat": json_data['mat.dat']
#     }
#     with tempfile.TemporaryDirectory() as tmp_dir_path:
#         save_files_locally(files_dict, tmp_dir_path)
#         session = requests.Session()
#         for key in files_dict:
#             with open(Path(tmp_dir_path, key), 'rb') as file:
#                 res: requests.Response = session.post(http_plgdata, files={key: file})
#                 try:
#                     res_json = res.json()
#                 except Exception:
#                     pass



def get_bdo_files(json_data: dict):
    """"""
