import argparse
import json as json_lib
import math
import sys
import time
import timeit
from pathlib import Path

import requests

ROOT_DIR = Path(__file__).parent.resolve()


class Endpoints:
    """API endpoints"""

    def __init__(self, host: str, port: int) -> None:
        self.http_hello = f'http://{host}:{port}'

        self.http_jobs_direct = f'http://{host}:{port}/jobs/direct'
        self.http_jobs_batch = f'http://{host}:{port}/jobs/batch'
        self.http_jobs = f'http://{host}:{port}/jobs'

        self.http_results = f'http://{host}:{port}/results'

        self.http_logfiles = f'http://{host}:{port}/logfiles'
        self.http_inputs = f'http://{host}:{port}/inputs'
        self.http_convert = f'http://{host}:{port}/convert'

        self.http_list_sims = f'http://{host}:{port}/user/simulations'
        self.http_update_user = f'http://{host}:{port}/user/update'

        self.http_auth_login = f'http://{host}:{port}/auth/login'
        self.http_auth_logout = f'http://{host}:{port}/auth/logout'


class YaptideTesterSession:
    """Class supposed to wrap request.Session class with yaptide auth features"""

    def __init__(self, login_endpoint: str, logout_endpoint: str, username: str, password: str):
        """Init of a class"""
        self.session = requests.Session()
        self.timer = timeit.default_timer()
        self.login_interval = 500
        self.login_endpoint = login_endpoint
        self.logout_endpoint = logout_endpoint
        self.username = username
        self.password = password

    def login(self, inital_login: bool = False):
        """Function allowing to login"""
        if timeit.default_timer() - self.timer > self.login_interval or inital_login:
            res: requests.Response = self.session.\
                post(self.login_endpoint, json={"username": self.username, "password": self.password})
            if res.status_code != 202:
                res_json = res.json()
                print(res_json)
                sys.exit()
            self.timer = timeit.default_timer()

    def logout(self):
        """Function allowing to logout"""
        self.session.delete(self.logout_endpoint)

    def post(self, endpoint: str, json: dict) -> requests.Response:
        """Post method wrapper"""
        self.login()
        return self.session.post(endpoint, json=json)

    def delete(self, endpoint: str, params: dict = None) -> requests.Response:
        """Delete method wrapper"""
        self.login()
        return self.session.delete(endpoint, params=params)

    def get(self, endpoint: str, params: dict = None) -> requests.Response:
        """Get method wrapper"""
        self.login()
        if params:
            return self.session.get(endpoint, params=params)
        return self.session.get(endpoint)


