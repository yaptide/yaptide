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

To check database URI:

```
docker exec -it yaptide_flask bash -c "cd /usr/local/app && python -c 'from yaptide.application import create_app; app = create_app(); app.app_context().push() or print(app.extensions[\"sqlalchemy\"].engine.url.render_as_string(hide_password=False))'"
```

or

```
(venv) grzanka@grzankax1:~/workspace/yaptide$ DB_URL=$(docker exec -it yaptide_flask bash -c "cd /usr/local/app && python -c 'from yaptide.application import create_
app; app = create_app(); app.app_context().push() or print(app.extensions[\"sqlalchemy\"].engine.url.render_as_string(hide_password=False))'")
(venv) grzanka@grzankax1:~/workspace/yaptide$ echo $DB_URL
postgresql://yaptide_user:yaptide_password@postgresql:5432/yaptide_db
```

testing:
```
FLASK_SQLALCHEMY_DATABASE_URI=postgresql://yaptide_user:yaptide_password@localhost:5432/yaptide_db ./yaptide/admin/db_manage.py list-users
```
