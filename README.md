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

    ```
    docker run --name yaptide_redis -dp 6379:6379 redis
    ```

2. Run Celery

    - You can reuse the same terminal, as for redis, as docker sends redis process to the background

    - for Windows run in Powershell

   ```powershell
   $env:CELERY_BROKER_URL="redis://localhost:6379/0"; $env:CELERY_RESULT_BACKEND="redis://localhost:6379/0"; celery --app yaptide.celery.worker worker -P threads --loglevel=info
    ```

    - for Linux run in bash

   ```bash
   CELERY_BROKER_URL=redis://localhost:6379/0 CELERY_RESULT_BACKEND=redis://localhost:6379/0 celery --app yaptide.celery.worker worker -P threads --loglevel=info
    ```

3. Run the app: `$ flask run`

   - For Linux run:

   ```bash
   FLASK_SQLALCHEMY_DATABASE_URI="sqlite:///db.sqlite" flask --app yaptide.application run
   ```

   - For Windows run:

   ```powershell
   $env:FLASK_SQLALCHEMY_DATABASE_URI="sqlite:///db.sqlite"; flask --app yaptide.application run
   ```
   For unknown reasons in Windows full absolute path is required.

   To get more debugging you can also force SQLALCHEMY to use `echo` mode by setting `SQLALCHEMY_ECHO` environment variable to `True`.

   - For Linux run:

   ```bash
   FLASK_SQLALCHEMY_ECHO=True FLASK_SQLALCHEMY_DATABASE_URI="sqlite:///db.sqlite" flask --app yaptide.application run
   ```

   - For Windows run:

   ```powershell
   $env:FLASK_SQLALCHEMY_ECHO="True"; $env:FLASK_SQLALCHEMY_DATABASE_URI="sqlite://db.sqlite"; flask --app yaptide.application run
   ```

   - To include debugging messages from flask, add `--debug` option to the command.

## Building/Running with Docker

You can build and run the app using the following command:

```shell
docker compose up -d --build
```

Once it's running, the app will be available at [http://localhost:5000](http://localhost:5000). If you get an error saying the container name is already in use, stop and remove the container and then try again.


## Docker database

Now registering, updating and deleting users is available with the use of `db_manage.py` located in `yaptide/admin` folder.
Once docker compose is running, you can use the following command:
`docker exec -w /usr/local/app/ yaptide_flask ./yaptide/admin/db_manage.py --help`.

To add an user run:

```bash
docker exec -w /usr/local/app/ yaptide_flask ./yaptide/admin/db_manage.py add-user admin --password mysecretpassword
```

In developer mode, use:

```powershell
$env:FLASK_SQLALCHEMY_DATABASE_URI="sqlite:///instance/db.sqlite"; python ./yaptide/admin/db_manage.py add-user admin --password admin
```

or

```bash
FLASK_SQLALCHEMY_DATABASE_URI="sqlite:///instance/db.sqlite" python ./yaptide/admin/db_manage.py add-user admin --password admin
```

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
poetry run pytest
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

## Credits

This work was partially funded by EuroHPC PL Project, Smart Growth Operational Programme 4.2