class YaptideTester:
    """Class responsible for testing YAPTIDE backend locally by developer"""

    def __init__(self, host: str, port: int, username: str, password: str):
        self.endpoints = Endpoints(host, port)
        self.session = YaptideTesterSession(
            self.endpoints.http_auth_login, self.endpoints.http_auth_logout, username, password)

    def run_tests(self, sim_n: int, flags: dict):  # skipcq: PY-R1000
        """Function running all important tests - might be extended in future"""
        Path(ROOT_DIR, "output").mkdir(parents=True, exist_ok=True)
        self.session.login(inital_login=True)

        if flags["all"] or (flags["test_files"] and flags["run_direct"]):
            print(f'\n\nRunning {sim_n} simulation{"s" if sim_n > 1 else ""} directly with files\n\n')
            for _ in range(sim_n):
                self.run_simulation_on_backend(True, flags["do_monitor"], True)

        if flags["all"] or (flags["test_jsons"] and flags["run_direct"]):
            print(f'\n\nRunning {sim_n} simulation{"s" if sim_n > 1 else ""} directly with json\n\n')
            for _ in range(sim_n):
                self.run_simulation_on_backend(False, flags["do_monitor"], True)

        if flags["all"] or (flags["test_files"] and flags["run_batch"]):
            print(f'\n\nRunning {sim_n} simulation{"s" if sim_n > 1 else ""} via batch with files\n\n')
            for _ in range(sim_n):
                self.run_simulation_on_backend(True, flags["do_monitor"], False)

        if flags["all"] or (flags["test_jsons"] and flags["run_batch"]):
            print(f'\n\nRunning {sim_n} simulation{"s" if sim_n > 1 else ""} via batch with json\n\n')
            for _ in range(sim_n):
                self.run_simulation_on_backend(False, flags["do_monitor"], False)

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

    def run_simulation_on_backend(self, with_files: bool, do_monitor_job: bool, direct: bool):  # skipcq: PY-R1000
        """Example client running simulation"""
        if with_files:
            input_files = self.read_input_files()
            sim_data = input_files
            input_type = "files"
            input_key = "input_files"
        else:
            example_json = Path(ROOT_DIR, 'example.json')

            with open(example_json) as json_file:
                sim_data = json_lib.load(json_file)
            input_type = "editor"
            input_key = "input_json"

        jobs_url = self.endpoints.http_jobs_direct if direct else self.endpoints.http_jobs_batch
        results_url = self.endpoints.http_results
        json_to_send = {
            "ntasks": 6,
            "input_type": input_type,
            input_key: sim_data,
            "sim_type": "shieldhit",
        }
        if not direct:
            json_to_send["batch_options"] = {
                "array_options": {
                    "time": "00:59:59",
                    "account": "plgccbmc11-cpu",
                    "partition": "plgrid",
                },
                "collect_options": {
                    "time": "00:29:59",
                    "account": "plgccbmc11-cpu",
                    "partition": "plgrid-testing",
                }
            }

        res: requests.Response = self.session.post(jobs_url, json=json_to_send)
        res_json: dict = res.json()
        print(res_json)

        job_id: str = res_json.get("job_id")

        if job_id is not None:
            while do_monitor_job:
                time.sleep(5)

                try:
                    res: requests.Response = self.session.get(self.endpoints.http_jobs, params={"job_id": job_id})
                    res_json: dict = res.json()

                    # the request has succeeded, we can access its contents
                    if res.status_code == 200:
                        if res_json.get('job_state') == "COMPLETED":
                            print("COMPLETED")
                            for i in range(2):
                                res: requests.Response = self.session.get(results_url, params={"job_id": job_id})
                                res_json: dict = res.json()
                                print(res_json["message"])
                                # we want to trigger getting results from database not celery
                                if "estimators" in res_json and i == 1:
                                    if len(job_id.split(":")) == 4:
                                        job_id = job_id.split(":")[1]  # only for file naming purpose
                                    with open(Path(ROOT_DIR, 'output', f'sim_output_{job_id}.json'), 'w') as writer:
                                        json_lib.dump({"estimators": res_json['estimators']}, writer, indent=4)
                            return
                        if res_json.get('job_state') == "FAILED":
                            print("FAILED")
                            res: requests.Response = self.session.get(
                                self.endpoints.http_logfiles, params={"job_id": job_id})
                            res_json: dict = res.json()
                            if res.status_code != 200:
                                print(res_json)
                                return
                            for key, value in res_json['logfiles'].items():
                                with open(Path(ROOT_DIR, 'output', key), 'w') as writer:
                                    writer.write(value)
                            return
                        print(res_json)
                        if res_json.get('error'):
                            return
                    else:
                        print(res_json)

                except Exception as e:  # skipcq: PYL-W0703
                    print(e)

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
                res: requests.Response = self.session.\
                    get(
                        self.endpoints.http_jobs,
                        params={"job_id": sim["job_id"]}
                    )
                res_json: dict = res.json()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', help='backend host', default="localhost", type=str)
    parser.add_argument('--port', help='backend port', default=5000, type=int)
    parser.add_argument('--username', help='user login to use for tests', default="admin", type=str)
    parser.add_argument('--password', help='user password to use for tests', default="password", type=str)
    parser.add_argument('--sim_n', help='number of simulations to run for each type', default=1, type=int)
    parser.add_argument('--do_monitor', help='orders tester to wait for simulations\' results', action='store_true')
    parser.add_argument('--test_jsons', help='orders tester to test jsons', action='store_true')
    parser.add_argument('--test_files', help='orders tester to test files', action='store_true')
    parser.add_argument('--run_direct', help='orders tester to run directly', action='store_true')
    parser.add_argument('--run_batch', help='orders tester to wait for simulations\' results', action='store_true')
    parser.add_argument('--all', help='orders tester to test everything', action='store_true')

    parser.set_defaults(do_monitor=False)
    parser.set_defaults(test_jsons=False)
    parser.set_defaults(test_files=False)
    parser.set_defaults(run_direct=False)
    parser.set_defaults(run_batch=False)
    parser.set_defaults(all=False)

    args = parser.parse_args()

    tester = YaptideTester(host=args.host, port=args.port, username=args.username, password=args.password)
    tester.run_tests(sim_n=args.sim_n, flags={
        "do_monitor": args.do_monitor,
        "test_jsons": args.test_jsons,
        "test_files": args.test_files,
        "run_direct": args.run_direct,
        "run_batch": args.run_batch,
        "all": args.all
    })
