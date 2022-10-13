import requests
import base64
import os
import time
from pathlib import Path

file_path = os.path.dirname(os.path.realpath(__file__))
grid_proxy_path = Path(file_path, 'grid_proxy')

HTTP_RIMROCK_JOBS = 'https://rimrock.pre.plgrid.pl/api/jobs'
HTTP_PLGDATA = 'https://data.plgrid.pl'
HOSTNAME = 'ares'
folder_path = 'xDDDDD'

with open(grid_proxy_path) as grid_proxy_file:
    grid_proxy = base64.b64encode(grid_proxy_file.read().encode('utf-8')).decode('utf-8')

session = requests.Session()
headers = {
    "PROXY": grid_proxy
}

res: requests.Response = session.get(f'{HTTP_PLGDATA}/list/{HOSTNAME}/~/', headers=headers)
print(res.status_code)
print(res.json())
res: requests.Response = session.post(f'{HTTP_PLGDATA}/mkdir/{HOSTNAME}/~/{folder_path}', headers=headers)
print(res.status_code)
print(f'/~/{folder_path}')
data = {
    "host": f'{HOSTNAME}.cyfronet.pl',
    "script": "#!/bin/bash\n#SBATCH -A plgccbmc11\necho hello\nexit 0"
}
res: requests.Response = session.post(HTTP_RIMROCK_JOBS, json=data, headers=headers)
print(res.status_code)
print(res.json())

time.sleep(4)
res: requests.Response = session.get(HTTP_RIMROCK_JOBS, headers=headers)
print(res.status_code)
print(res.json())

res: requests.Response = session.get(f'{HTTP_PLGDATA}/list/{HOSTNAME}/~/{folder_path}', headers=headers)
print(res.status_code)
print(res.json())