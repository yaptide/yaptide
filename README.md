# Installation
Run: ```$ pip install -r requirements.txt```

# Running the app
1. Get the redis
   * If you already use it just start it on port ```6379```
   * If not good solution would comes with help of docker:
   * * Run the following commands
   * * ```$ docker run -dp 6379:6379 redis```

2. Run Celery with ```$ celery --app yaptide.simulation_runner.celery_app worker -P threads --loglevel=info```
   * You can reuse the same terminal, as for redis, as docker sends redis process to the background
   
3. In new terminal set FLASK_APP env variable ([explanation](https://flask.palletsprojects.com/en/2.0.x/cli/)):
   * Windows CMD: ```$ set FLASK_APP=yaptide.application```
   * Windows Powershell: ```$ $env:FLASK_APP = "yaptide.application"```
   * Linux: ```$ export FLASK_APP=yaptide.application```

4. Run the app: ```$ flask run```
   * By default the app will re-create the database with each run, dropping it in the process. 
   * To persist the database between runs this ```with app.app_context():
        models.create_models()``` in yaptide/application.py inside the ```create_app``` factory.

# Building/Running with Docker

You can build and run the app using the following command:

Linux:
```shell
SHIELDHIT_PATH=path/to/shieldhit docker-compose up -d --build
```

Windows Powershell:
```shell
$env:SHIELDHIT_PATH = "path.to.shieldhit"
```

Once it's running, the app will be available at [http://localhost:5000](http://localhost:5000). If you get an error saying the container name is already in use, stop and remove the container and then try again.

When you're ready to stop the containers, use the following commands:

```shell
docker-compose stop yaptide
docker-compose stop redis
docker-compose stop worker
docker system prune
```

# Testing API with command-line tools

Currently, the dummy converter ignores the JSON content sent in the request's body so it can contain anything.

Example curl for Windows:
```shell
curl -i -X POST -H "Content-Type:application/json" -d "{\"Dummy\": \"Curl\" }" http://localhost:5000/sh/run
```

And for Linux:
```shell
curl -i -X POST -H "Content-Type:application/json" -d '{"Dummy": "Curl" }' "http://localhost:5000/sh/run"
```

The result of curl contains the task_id by which you can access the status of task started in the backend. In this case you can access the status by another curl.

Example curl for Windows:
```shell
curl -i http://localhost:5000/sh/status?task_id=<task_id>
```

And for Linux:
```shell
curl -i "http://localhost:5000/sh/status?task_id=<task_id>"
```

Although it might be inefficient way of testing so there is a prepared example ```call_api_example.py``` in yaptide/examples folder