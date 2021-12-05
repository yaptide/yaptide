import requests
import json
import time
import os


def call_api():
    """Example backend endpoint call"""
    api_post = 'http://localhost:5000/sh/run'
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
    is_input_saved = True
    if task_id != "":
        while True:
            time.sleep(5)
            try:
                if is_input_saved:
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
                    is_input_saved = False

                res: requests.Response = requests.get(api_status, json={'task_id': task_id})
                data = res.json()
                print(data.get('state'))

                if data["state"] == "SUCCESS":
                    with open(os.path.join(example_dir, 'simulation_output.json'), 'w') as writer:
                        data_to_write = str(data["result"])
                        data_to_write = data_to_write.replace("'", "\"")
                        writer.write(data_to_write)
                    return
                if data["state"] == "FAILURE":
                    return

            except Exception as e:  # skipcq: PYL-W0703
                print(e)


if __name__ == "__main__":
    call_api()
