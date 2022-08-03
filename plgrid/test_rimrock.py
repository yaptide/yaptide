import requests
import base64
import os
import time
from pathlib import Path

file_path = os.path.dirname(os.path.realpath(__file__))
grid_proxy_path = Path(file_path, 'grid_proxy')

http_rimrock_jobs = 'https://rimrock.pre.plgrid.pl/api/jobs'
http_plgdata = 'https://data.plgrid.pl'
hostname = 'ares'
folder_path = 'xDDDDD'
plguserlogin = 'plgpitrus'

with open(grid_proxy_path) as grid_proxy_file:
    grid_proxy = base64.b64encode(grid_proxy_file.read().encode('utf-8')).decode('utf-8')

session = requests.Session()
headers = {
    "PROXY": grid_proxy
}

res: requests.Response = session.get(f'{http_plgdata}/list/{hostname}/net/people/{plguserlogin}', headers=headers)
print(res.status_code)
print(res.json())
res: requests.Response = session.post(f'{http_plgdata}/mkdir/{hostname}/net/people/{plguserlogin}/{folder_path}', headers=headers)
print(res.status_code)
print(f'/net/people/{plguserlogin}/{folder_path}')
data = {
    "host": f'{hostname}.cyfronet.pl',
    "script": "#!/bin/bash\n#SBATCH -A plgccbmc11\necho hello\nexit 0"
}
res: requests.Response = session.post(http_rimrock_jobs, json=data, headers=headers)
print(res.status_code)
print(res.json())

time.sleep(4)
res: requests.Response = session.get(http_rimrock_jobs, headers=headers)
print(res.status_code)
print(res.json())

res: requests.Response = session.get(f'{http_plgdata}/list/{hostname}/net/people/{plguserlogin}/{folder_path}', headers=headers)
print(res.status_code)
print(res.json())