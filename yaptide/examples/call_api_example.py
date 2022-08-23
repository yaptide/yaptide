import argparse
import json
import os
import time
import timeit
import base64
from pathlib import Path

import requests


class Endpoints:
    """API endpoints"""

    def __init__(self, host: str = 'localhost', port: int = 5000) -> None:
        self.http_sim_run = f'http://{host}:{port}/sh/run'
        self.http_sim_status = f'http://{host}:{port}/sh/status'
        self.http_list_sims = f'http://{host}:{port}/user/simulations'
        self.http_convert = f'http://{host}:{port}/sh/convert'

        self.http_auth_login = f'http://{host}:{port}/auth/login'
        self.http_auth_logout = f'http://{host}:{port}/auth/logout'

        self.http_rimrock = f'http://{host}:{port}/plgrid/jobs'


auth_json = {
    "login_name": "admin",
    "password": "password",
}


def read_input_files(example_dir: Path) -> dict:
    """Read shieldhit input files from input_files folder"""
    input_files = {}
    for filename in ['geo.dat', 'detect.dat', 'beam.dat', 'mat.dat']:
        file = Path(example_dir, 'input_files', filename)
        with open(file, 'r') as reader:
            input_files[filename] = reader.read()
    return input_files


def run_simulation_on_backend(port: int = 5000):
    """Example client running simulation"""
    example_dir = os.path.dirname(os.path.realpath(__file__))
    example_json = Path(example_dir, 'example.json')

    with open(example_json) as json_file:
        json_to_send = json.load(json_file)

    session = requests.Session()

    res: requests.Response = session.post(Endpoints(port=port).http_auth_login, json=auth_json)

    if res.status_code != 202:
        print(res.json())
        return

    run_simulation_with_json(session, example_dir, json_to_send, port=port)

    run_simulation_with_files(session, example_dir, json_to_send, port=port)

    session.delete(Endpoints(port=port).http_auth_logout)


def run_simulation_with_json(session: requests.Session, example_dir, json_to_send, port: int = 5000):
    """Example function running simulation with JSON"""
    timer = timeit.default_timer()
    res: requests.Response = session.post(Endpoints(port=port).http_sim_run, json=json_to_send)

    task_id: str = ""
    data: dict = res.json()
    print(data)
    task_id = data.get('task_id')

    res: requests.Response = session.get(Endpoints(port=port).http_list_sims)
    data: dict = res.json()
    print(data)
    if task_id != "":
        while True:
            time.sleep(5)
            # we need to relog in every 2 hours or refresh every 10 minutes
            # for just simplicity of the code we are just relogging in
            if timeit.default_timer() - timer > 500:
                res: requests.Response = session.post(Endpoints(port=port).http_auth_login, json=auth_json)
                if res.status_code != 202:
                    print(res.json())
                    return
                timer = timeit.default_timer()
            try:
                res: requests.Response = session.post(Endpoints(port=port).http_sim_status, json={'task_id': task_id})
                data: dict = res.json()

                # the request has succeeded, we can access its contents
                if res.status_code == 200:
                    if data.get('result'):
                        with open(Path(example_dir, 'output', 'simulation_output.json'), 'w') as writer:
                            data_to_write = str(data['result'])
                            data_to_write = data_to_write.replace("'", "\"")
                            writer.write(data_to_write)
                        return
                    if data.get('logfile'):
                        with open(Path(example_dir, 'output', 'error_full_output.json'), 'w') as writer:
                            data_to_write = str(data)
                            data_to_write = data_to_write.replace("'", "\"")
                            writer.write(data_to_write)
                        with open(Path(example_dir, 'output', 'shieldlog.log'), 'w') as writer:
                            writer.write(data['logfile'])
                        for key, value in data['input_files'].items():
                            with open(Path(example_dir, 'output', key), 'w') as writer:
                                writer.write(value)
                        return
                    if data.get('error'):
                        print(data.get('error'))
                        return

            except Exception as e:  # skipcq: PYL-W0703
                print(e)


