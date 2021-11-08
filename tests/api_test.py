import requests
import json
import time


def test_api():
    api_post = 'http://localhost:5000/sh/run'
    api_get = 'http://localhost:5000/sh/status?task_id={task_id}'

    res = requests.post(api_post, json = {"some": "json"})

    task_id = None
    data = json.loads(res.json())
    print(data)
    for key in json.loads(res.json()):
        if key == 'task_id':
            task_id = data[key]
        if task_id != None:
            while True:
                time.sleep(5)
                res = requests.get(api_get.format(task_id=task_id))
                try:
                    print(res)
                    print(res.text)
                    print(res.json())
                    # data = json.loads(str(res.json()))

                except Exception:
                    print(Exception)

if __name__ == "__main__":
    test_api()
