# Persistency storage

## Data model

We have following data model, implemented in `yaptide/persistence/models.py`:

Simulation model and dependent classes:
```mermaid
classDiagram
  class SimulationModel {
    id: int
    job_id: str
    user_id: int
    start_time: datetime
    end_time: datetime
    title: str
    platform: str
    input_type: str
    sim_type: str
    job_state: str
    update_key_hash: str
    tasks
    estimators
  }

  class CelerySimulationModel {
    id: int
    merge_id: str
  }

  class BatchSimulationModel {
    id: int
    cluster_id: int
    job_dir: str
    array_id: int
    collect_id: int
  }

  class TaskModel {
    id: int
    simulation_id: int
    task_id: int
    requested_primaries: int
    simulated_primaries: int
    task_state: str
    estimated_time: int
    start_time: datetime
    end_time: datetime
    platform: str
    last_update_time: datetime
  }

  class CeleryTaskModel {
    id: int
    celery_id: str
  }

  class BatchTaskModel {
    id: int
  }

  class InputModel {
    id: int
    simulation_id: int
    compressed_data: bytes
    data
  }

  class EstimatorModel {
    id: int
    simulation_id: int
    name: str
    compressed_data: bytes
    data
  }

  class PageModel {
    id: int
    estimator_id: int
    page_number: int
    compressed_data: bytes
    data
  }

  class LogfilesModel {
    id: int
    simulation_id: int
    compressed_data: bytes
    data
  }

  SimulationModel <|-- CelerySimulationModel
  SimulationModel <|-- BatchSimulationModel
  TaskModel <|-- CeleryTaskModel
  TaskModel <|-- BatchTaskModel
  SimulationModel "1" *-- "0..*" TaskModel
  SimulationModel "1" *-- "0..*" EstimatorModel
  EstimatorModel "1" *-- "0..*" PageModel
  SimulationModel "1" *-- "0..*" LogfilesModel
  SimulationModel *-- InputModel
```

other classes we use are:

```mermaid
classDiagram
  class UserModel {
    id: int
    username: str
    auth_provider: str
    simulations
  }

  class YaptideUserModel {
    id: int
    password_hash: str
  }

  class KeycloakUserModel {
    id: int
    cert: str
    private_key: str
  }

  class ClusterModel {
    id: int
    cluster_name: str
    simulations
  }

  UserModel <|-- YaptideUserModel
  UserModel <|-- KeycloakUserModel
```

We've been too lazy to write down the mermaid code for these diagrams, but ChatGPT nowadays does a good job on that.
Whenever you need to update the diagrams, just copy the code from the `yaptide/persistence/models.py` file and ask ChatGPT to generate the diagram for you.

## Database

Production version uses PostgreSQL database, while in the unit tests suite we use SQLite in-memory database.

Sometimes it may be convenient to connect to the production DB from outside the container, e.g. to check the content of the database.
Then you can use the following command to get the DB URL.

```shell
docker exec -it yaptide_flask bash -c "cd /usr/local/app && python -c 'from yaptide.application import create_app; app = create_app(); app.app_context().push() or print(app.extensions[\"sqlalchemy\"].engine.url.render_as_string(hide_password=False))'"
```

The code above is implemented as a handy onliner, the code may look tricky, epecially the `app.app_context().push() or` part.
The reason for that hacking is simple. Regular methods to get the DB URL require the application context. This is usually achieved using `with app.app_context():` construct, which is not possible in the oneliner.

Knowing the DB URL, you can connect to the DB using any DB client, e.g. `psql` or `pgadmin`. You can also use the `db_manage.py` script from the `yaptide/admin` directory. For example, to list all users in the DB, you can use the following command from outside the container:

```shell
FLASK_SQLALCHEMY_DATABASE_URI=postgresql+psycopg://yaptide_user:yaptide_password@localhost:5432/yaptide_db ./yaptide/admin/db_manage.py list-users
```

This is equivalent to the following command executed inside the container:

```shell
docker exec -it yaptide_flask ./yaptide/admin/db_manage.py list-users
```

## Developing model

In Yaptide flask-migrate is responsible for modyfing database after each change to `models.py` and keeping track of versions of database (new version comes after each modification of models.py).

### Development steps
For development running yaptide_postgres in docker is required

1. Depending on whether development happens locally or yap-dev export `FLASK_SQLALCHEMY_DATABASE_URI` or define it before each `flask db` command execution:


    - The general pattern for `FLASK_SQLALCHEMY_DATABASE_URI` is taken from docker-compose (there is only postgres changed to localhost):

      `FLASK_SQLALCHEMY_DATABASE_URI=postgresql+psycopg://${POSTGRES_USER:-yaptide_user}:${POSTGRES_PASSWORD:-yaptide_password}@localhost:5432/${POSTGRES_DB:-yaptide_db}`

      e.g. for local development `FLASK_SQLALCHEMY_DATABASE_URI=postgresql+psycopg://yaptide_user:yaptide_password@localhost:5432/yaptide_db`
1. When first time using flask migrate during database running on docker on local machine, run `flask --app yaptide.application db stamp 06c32cf470e7` (first version)
1. Do modifications `models.py`
1. Run `flask --app yaptide.application db migrate`.
    - In case of error `ERROR [flask_migrate] Error: Target database is not up to date` run
    `flask --app yaptide.application db stamp head`
1. There will be generated file named after currnet version in migrations/versions
1. Check the file, there might be some `None` values which needs to be changed. Pasting script in chat gpt might be helpful to identify some potential problems.
1. then run `flask --app yaptide.application db upgrade`




flask db stamp [--sql] [--tag TAG] <revision>

    Sets the revision in the database to the one given as an argument, without performing any migrations.
