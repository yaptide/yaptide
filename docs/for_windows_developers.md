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

### Building and running the app

Application consists of multiple components. The simplest way to run the app is to use docker-compose. Following instruction will guide you through the process of set up and running the application.

1. Download SHIELD-HIT12A simulator

    Currently, we store binaries of three simulators on S3 platform. SHIELD-HIT12A (full version) and Fluka files are encrypted.

    To simply init download process we have to run following commands:

    ```bash
    poetry run ./yaptide/admin/simulators.py download-shieldhit --dir bin
    ```

    To get full instruction of command usage we can type

    ```bash
    poetry run ./yaptide/admin/simulators.py
    ```
2. Get the redis

    If you already use it just start it on port `6379`

    If not good solution would comes with help of docker, run the following commands:

    ```bash
    docker run --detach --publish 6379:6379 --name yaptide_redis redis:7-alpine
    ```

    To remove this container use:

    ```bash
    docker rm -f yaptide_redis
    ```

3. Run Celery

    You can reuse the same terminal, as for redis, as docker sends redis process to the background

    ```powershell
    $env:CELERY_BROKER_URL="redis://localhost:6379/0"; $env:CELERY_RESULT_BACKEND="redis://localhost:6379/0"; poetry run celery --app yaptide.celery.worker worker -P threads --loglevel=info
    ```

4. Run the app

    ```powershell
    $env:FLASK_SQLALCHEMY_DATABASE_URI="sqlite:///db.sqlite"; poetry run flask --app yaptide.application run
    ```
    This command will create `db.sqlite` inside `./instance` folder. This is [default flask behaviour](https://flask.palletsprojects.com/en/3.0.x/config/#instance-folders).

    To get more debugging information you can also force SQLALCHEMY to use `echo` mode by setting `SQLALCHEMY_ECHO` environment variable to `True`.

   ```powershell
   $env:FLASK_SQLALCHEMY_ECHO="True"; $env:FLASK_SQLALCHEMY_DATABASE_URI="sqlite://db.sqlite"; poetry run flask --app yaptide.application run
   ```

    To include debugging messages from flask, add `--debug` option to the command.

### Database

To add user, run:

```powershell
$env:FLASK_SQLALCHEMY_DATABASE_URI="sqlite:///instance/db.sqlite"; poetry run ./yaptide/admin/db_manage.py add-user admin --password password
```

You can use the following command, to get more information:

```
$env:FLASK_SQLALCHEMY_DATABASE_URI="sqlite:///instance/db.sqlite"; poetry run ./yaptide/admin/db_manage.py --help
```

### Testing
On Windows you need to run tests one by one:

```shell
Get-ChildItem -Path "tests" -Filter "test_*.py" -Recurse | foreach { poetry run pytest $_.FullName }
```

### Development

To maintain code quality, we use yapf and flake8. You can run them with. To avoid running them manually we strongly recommend to use pre-commit hooks. To install them run:

```shell
poetry run pre-commit install
```
