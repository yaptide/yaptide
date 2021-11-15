import requests
import json
import time


def call_api():
    """Example backend endpoint call"""
    api_post = 'http://localhost:5000/sh/run'
    api_get = 'http://localhost:5000/sh/status?task_id={task_id}'

    with open('example.json') as json_file:
        data_to_send = json.load(json_file)

    res: requests.Response = requests.post(api_post, json=data_to_send)

    task_id: str = ""
    data = json.loads(res.json())
    for key in data:
        if key == 'task_id':
            task_id = data[key]
        if task_id != "":
            while True:
                res: requests.Response = requests.get(api_get.format(task_id=task_id))
                try:
                    print(res.json())
                    data = json.loads(str(res.json()))
                    if data["state"] == "SUCCESS":
                        print(data["result"])
                        return
                    if data["state"] == "FAILURE":
                        print("sth went wrong")
                        return

                except Exception:  # skipcq: PYL-W0703
                    print(Exception)
                time.sleep(5)


if __name__ == "__main__":
    call_api()
