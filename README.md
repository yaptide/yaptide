# yaptide backend

## Getting the code

Clone the repository including submodules:

```shell
git clone --recurse-submodules https://github.com/yaptide/yaptide.git
```

In case you have used regular `git clone` command, without `--recurse-submodules` option, you can still download the submodules by running:

```shell
git submodule update --init --recursive
```

## Running the app

Application consists of multiple components. The simplest way to run the app is to use docker-compose.
Following instruction will guide you through the process of set up and running the application.

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
`docker exec -w /usr/local/app/ yaptide_flask ./yaptide/admin/db_manage.py --help`.

To add an user run:

```bash
docker exec -w /usr/local/app/ yaptide_flask ./yaptide/admin/db_manage.py add-user admin --password mysecretpassword
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

Project make use of poetry for dependency management. If you do not have it installed, check official [poetry installation guide](https://python-poetry.org/docs/).
Project is configured to  create virtual environment for you, so you do not need to worry about it.
Virtual environment is created in `.venv` folder in the root of the project.

### Installing dependencies

To install all dependencies, run:

```bash
poetry install
```

This will install all the dependencies including `test` and `docs` ones.
If you want to test app, you do not need `docs` dependencies, you can skip them by using:

```bash
poetry install --without docs
```

If you want to install only main dependencies, you can use:

```bash
poetry  install --only main,test
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

### Development

To maintain code quality, we use yapf and flake8. You can run them with.
To avoid running them manually we strongly recommend to use pre-commit hooks. To install them run:

```shell
poetry run pre-commit install
```

### Pre-commit Use Cases

### Case 1: All Hooks Pass Successfully

1. **Add or Modify Files**: Make changes to your codebase as usual.

2. **Stage Changes**: Stage the changes you made using `git add`.

3. **Commit Changes**: Commit your changes using `git commit`.

4. **Pre-commit Hooks Run**: Before the commit is finalized, pre-commit will automatically run all configured hooks.

5. **Success**: If all hooks pass without any issues, the commit proceeds as usual.

6. **Commit Successfully**: Your changes are now committed to the repository with the assurance that they meet the project's coding standards.

### Case 2: Some Hooks Fail

1. **Add or Modify Files**: Make changes to your codebase as usual.

2. **Stage Changes**: Stage the changes you made using `git add`.

3. **Commit Changes**: Attempt to commit your changes using `git commit`.

4. **Pre-commit Hooks Run**: Before the commit is finalized, pre-commit will automatically run all configured hooks.

5. **Failure**: If one or more hooks fail, pre-commit will abort the commit process.

6. **Review Error Messages**: Read the error messages in the terminal to identify which hooks failed and why.

7. **Fix Issues**: Address the issues reported by the failed hooks. Some hooks automatically format code so you don't have to change anything.

8. **Retry Commit**: Once the issues are fixed, stage the changes again using `git add` and attempt to commit once more.

9. **Success**: If all hooks pass after fixing the issues, the commit proceeds as usual.

10. **Commit Successfully**: Your changes are now committed to the repository with the assurance that they meet the project's coding standards.

## Credits

This work was partially funded by EuroHPC PL Project, Smart Growth Operational Programme 4.2
