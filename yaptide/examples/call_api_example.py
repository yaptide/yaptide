import requests
import json
import time


def call_api():
    """Example backend endpoint call"""
    api_post = 'http://localhost:5000/sh/run?sim_type=dummy'
    api_get = 'http://localhost:5000/sh/status'

    with open('example.json') as json_file:
        data_to_send = json.load(json_file)

    res: requests.Response = requests.post(api_post, json=data_to_send)

    task_id: str = ""
    data = res.json()
    task_id = data.get('message').get('task_id')
    if task_id != "":
        while True:
            res: requests.Response = requests.get(api_get, json={'task_id': task_id})
            try:
                print(res.json())
                data = res.json()
                if data["state"] == "SUCCESS":
                    print(data["result"])
                    return
                if data["state"] == "FAILURE":
                    return

            except Exception as e:  # skipcq: PYL-W0703
                print(e)
            time.sleep(5)


if __name__ == "__main__":
    call_api()
