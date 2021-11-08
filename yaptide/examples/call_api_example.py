import requests
import json
import time


def call_api():
    """Example backend endpoint call"""
    api_post = 'http://localhost:5000/sh/run'
    api_get = 'http://localhost:5000/sh/status?task_id={task_id}'

    res = requests.post(api_post, json={"some": "json"})

    task_id = None
    data = json.loads(res.json())
    print(data)
    for key in json.loads(res.json()):
        if key == 'task_id':
            task_id = data[key]
        if task_id:
            while True:
                time.sleep(5)
                res = requests.get(api_get.format(task_id=task_id))
                try:
                    print(res)
                    print(res.text)
                    print(res.json())
                    # data = json.loads(str(res.json()))

                except Exception:  # skipcq: PYL-W0703
                    print(Exception)


if __name__ == "__main__":
    call_api()
