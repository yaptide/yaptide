# Installation

Run: ``$ pip install -r requirements.txt``

# Running the app

1. Get the redis

   * If you already use it just start it on port ``6379``
   * If not good solution would comes with help of docker:
   * * Run the following commands
   * * ``$ docker run -dp 6379:6379 redis``
2. Run Celery with ``$ celery --app yaptide.celery.worker worker -P threads --loglevel=info``

   * You can reuse the same terminal, as for redis, as docker sends redis process to the background
3. In new terminal set FLASK_APP env variable ([explanation](https://flask.palletsprojects.com/en/2.0.x/cli/)):

   * Windows CMD: ``$ set FLASK_APP=yaptide.application``
   * Windows Powershell: ``$ $env:FLASK_APP = "yaptide.application"``
   * Linux: ``$ export FLASK_APP=yaptide.application``
4. Run the app: ``$ flask run``

   * By default the app will re-create the database with each run, dropping it in the process.
   * To persist the database between runs this ``with app.app_context(): models.create_models()`` in yaptide/application.py inside the ``create_app`` factory.

# Building/Running with Docker

You can build and run the app using the following command:

Linux:

```shell
SHIELDHIT_PATH=path/to/shieldhit docker-compose up -d --build
```

Windows Powershell:

```shell
$env:SHIELDHIT_PATH = "path.to.shieldhit"
docker-compose up -d --build
```

Due to docker specific limitations, shieldhit path cannot be absolute path. shieldhit binary needs to be located in the same or in one of yaptide subdirectories (at the same or lower level than Dockerfile).

Once it's running, the app will be available at [http://localhost:5000](http://localhost:5000). If you get an error saying the container name is already in use, stop and remove the container and then try again.

When you're ready to stop the containers, use the following commands:

```shell
docker-compose stop yaptide_flask
docker-compose stop yaptide_worker
docker-compose stop redis
docker system prune
```

# Local Authorisation

Currently, there is a first version of authorisation. For now we need to register new user and log in.

1. Register:
   Example curl for Windows cmd:

```shell
curl -i -X PUT -H "Content-Type:application/json" -d "{\"login_name\": \"login\", \"password\": \"password\" }" http://localhost:5000/auth/register
```

2. Log in:
   Example curl for Windows cmd:

```shell
curl -i -X POST -c cookies.txt -H "Content-Type:application/json" -d "{\"login_name\": \"login\", \"password\": \"password\" }" http://localhost:5000/auth/login
```

3. Status:
   Example curl for Windows cmd:

```shell
curl -i -X GET -b cookies.txt http://localhost:5000/auth/status
```

4. Refresh:
   Example curl for Windows cmd:

```shell
curl -i -X GET -b cookies.txt -c cookies.txt http://localhost:5000/auth/refresh
```

5. Logout:
   Example curl for Windows cmd:

```shell
curl -i -X DELETE http://localhost:5000/auth/logout
```

# Docker database

Now registering, updating and deleting users is available with the use of ``db_script.py`` located in ``yaptide/data`` folder, which is a volume folder for ``yaptide_flask`` container. To make any changes in the database, ``script_input.json`` (the name is currently hardcoded) file should be prepared. ``example_script_input.json`` shows pattern of doing this. It is possible to either edit the file in Docker CLI (user unfriendly way) or prepare the file elsewhere and copy/move it into ``yaptide_data/_data`` folder found in docker volumes folder. In order to get access to PLGrid resources it is required to generate ``grid_proxy`` file (instruction describing generating it are provided in ``PLGrid`` section). After preparing ``grid_proxy`` file it should be copied/moved into ``yaptide_data/_data`` folder and in ``script_input.json`` its name should be added in User update option following the pattern showed in ``example_script_input.json``. In next step, ``db_script.py`` can be run in the Docker CLI (from any folder) of ``yaptide_flask`` container with ``python3 /path/to/file/db_script.py`` command or in terminal (for example in which docker-compose was run) with ``docker exec -w /usr/local/app/yaptide/data yaptide_flask python3 db_script.py`` command.

# Testing API with command-line tools

Currently converter is parsing some of the frontend input so it would be wise to pass the valid json in order to run the simulation (or you just end up with 500 API status)

Example curl for Windows cmd:

```shell
curl -i -X POST -b cookies.txt -H "Content-Type:application/json" -d @path/to/jsonfile http://localhost:5000/sh/run
```

And for Linux:

```shell
curl -i -X POST -b cookies.txt -H "Content-Type:application/json" -d @path/to/jsonfile "http://localhost:5000/sh/run"
```

You can also add parameters after ``?`` sign like this: ``http://localhost:5000/sh/run?<param name>=<param value>``
Possible parameters:

* jobs - number of threads simulations should run on
* sim_type - name of the simulator you wish to use, possible are ``shieldhit`` which is default, ``topas`` and ``dummy`` (note that they might not be working yet and for the purpose of testing just API not simulation results, use ``dummy``)

The result of curl contains the task_id by which you can access the status of task started in the backend. In this case you can access the status by another curl.

Example curl for Windows cmd:

```shell
curl -i -X GET -b cookies.txt -H "Content-Type:application/json" -d "{\"task_id\": \"<task_id>\"}" http://localhost:5000/sh/status
```

And for Linux:

```shell
curl -i -X GET -b cookies.txt -H "Content-Type:application/json" -d "{'task_id' : '<task_id>'}" "http://localhost:5000/sh/status"
```

Although it might be inefficient way of testing so there is a prepared example ``call_api_example.py`` in yaptide/examples folder

# PLGrid

Command generating `grid_proxy` file on Linux (WSL also works fine)
```shell
read -s p && echo $p | ssh -l <plgusername> ares.cyfronet.pl "grid-proxy-init -q -pwstdin && cat /tmp/x509up_u\`id -u\`" > grid_proxy && unset p
```

# Credits

This work was partially funded by EuroHPC PL Project, Smart Growth Operational Programme 4.2
