import argparse
import json
import math
import os
import time
import timeit

from pathlib import Path

import requests


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


AUTH_JSON = {
    "login_name": "admin",
    "password": "password",
}
EXAMPLE_DIR = os.path.dirname(os.path.realpath(__file__))


def read_input_files() -> dict:
    """Read shieldhit input files from input_files folder"""
    input_files = {}
    for filename in ['geo.dat', 'detect.dat', 'beam.dat', 'mat.dat']:
        file = Path(EXAMPLE_DIR, 'input_files', filename)
        with open(file, 'r') as reader:
            input_files[filename] = reader.read()
    return input_files


def run_simulation_on_backend(session: requests.Session, port: int = 5000, do_monitor_job: bool = True):
    """Example client running simulation"""
    example_json = Path(EXAMPLE_DIR, 'example.json')

    with open(example_json) as json_file:
        json_to_send = json.load(json_file)

    res: requests.Response = session.post(Endpoints(port=port).http_auth_login, json=AUTH_JSON)

    if res.status_code != 202:
        print(res.json())
        return

    if do_monitor_job:
        run_simulation_with_json(session=session, json_to_send=json_to_send, port=port)

        run_simulation_with_files(session=session, port=port)
    else:
        sim_n = 4
        for _ in range(sim_n):
            run_simulation_with_files(session=session, port=port, do_monitor_job=False)
            time.sleep(5)
        check_backend_jobs(session=session, sim_n=sim_n, page_size=2, port=port)

    session.delete(Endpoints(port=port).http_auth_logout)


def run_simulation_with_json(session: requests.Session, json_to_send, port: int = 5000, do_monitor_job: bool = True):
    """Example function running simulation with JSON"""
    timer = timeit.default_timer()
    res: requests.Response = session.post(Endpoints(port=port).http_sim_run, json=json_to_send)

    task_id: str = ""
    data: dict = res.json()
    print(data)
    task_id = data.get('task_id')

    if task_id != "":
        while do_monitor_job:
            time.sleep(5)
            # we need to relog in every 2 hours or refresh every 10 minutes
            # for just simplicity of the code we are just relogging in
            if timeit.default_timer() - timer > 500:
                res: requests.Response = session.post(Endpoints(port=port).http_auth_login, json=AUTH_JSON)
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
                        with open(Path(EXAMPLE_DIR, 'output', 'simulation_output.json'), 'w') as writer:
                            data_to_write = str(data['result'])
                            data_to_write = data_to_write.replace("'", "\"")
                            writer.write(data_to_write)
                        return
                    if data.get('logfile'):
                        with open(Path(EXAMPLE_DIR, 'output', 'error_full_output.json'), 'w') as writer:
                            data_to_write = str(data)
                            data_to_write = data_to_write.replace("'", "\"")
                            writer.write(data_to_write)
                        with open(Path(EXAMPLE_DIR, 'output', 'shieldlog.log'), 'w') as writer:
                            writer.write(data['logfile'])
                        for key, value in data['input_files'].items():
                            with open(Path(EXAMPLE_DIR, 'output', key), 'w') as writer:
                                writer.write(value)
                        return
                    if data.get('error'):
                        print(data.get('error'))
                        return

            except Exception as e:  # skipcq: PYL-W0703
                print(e)


def run_simulation_with_files(session: requests.Session, port: int = 5000, do_monitor_job: bool = True):
    """Example function running simulation with input files"""
    input_files = read_input_files()

    timer = timeit.default_timer()
    res: requests.Response = session.post(Endpoints(port=port).http_sim_run, json={'input_files': input_files})
    data: dict = res.json()
    print(data)

    task_id: str = data.get('task_id')

    if task_id is not None:
        while do_monitor_job:
            time.sleep(5)
            # we need to relog in every 2 hours or refresh every 10 minutes
            # for just simplicity of the code we are just relogging in
            if timeit.default_timer() - timer > 500:
                res: requests.Response = session.post(Endpoints(port=port).http_auth_login, json=AUTH_JSON)
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
                        with open(Path(EXAMPLE_DIR, 'output', 'simulation_output.json'), 'w') as writer:
                            data_to_write = str(data['result'])
                            data_to_write = data_to_write.replace("'", "\"")
                            writer.write(data_to_write)
                        return
                    if data.get('logfile'):
                        with open(Path(EXAMPLE_DIR, 'output', 'error_full_output.json'), 'w') as writer:
                            data_to_write = str(data)
                            data_to_write = data_to_write.replace("'", "\"")
                            writer.write(data_to_write)
                        with open(Path(EXAMPLE_DIR, 'output', 'shieldlog.log'), 'w') as writer:
                            writer.write(data['logfile'])
                        for key, value in data['input_files'].items():
                            with open(Path(EXAMPLE_DIR, 'output', key), 'w') as writer:
                                writer.write(value)
                        return
                    if data.get('error'):
                        print(data.get('error'))
                        return

            except Exception as e:  # skipcq: PYL-W0703
                print(e)


