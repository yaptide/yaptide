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
For development - running yaptide_postgres in docker is required. It's recommended to do development on local machine.

1. Make sure all poetry dependencies are installed. Run `poetry shell` in terminal.
2. Calling `flask db` commands will require `FLASK_SQLALCHEMY_DATABASE_URI` variable to be defined before each execution:

    - The general pattern for `FLASK_SQLALCHEMY_DATABASE_URI` is taken from docker-compose (there is only postgres changed to localhost):

      `FLASK_SQLALCHEMY_DATABASE_URI=postgresql+psycopg://${POSTGRES_USER:-yaptide_user}:${POSTGRES_PASSWORD:-yaptide_password}@localhost:5432/${POSTGRES_DB:-yaptide_db}`

      e.g. for local development `FLASK_SQLALCHEMY_DATABASE_URI=postgresql+psycopg://yaptide_user:yaptide_password@localhost:5432/yaptide_db` will be put before each `flask db` call. For local development it can be exported as variable but it's not recommended for environments where username, password are sensitive information.

      **From now each command in this docummentation containing `flask db` should be called with `FLASK_SQLALCHEMY_DATABASE_URI`**.

3. Now it's time to prepare local/development database for development of models.py and creation of migration script.

    - In `docker-compose.yml` edit database service to use volume with different name, this will create new volume and old one won't get deleted. Run `scripts/start_with_docker.sh`. This will create database that for sure reflects what's in models.py. Then to mark database with version from migrations/versions, run `flask --app yaptide.application db stamp head`. This will save id of newest version of database in alembic_version table. **Be cautios as this option is only for development on local machine.**

4. Do modifications in `models.py`.
5. Run `flask --app yaptide.application db migrate`.
6. There will be generated migration file in migrations/versions. Name of the newest file is displayed in output of above command.
7. **IMPORTANT!** Check the file carefully. For example there might be some `None` values which needs to be changed.
    -  script that adds CASCADE option to foreign constraint at first looks like this
        ```
        def upgrade():
            # ### commands auto generated by Alembic - please adjust! ###
            with op.batch_alter_table('Task', schema=None) as batch_op:
                batch_op.drop_constraint('Task_simulation_id_fkey', type_='foreignkey')
                batch_op.create_foreign_key(None, 'Simulation', ['simulation_id'], ['id'], ondelete='CASCADE')
        ```
        In this case change None to 'Task_simulation_id_fkey'.
8. Run `flask --app yaptide.application db upgrade` to apply migration script.
9. To undo changes and go back to previous version run `flask --app yaptide.application db downgrade`.
10. Commit and push script and modification to models.py.

### Testing migration script with copy of production volume

1. If there is testing environment other than local - pull changes.
2. Copy volume ("data") of production postgres database and save it under different name.
3. In `docker-compose.yml` modify database configuration to use this volume.
4. Run `scripts/start_with_docker_develop.sh`, to run backend and additionaly pgadminer tool (see section Using pgadminer).
5. Again prepare `FLASK_SQLALCHEMY_DATABASE_URI` like above and use it together with each `flask db` command.
6. Run `flask --app yaptide.application db upgrade`.
7. Check also `flask --app yaptide.application db downgrade`, then do upgrade again. All should execute without errors.
8. Do manual testing. Check functionalities, some might be unnecessary to check depending which part in `models.py` was changed:
    - logging in and out
    - Loading simulation results, input files, logs.
    - Submiting new simulation
    - operations contained in `admin/db_manage.py`

### Migrating production
1. Run git pull on master.
2. Backup the production database
  Before applying any migrations, create a backup of the live database:
    `
    pg_dump -U <db_user> -h <db_host> -d <db_name> > backup.sql
    `
3. Again prepare `FLASK_SQLALCHEMY_DATABASE_URI` like above and use it together with each `flask db` command.
4. Applying the migration in production
    There are two options for applying the migration:

    - Option 1: Execute from outside the Docker container

      `
      FLASK_SQLALCHEMY_DATABASE_URI=postgresql+psycopg://user:password@<db_container_ip>:5432/db_name flask --app yaptide.application db upgrade
      `
    - Option 2: Execute from inside the Flask container

    Access the container and run the upgrade:
      `
      docker exec -it <flask_container> bash
      `
      `
      FLASK_SQLALCHEMY_DATABASE_URI=postgresql+psycopg://user:password@<db_container_ip>:5432/db_name flask --app yaptide.application db upgrade
      `
    Rollback strategy
    In case of any issues, you can revert the changes by running:
      `
      flask --app yaptide.application db downgrade
      `
    Post-migration testing
    Perform manual tests on the production system:

    - Verify logging in and out.
    - Check simulation submissions.
    - Ensure any functionality affected by the migration is working.


5. In case of restoring database from backup, run:
    - `
      psql -U <db_user> -h <db_host> -c "DROP DATABASE IF EXISTS <db_name>;"
      `

    - `
      psql -U <db_user> -h <db_host> -c "CREATE DATABASE <db_name>;"
      `

    - `
      psql -U <db_user> -h <db_host> -d <db_name> -f backup.sql
      `



### Using pgadminer
Pgadminer is tool that lets user browse database through graphical interface. It can help with veryfication, testing and troubleshooting during migration. To run pgadminer alongside other containers run script: `scripts/start_with_docker_develop.sh`. If executed locally it can be accessed from browser with address: `localhost:9999`. When running from remote the tunnel connection is requred. Run:
```
ssh -L 9999:localhost:9999 <remote_host>
```
then open in browser localhost:9999. Log in with credentials set in compose file. rightclick on servers -> register -> server -> fill necessary fields general and connection tabs.