def run_simulation_with_files(session: requests.Session, example_dir, json_to_send, port: int = 5000):
    """Example function running simulation with input files"""
    res: requests.Response = session.post(Endpoints(port=port).http_convert, json=json_to_send)

    data: dict = res.json()
    for key, value in data['input_files'].items():
        with open(Path(example_dir, 'output', key), 'w') as writer:
            writer.write(value)

    input_files = read_input_files(example_dir=example_dir)

    timer = timeit.default_timer()
    res: requests.Response = session.post(Endpoints(port=port).http_sim_run, json={'input_files': input_files})
    task_id: str = ""
    data: dict = res.json()
    print(data)

    task_id = data.get('task_id')

    res: requests.Response = session.get(Endpoints(port=port).http_list_sims)
    data: dict = res.json()
    print(data)
    if task_id != "":
        while True:
            time.sleep(5)
            # we need to relog in every 2 hours or refresh every 10 minutes
            # for just simplicity of the code we are just relogging in
            if timeit.default_timer() - timer > 500:
                res: requests.Response = session.post(Endpoints(port=port).http_auth_login, json=auth_json)
                if res.status_code != 202:
                    print(res.json())
                    return
                timer = timeit.default_timer()
            try:
                res: requests.Response = session.post(Endpoints(port=port).http_sim_status, json={'task_id': task_id})
                data: dict = res.json()

                # the request has succeeded, we can access its contents
                if res.status_code == 200:
                    if data.get('result'):
                        with open(Path(example_dir, 'output', 'simulation_output.json'), 'w') as writer:
                            data_to_write = str(data['result'])
                            data_to_write = data_to_write.replace("'", "\"")
                            writer.write(data_to_write)
                        return
                    if data.get('logfile'):
                        with open(Path(example_dir, 'output', 'error_full_output.json'), 'w') as writer:
                            data_to_write = str(data)
                            data_to_write = data_to_write.replace("'", "\"")
                            writer.write(data_to_write)
                        with open(Path(example_dir, 'output', 'shieldlog.log'), 'w') as writer:
                            writer.write(data['logfile'])
                        for key, value in data['input_files'].items():
                            with open(Path(example_dir, 'output', key), 'w') as writer:
                                writer.write(value)
                        return
                    if data.get('error'):
                        print(data.get('error'))
                        return

            except Exception as e:  # skipcq: PYL-W0703
                print(e)


def run_simulation_with_rimrock(port: int = 5000):
    """Example function running simulation on rimrock"""
    example_dir = os.path.dirname(os.path.realpath(__file__))
    grid_proxy_path = Path(example_dir, 'grid_proxy')
    try:
        with open(grid_proxy_path) as grid_proxy_file:
            grid_proxy = grid_proxy_file.read()
    except FileNotFoundError:
        print("Generate grid_proxy file by adjusting following command:\n")
        cmd = "read -s p && echo $p | ssh -l <plgusername> ares.cyfronet.pl "
        cmd += r'"grid-proxy-init -q -pwstdin && cat /tmp/x509up_u\`id -u\`"'
        cmd += f" > {grid_proxy_path} && unset p\n"
        print(cmd)
        return

    headers = {"PROXY": base64.b64encode(grid_proxy.encode('utf-8')).decode('utf-8')}

    session = requests.Session()
    input_files = read_input_files(example_dir=example_dir)
    res: requests.Response = session.post(Endpoints(port=port).http_rimrock, json=input_files, headers=headers)
    res_json = res.json()
    print(res_json)

    job_id: str = ""
    job_id = res_json.get('job_id')
    if job_id != "":
        while True:
            time.sleep(5)
            res: requests.Response = session.get(Endpoints(port=port).http_rimrock,
                                                 params={"job_id": job_id},
                                                 headers=headers)
            res_json = res.json()
            if res.status_code != 200:
                print(res_json)
                return
            if res_json.get('status') != 200:
                print(res_json)
                return
            print(res_json)
            if res_json.get('job_status') == 'FINISHED':
                return


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', help='backend port', default=5000, type=int)
    args = parser.parse_args()
    run_simulation_with_rimrock(port=args.port)
