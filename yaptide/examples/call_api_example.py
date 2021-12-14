import requests
import json
import time
import os
import timeit


def run_simulation_on_backend():
    """Example client running simulation"""
    http_sim_run = 'http://localhost:5000/sh/run'
    http_sim_status = 'http://localhost:5000/sh/status'
    http_sim_inputs = 'http://localhost:5000/sh/inputs'
    http_list_sims = 'http://localhost:5000/user/simulations'

    http_auth_login = 'http://localhost:5000/auth/login'
    http_auth_logout = 'http://localhost:5000/auth/logout'

    auth_json = {
        "login_name": "admin",
        "password": "password",
    }

    example_dir = os.path.dirname(os.path.realpath(__file__))
    example_path = os.path.join(example_dir, 'example.json')

    with open(example_path) as json_file:
        data_to_send = json.load(json_file)

    session = requests.Session()

    res: requests.Response = session.post(http_auth_login, json=auth_json)

    if res.status_code != 202:
        print(res.json())
        return

    timer = timeit.default_timer()
    res: requests.Response = session.post(http_sim_run, json=data_to_send)

    task_id: str = ""
    data: dict = res.json()
    print(data)
    task_id = data.get('content').get('task_id')

    res: requests.Response = session.get(http_list_sims)
    data: dict = res.json()
    print(data)

    is_input_saved = True
    if task_id != "":

        while True:
            time.sleep(5)
            # we need to relog in every 2 hours or refresh every 10 minutes
            # for just simplicity of the code we are just relogging in
            if timeit.default_timer() - timer > 500:
                res: requests.Response = session.post(http_auth_login, json=auth_json)
                if res.status_code != 202:
                    print(res.json())
                    return
                timer = timeit.default_timer()
            try:
                res: requests.Response = session.post(http_sim_status, json={'task_id': task_id})
                data: dict = res.json()
                print(data.get('message'))

                if res.status_code == 200:
                    if data['content'].get('result'):
                        with open(os.path.join(example_dir, 'output', 'simulation_output.json'), 'w') as writer:
                            data_to_write = str(data['content']['result'])
                            data_to_write = data_to_write.replace("'", "\"")
                            writer.write(data_to_write)
                        session.delete(http_auth_logout)
                        return
                    elif data['content'].get('shieldhitlog'):
                        with open(os.path.join(example_dir, 'output', 'error_full_output.json'), 'w') as writer:
                            data_to_write = str(data['content'])
                            data_to_write = data_to_write.replace("'", "\"")
                            writer.write(data_to_write)
                        with open(os.path.join(example_dir, 'output', 'shieldlog.log'), 'w') as writer:
                            writer.write(data['content']['shieldhitlog'])
                        for key in data['content']['input_files']:
                            with open(os.path.join(example_dir, 'output', key), 'w') as writer:
                                writer.write(data['content']['input_files'][key])
                        session.delete(http_auth_logout)
                        return

            except Exception as e:  # skipcq: PYL-W0703
                print(e)


if __name__ == "__main__":
    run_simulation_on_backend()
