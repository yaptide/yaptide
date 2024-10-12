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

The code above is implemented as a handy onliner, the code may look tricky, especially the `app.app_context().push() or` part.
The reason for that hacking is simple. Regular methods to get the DB URL require the application context. This is usually achieved using `with app.app_context():` construct, which is not possible in the oneliner.

Knowing the DB URL, you can connect to the DB using any DB client, e.g. `psql` or `pgadmin`. You can also use the `db_manage.py` script from the `yaptide/admin` directory. For example, to list all users in the DB, you can use the following command from outside the container:

```shell
FLASK_SQLALCHEMY_DATABASE_URI=postgresql+psycopg://yaptide_user:yaptide_password@localhost:5432/yaptide_db ./yaptide/admin/db_manage.py list-users
```

This is equivalent to the following command executed inside the container:

```shell
docker exec -it yaptide_flask ./yaptide/admin/db_manage.py list-users
```

## commands in db_manage.py

The `db_manage.py` script provides several commands to manage the database. Below is a list of available commands along with their arguments and options:

- **list_users**
  - Printed columns: `username`, `auth_provider`
  - Options:
    - `-v`, `--verbose`

- **add_user**
  - Arguments:
    - `name`
  - Options:
    - `--password` (default: '')
    - `-v`, `--verbose`

- **update_user**
  - Arguments:
    - `name`
  - Options:
    - `--password` (default: '')
    - `-v`, `--verbose`

- **remove_user**
  - Arguments:
    - `name`
    - `auth_provider`

- **list_tasks**
  - Printed columns: `simulation_id`, `task_id`, `task_state`, `username`
  - Options:
    - `--user`
    - `--auth-provider`

- **remove_task**
  - Arguments:
    - `task_id`
  - Options:
    - `-v`, `--verbose`

- **list_simulations**
    - Printed columns: `id`, `job_id`, `start_time`, `end_time`, `username`
  - Options:
    - `-v`, `--verbose`
    - `--user`
    - `--auth-provider`

- **remove_simulation**
  - Arguments:
    - `simulation_id`
  - Options:
    - `-v`, `--verbose`

- **add_cluster**
  - Arguments:
    - `cluster_name`
  - Options:
    - `-v`, `--verbose`

- **list_clusters**
  - Columns: `id`, `cluster_name`
