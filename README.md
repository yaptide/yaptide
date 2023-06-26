# yaptide backend

## Installation

Run: `$ pip install -r requirements.txt`

Download/update sumbmodules:

```shell
git submodule update --init --recursive
```

## Running the app

1. Get the redis

    - If you already use it just start it on port `6379`
    - If not good solution would comes with help of docker, run the following commands:
      - `$ docker run -dp 6379:6379 redis`

2. Run Celery with `$ celery --app yaptide.celery.worker worker -P threads --loglevel=info`

    - You can reuse the same terminal, as for redis, as docker sends redis process to the background

3. In new terminal set FLASK_APP env variable ([explanation](https://flask.palletsprojects.com/en/2.0.x/cli/)):

    - Windows CMD: `$ set FLASK_APP=yaptide.application`
    - Windows Powershell: `$ $env:FLASK_APP = "yaptide.application"`
    - Linux: `$ export FLASK_APP=yaptide.application`

4. Run the app: `$ flask run`

    - By default the app will re-create the database with each run, dropping it in the process.
    - To persist the database between runs this `with app.app_context(): models.create_models()` in yaptide/application.py inside the `create_app` factory.

## Building/Running with Docker

You can build and run the app using the following command:

```shell
docker compose up -d --build
```

Once it's running, the app will be available at [http://localhost:5000](http://localhost:5000). If you get an error saying the container name is already in use, stop and remove the container and then try again.

When you're ready to stop the containers, use the following commands:

```shell
docker compose stop
docker system prune
```

## Local Authorisation

Currently, there is a first version of authorisation. For now we need to register new user and log in.

1. Register:
   Example curl for Windows cmd:

```shell
curl -i -X PUT -H "Content-Type:application/json" -d "{\"username\": \"login\", \"password\": \"password\" }" http://localhost:5000/auth/register
```

2. Log in:
   Example curl for Windows cmd:

```shell
curl -i -X POST -c cookies.txt -H "Content-Type:application/json" -d "{\"username\": \"login\", \"password\": \"password\" }" http://localhost:5000/auth/login
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

## Docker database

Now registering, updating and deleting users is available with the use of `db_manage.py` located in `yaptide/admin` folder.
Once docker compose is running, you can use the following command:
`docker exec -w /usr/local/app/ yaptide_flask python3 yaptide/admin/db_manage.py --help`.

To add an user run:

```bash
docker exec -w /usr/local/app/ yaptide_flask python3 yaptide/admin/db_manage.py add-user admin --password mysecretpassword
```

## Testing API with command-line tools

Currently converter is parsing some of the frontend input so it would be wise to pass the valid json in order to run the simulation (or you just end up with 500 API status)

Example curl for Windows cmd:

```shell
curl -i -X POST -b cookies.txt -H "Content-Type:application/json" -d @path/to/jsonfile http://localhost:5000/jobs/direct
```

And for Linux:

```shell
curl -i -X POST -b cookies.txt -H "Content-Type:application/json" -d @path/to/jsonfile "http://localhost:5000/jobs/direct"
```

You can also add parameters after `?` sign like this: `http://localhost:5000/jobs/direct?<param name>=<param value>`
Possible parameters:

-   jobs - number of threads simulations should run on
-   sim_type - name of the simulator you wish to use, possible are `shieldhit` which is default, `topas` and `dummy` (note that they might not be working yet and for the purpose of testing just API not simulation results, use `dummy`)

The result of curl contains the job_id by which you can access the status of task started in the backend. In this case you can access the status by another curl.

Example curl for Windows cmd:

```shell
curl -i -X GET -b cookies.txt -H "Content-Type:application/json" -d "{\"job_id\": \"<job_id>\"}" http://localhost:5000/jobs/direct
```

And for Linux:

```shell
curl -i -X GET -b cookies.txt -H "Content-Type:application/json" -d "{'job_id' : '<job_id>'}" "http://localhost:5000/jobs/direct"
```

## Windows running script

There are 3 scripts prepared for Windows. Example calls: 

```shell
.\scripts\run_yaptide.bat <shieldhit_binary_file_path>
.\scripts\kill_yaptide.bat
.\scripts\run_dev_testing.bat <shieldhit_binary_file_path>
```

First script setups the YAPTIDE environment
Second allows to delete YAPTIDE environment
Third one setups the environment, runs tests and deletes environment

## For developers

### installation

Alternative method for [installation](#installation) of requirements using **venv**.

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Testing

Run tests on Linux with:

```shell
pytest
```

on Windows you need to run them one by one:

```shell
Get-ChildItem -Path "tests" -Filter "test_*.py" -Recurse | foreach { pytest $_.FullName }
```

# Credits

This work was partially funded by EuroHPC PL Project, Smart Growth Operational Programme 4.2
