import argparse
import json
import math
import os
import sys
import time
import timeit

from pathlib import Path

import requests

ROOT_DIR = os.path.dirname(os.path.realpath(__file__))


class Endpoints:
    """API endpoints"""

    def __init__(self, host: str = 'localhost', port: int = 5000) -> None:
        self.http_sim_run = f'http://{host}:{port}/sh/run'
        self.http_sim_status = f'http://{host}:{port}/sh/status'
        self.http_convert = f'http://{host}:{port}/sh/convert'

        self.http_list_sims = f'http://{host}:{port}/user/simulations'
        self.http_update_user = f'http://{host}:{port}/user/update'

        self.http_auth_login = f'http://{host}:{port}/auth/login'
        self.http_auth_logout = f'http://{host}:{port}/auth/logout'

        self.http_rimrock = f'http://{host}:{port}/plgrid/jobs'
        self.http_plgdata = f'http://{host}:{port}/plgrid/data'

class YaptideTesterSession:
    """"""

    def __init__(self, login_endpoint: str, logout_endpoint: str):
        """"""
        self.session = requests.Session()
        self.timer = timeit.default_timer()
        self.login_interval = 500
        self.login_endpoint = login_endpoint
        self.logout_endpoint = logout_endpoint

    def login(self, inital_login: bool = False):
        """"""
        if timeit.default_timer() - self.timer > self.login_interval or inital_login:
            res: requests.Response = self.session.post(self.login_endpoint, json={"login_name": "admin", "password": "password"})
            if res.status_code != 202:
                res_json = res.json()
                print(res_json)
                sys.exit()

    def logout(self):
        """"""
        self.session.delete(self.logout_endpoint)

    def post(self, endpoint: str, json: dict) -> requests.Response:
        """"""
        self.login()
        return self.session.post(endpoint, json=json)

    def get(self, endpoint: str, params: dict = None) -> requests.Response:
        """"""
        self.login()
        if params:
            return self.session.get(endpoint, params=params)
        else:
            return self.session.get(endpoint)