def check_backend_jobs(session: requests.Session, sim_n: int, page_size: int, port: int = 5000):
    """Example checking backend jobs with pagination"""
    res: requests.Response = session.post(Endpoints(port=port).http_auth_login, json=AUTH_JSON)
    print(res.json())
    if res.status_code != 202:
        return
    timer = timeit.default_timer()
    are_all_finished = False
    one_last_run = True
    while not are_all_finished and one_last_run:
        some_still_running = False
        for i in range(math.ceil(sim_n/page_size)):
            time.sleep(5)
            if timeit.default_timer() - timer > 500:
                res: requests.Response = session.post(Endpoints(port=port).http_auth_login, json=AUTH_JSON)
                if res.status_code != 202:
                    print(res.json())
                    return
                timer = timeit.default_timer()
            res: requests.Response = session.get(Endpoints(port=port).http_list_sims, params={
                "page_size": page_size,
                "page_idx": i,
                "order_by": "start_time",
                "order_type": "descend",
            })
            res_json: dict = res.json()
            print(res_json['simulations_count'])
            for sim in res_json['simulations']:
                print(sim)
                task_id = sim['task_id']
                res: requests.Response = session.post(Endpoints(port=port).http_sim_status, json={'task_id': task_id})
                res_json: dict = res.json()
                if "result" not in res_json and not some_still_running:
                    some_still_running = True
                    print("Some still running")
        one_last_run = not are_all_finished
        are_all_finished = not some_still_running


def read_grid_proxy_file(dir_path: str) -> str:
    """Function reading grid_proxy file"""
    grid_proxy_path = Path(dir_path, 'grid_proxy')
    grid_proxy = ""
    try:
        with open(grid_proxy_path) as grid_proxy_file:
            grid_proxy = grid_proxy_file.read()
    except FileNotFoundError:
        print("Generate grid_proxy file by adjusting following command:\n")
        cmd = "read -s p && echo $p | ssh -l <plgusername> ares.cyfronet.pl "
        cmd += r'"grid-proxy-init -q -pwstdin && cat /tmp/x509up_u\`id -u\`"'
        cmd += f" > {grid_proxy_path} && unset p\n"
        print(cmd)
    return grid_proxy


def run_simulation_with_rimrock(session: requests.Session, port: int = 5000, do_monitor_job: bool = True):
    """Example function running simulation on rimrock"""
    session = requests.Session()
    input_files = read_input_files()
    timer = timeit.default_timer()
    res: requests.Response = session.post(Endpoints(port=port).http_auth_login, json=AUTH_JSON)
    res_json = res.json()
    print(res_json)
    if res.status_code != 202:
        return
    res: requests.Response = session.post(Endpoints(port=port).http_rimrock, json=input_files)
    res_json = res.json()
    print(res_json)
    if res.status_code != 201:
        return

    job_id: str = res_json.get('job_id')
    if job_id is not None:
        while do_monitor_job:
            time.sleep(5)
            # we need to relog in every 2 hours or refresh every 10 minutes
            # for just simplicity of the code we are just relogging in
            if timeit.default_timer() - timer > 500:
                res: requests.Response = session.post(Endpoints(port=port).http_auth_login, json=AUTH_JSON)
                if res.status_code != 202:
                    print(res.json())
                    return
                timer = timeit.default_timer()
            res: requests.Response = session.get(Endpoints(port=port).http_rimrock,
                                                 params={"job_id": job_id})
            res_json = res.json()
            print(f'Rescode {res.status_code}')
            print(res_json)
            if res.status_code != 200:
                return
            if res_json['status'] == 'FINISHED':
                get_slurm_results(session=session, job_id=job_id, port=port)
                return


def check_rimrock_jobs(session: requests.Session, port: int = 5000):
    """Example function cehcking rimrock jobs' statuses"""
    res: requests.Response = session.get(Endpoints(port=port).http_rimrock)
    res_json = res.json()
    print(res_json)


def get_slurm_results(session: requests.Session, job_id: str, port: int = 5000):
    """Example function getting slurm results"""
    res: requests.Response = session.get(Endpoints(port=port).http_plgdata,
                                         params={"job_id": job_id})
    res_json = res.json()
    path = Path(EXAMPLE_DIR, 'output', f'{job_id.split(".")[0]}.json')
    with open(path, 'w') as writer:
        data_to_write = str(res_json['result'])
        data_to_write = data_to_write.replace("'", "\"")
        writer.write(data_to_write)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', help='backend port', default=5000, type=int)
    args = parser.parse_args()
    main_session = requests.Session()
    run_simulation_with_rimrock(session=main_session, port=args.port, do_monitor_job=True)
