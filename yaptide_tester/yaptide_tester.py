import argparse
import json as json_lib
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
    """Class supposed to wrap request.Session class with yaptide auth features"""

    def __init__(self, login_endpoint: str, logout_endpoint: str):
        """Init of a class"""
        self.session = requests.Session()
        self.timer = timeit.default_timer()
        self.login_interval = 500
        self.login_endpoint = login_endpoint
        self.logout_endpoint = logout_endpoint

    def login(self, inital_login: bool = False):
        """Function allowing to login"""
        if timeit.default_timer() - self.timer > self.login_interval or inital_login:
            res: requests.Response = self.session.\
                post(self.login_endpoint, json={"login_name": "admin", "password": "password"})
            if res.status_code != 202:
                res_json = res.json()
                print(res_json)
                sys.exit()

    def logout(self):
        """Function allowing to logout"""
        self.session.delete(self.logout_endpoint)

    def post(self, endpoint: str, json: dict) -> requests.Response:
        """Post method wrapper"""
        self.login()
        return self.session.post(endpoint, json=json)

    def get(self, endpoint: str, params: dict = None) -> requests.Response:
        """Get method wrapper"""
        self.login()
        if params:
            return self.session.get(endpoint, params=params)
        return self.session.get(endpoint)


class YaptideTester:
    """Class responsible for testing YAPTIDE backend locally by developer"""

    def __init__(self, host: str = 'localhost', port: int = 5000):
        self.endpoints = Endpoints(host, port)
        self.session = YaptideTesterSession(self.endpoints.http_auth_login, self.endpoints.http_auth_logout)

    def run_all(self, sim_n: int, do_monitor: bool):
        """Function running all important tests - might be extended in future"""
        Path(ROOT_DIR, "output").mkdir(parents=True, exist_ok=True)
        self.session.login(inital_login=True)

        print(f'\n\nRunning {sim_n} simulation{"s" if sim_n > 1 else ""} on backend with files\n\n')
        for _ in range(sim_n):
            self.run_simulation_on_backend(True, do_monitor)
        print(f'\n\nRunning {sim_n} simulation{"s" if sim_n > 1 else ""} on backend with json\n\n')
        for _ in range(sim_n):
            self.run_simulation_on_backend(False, do_monitor)
        print(f'\n\nRunning {sim_n} simulation{"s" if sim_n > 1 else ""} on rimrock\n\n')
        for _ in range(sim_n):
            self.run_simulation_on_rimrock(do_monitor)
        print("\n\nRunning simulations pagination check\n\n")
        self.check_backend_jobs()

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

    def run_simulation_on_backend(self, with_files: bool, do_monitor_job: bool):
        """Example client running simulation"""
        if with_files:
            input_files = self.read_input_files()
            json_to_send = {'input_files': input_files}
        else:
            example_json = Path(ROOT_DIR, 'example.json')

            with open(example_json) as json_file:
                json_to_send = json_lib.load(json_file)

        res: requests.Response = self.session.post(self.endpoints.http_sim_run, json=json_to_send)
        res_json: dict = res.json()
        print(res_json)

        task_id: str = res_json.get('task_id')

        if task_id is not None:
            while do_monitor_job:
                time.sleep(5)
                try:
                    res: requests.Response = self.session.\
                        post(self.endpoints.http_sim_status, json={'task_id': task_id})
                    res_json: dict = res.json()

                    # the request has succeeded, we can access its contents
                    if res.status_code == 200:
                        if res_json.get('result'):
                            with open(Path(ROOT_DIR, 'output', 'simulation_output.json'), 'w') as writer:
                                data_to_write = str(res_json['result'])
                                data_to_write = data_to_write.replace("'", "\"")
                                writer.write(data_to_write)
                            return
                        print(res_json)
                        if res_json.get('logfile'):
                            with open(Path(ROOT_DIR, 'output', 'error_full_output.json'), 'w') as writer:
                                data_to_write = str(res_json)
                                data_to_write = data_to_write.replace("'", "\"")
                                writer.write(data_to_write)
                            with open(Path(ROOT_DIR, 'output', 'shieldlog.log'), 'w') as writer:
                                writer.write(res_json['logfile'])
                            for key, value in res_json['input_files'].items():
                                with open(Path(ROOT_DIR, 'output', key), 'w') as writer:
                                    writer.write(value)
                            return
                        if res_json.get('error'):
                            print(res_json.get('error'))
                            return

                except Exception as e:  # skipcq: PYL-W0703
                    print(e)

    def run_simulation_on_rimrock(self, do_monitor_job: bool):
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

    def check_backend_jobs(self):
        """Example checking backend jobs with pagination"""
        order_by = "start_time"
        order_type = "descend"
        res: requests.Response = self.session.get(self.endpoints.http_list_sims, params={
                "order_by": order_by,
                "order_type": order_type,
            })
        res_json: dict = res.json()
        if res.status_code != 200:
            print(res_json)
            return
        simulations_count = res_json["simulations_count"]
        print(f"Number of user simulations in database: {simulations_count}")
        page_size = int(math.sqrt(simulations_count))
        for i in range(math.ceil(simulations_count/page_size)):
            res: requests.Response = self.session.get(self.endpoints.http_list_sims, params={
                "page_size": page_size,
                "page_idx": i,
                "order_by": order_by,
                "order_type": order_type,
            })
            res_json: dict = res.json()
            for sim in res_json['simulations']:
                print(sim)
                id_type = 'task_id' if sim['platform'] == 'CELERY' else 'job_id'
                res: requests.Response = self.session.\
                    post(self.endpoints.http_sim_status, json={id_type: sim[id_type]})
                res_json: dict = res.json()

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
    parser.add_argument('--sim_n', help='number of simulations to run for each type', default=1, type=int)
    parser.add_argument('--do_monitor', action='store_true')
    parser.add_argument('--no-do_monitor', dest='do_monitor', action='store_false')
    parser.set_defaults(do_monitor=False)
    args = parser.parse_args()

    tester = YaptideTester(port=args.port)
    tester.run_all(sim_n=args.sim_n, do_monitor=args.do_monitor)
