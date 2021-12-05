import requests
import json
import time
import os


def call_api():
    """Example backend endpoint call"""
    api_post = 'http://localhost:5000/sh/run?sim_type=dummy'
    # api_post = 'http://localhost:5000/sh/run'
    api_status = 'http://localhost:5000/sh/status'
    api_inputs = 'http://localhost:5000/sh/inputs'

    example_dir = os.path.dirname(os.path.realpath(__file__))
    example_path = os.path.join(example_dir, 'example.json')

    with open(example_path) as json_file:
        data_to_send = json.load(json_file)

    res: requests.Response = requests.post(api_post, json=data_to_send)

    task_id: str = ""
    data = res.json()
    task_id = data.get('message').get('task_id')
    flag = True
    if task_id != "":
        while True:
            time.sleep(5)
            try:
                res: requests.Response = requests.get(api_status, json={'task_id': task_id})
                print(res.json())
                data = res.json()

                if data["state"] == "SUCCESS":
                    print(data["result"])
                    return
                if data["state"] == "FAILURE":
                    return

                if flag:
                    flag = False
                    res: requests.Response = requests.get(api_inputs, json={'task_id': task_id})
                    data = res.json()
                    with open(os.path.join(example_dir, 'simulation_inputs.txt'), 'w') as writer:
                        for key in data:
                            if key == 'state':
                                continue
                            writer.write(key)
                            writer.write("\n")
                            writer.write(data[key])
                            writer.write("\n")

            except Exception as e:  # skipcq: PYL-W0703
                print(e)


if __name__ == "__main__":
    call_api()