class YaptideTester:
    """"""

    def __init__(self, host: str = 'localhost', port: int = 5000):
        self.endpoints = Endpoints(host, port)
        self.session = YaptideTesterSession(self.endpoints.http_auth_login, self.endpoints.http_auth_logout)

    def run_all(self):
        """"""
        Path(ROOT_DIR, "output").mkdir(parents=True, exist_ok=True)
        self.session.login(inital_login=True)

        print("Running simulation on rimrock")
        self.run_simulation_with_rimrock(True)
        print("Running simulation on backend")
        self.run_simulation_on_backend(True)

        self.session.logout()

    @staticmethod
    def read_input_files() -> dict:
        """Read shieldhit input files from input_files folder"""
        input_files = {}
        for filename in ['geo.dat', 'detect.dat', 'beam.dat', 'mat.dat']:
            file = Path(ROOT_DIR, 'input_files', filename)
            file.parent.mkdir(exist_ok=True, parents=True)
            with open(file, 'r') as reader:
                input_files[filename] = reader.read()
        return input_files


    def run_simulation_on_backend(self, do_monitor_job: bool = True):
        """Example client running simulation"""
        example_json = Path(ROOT_DIR, 'example.json')

        with open(example_json) as json_file:
            json_to_send = json.load(json_file)

        if do_monitor_job:
            self.run_simulation_with_json(json_to_send)

            self.run_simulation_with_files()
        else:
            sim_n = 4
            for _ in range(sim_n):
                self.run_simulation_with_files(do_monitor_job=False)
                time.sleep(5)
            self.check_backend_jobs(sim_n=sim_n, page_size=2)


    def run_simulation_with_json(self, json_to_send, do_monitor_job: bool = True):
        """Example function running simulation with JSON"""
        res: requests.Response = self.session.post(self.endpoints.http_sim_run, json=json_to_send)

        task_id: str = ""
        data: dict = res.json()
        print(data)
        task_id = data.get('task_id')

        if task_id != "":
            while do_monitor_job:
                time.sleep(5)
                try:
                    res: requests.Response = self.session.post(self.endpoints.http_sim_status, json={'task_id': task_id})
                    data: dict = res.json()

                    # the request has succeeded, we can access its contents
                    if res.status_code == 200:
                        if data.get('result'):
                            with open(Path(ROOT_DIR, 'output', 'simulation_output.json'), 'w') as writer:
                                data_to_write = str(data['result'])
                                data_to_write = data_to_write.replace("'", "\"")
                                writer.write(data_to_write)
                            return
                        if data.get('logfile'):
                            with open(Path(ROOT_DIR, 'output', 'error_full_output.json'), 'w') as writer:
                                data_to_write = str(data)
                                data_to_write = data_to_write.replace("'", "\"")
                                writer.write(data_to_write)
                            with open(Path(ROOT_DIR, 'output', 'shieldlog.log'), 'w') as writer:
                                writer.write(data['logfile'])
                            for key, value in data['input_files'].items():
                                with open(Path(ROOT_DIR, 'output', key), 'w') as writer:
                                    writer.write(value)
                            return
                        if data.get('error'):
                            print(data.get('error'))
                            return

                except Exception as e:  # skipcq: PYL-W0703
                    print(e)


    def run_simulation_with_files(self, do_monitor_job: bool = True):
        """Example function running simulation with input files"""
        input_files = self.read_input_files()

        res: requests.Response = self.session.post(self.endpoints.http_sim_run, json={'input_files': input_files})
        data: dict = res.json()
        print(data)

        task_id: str = data.get('task_id')

        if task_id is not None:
            while do_monitor_job:
                time.sleep(5)
                try:
                    res: requests.Response = self.session.post(self.endpoints.http_sim_status, json={'task_id': task_id})
                    data: dict = res.json()

                    # the request has succeeded, we can access its contents
                    if res.status_code == 200:
                        if data.get('result'):
                            with open(Path(ROOT_DIR, 'output', 'simulation_output.json'), 'w') as writer:
                                data_to_write = str(data['result'])
                                data_to_write = data_to_write.replace("'", "\"")
                                writer.write(data_to_write)
                            return
                        if data.get('logfile'):
                            with open(Path(ROOT_DIR, 'output', 'error_full_output.json'), 'w') as writer:
                                data_to_write = str(data)
                                data_to_write = data_to_write.replace("'", "\"")
                                writer.write(data_to_write)
                            with open(Path(ROOT_DIR, 'output', 'shieldlog.log'), 'w') as writer:
                                writer.write(data['logfile'])
                            for key, value in data['input_files'].items():
                                with open(Path(ROOT_DIR, 'output', key), 'w') as writer:
                                    writer.write(value)
                            return
                        if data.get('error'):
                            print(data.get('error'))
                            return

                except Exception as e:  # skipcq: PYL-W0703
                    print(e)


    def check_backend_jobs(self, sim_n: int, page_size: int):
        """Example checking backend jobs with pagination"""
        are_all_finished = False
        one_last_run = True
        while not are_all_finished and one_last_run:
            some_still_running = False
            for i in range(math.ceil(sim_n/page_size)):
                time.sleep(5)
                res: requests.Response = self.session.get(self.endpoints.http_list_sims, params={
                    "page_size": page_size,
                    "page_idx": i,
                    "order_by": "start_time",
                    "order_type": "descend",
                })
                res_json: dict = res.json()
                for sim in res_json['simulations']:
                    print(sim)
                    task_id = sim['task_id']
                    res: requests.Response = self.session.post(self.endpoints.http_sim_status, json={'task_id': task_id})
                    res_json: dict = res.json()
                    if "result" not in res_json and not some_still_running:
                        some_still_running = True
            one_last_run = not are_all_finished
            are_all_finished = not some_still_running


    def run_simulation_with_rimrock(self, do_monitor_job: bool = True):
        """Example function running simulation on rimrock"""
        input_files = self.read_input_files()
        res: requests.Response = self.session.post(self.endpoints.http_rimrock, json=input_files)
        res_json: dict = res.json()
        print(res_json)
        if res.status_code != 201:
            return

        job_id: str = res_json.get('job_id')
        if job_id is not None:
            while do_monitor_job:
                time.sleep(5)
                res: requests.Response = self.session.get(self.endpoints.http_rimrock, params={"job_id": job_id})
                res_json = res.json()
                print(res_json)
                if res.status_code != 200:
                    return
                if res_json['status'] == 'FINISHED':
                    self.get_slurm_results(job_id=job_id)
                    return


    def check_rimrock_jobs(self):
        """Example function cehcking rimrock jobs' statuses"""
        res: requests.Response = self.session.get(self.endpoints.http_rimrock)
        res_json = res.json()
        print(res_json)


    def get_slurm_results(self, job_id: str):
        """Example function getting slurm results"""
        res: requests.Response = self.session.get(self.endpoints.http_plgdata, params={"job_id": job_id})
        res_json = res.json()
        path = Path(ROOT_DIR, 'output', f'{job_id.split(".")[0]}.json')
        with open(path, 'w') as writer:
            data_to_write = str(res_json['result'])
            data_to_write = data_to_write.replace("'", "\"")
            writer.write(data_to_write)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', help='backend port', default=5000, type=int)
    args = parser.parse_args()

    tester = YaptideTester(port=args.port)
    tester.run_all()
