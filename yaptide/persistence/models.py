# ---------- IMPORTANT ------------
# Read documentation in persistency.md. It contains information about database development with flask-migrate.

import gzip
import json
from datetime import datetime

import flask_migrate
from sqlalchemy import DDL, Column, UniqueConstraint, event, inspect
from sqlalchemy.orm import relationship
from sqlalchemy.sql.functions import now
from werkzeug.security import check_password_hash, generate_password_hash

from yaptide.persistence.database import db
from yaptide.utils.enums import EntityState, PlatformType


class UserModel(db.Model):
    """User model"""

    __tablename__ = "User"
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    username: Column[str] = db.Column(db.String, nullable=False)
    auth_provider: Column[str] = db.Column(db.String, nullable=False)
    simulations = relationship("SimulationModel")

    __table_args__ = (UniqueConstraint("username", "auth_provider", name="_username_provider_uc"),)

    __mapper_args__ = {"polymorphic_identity": "User", "polymorphic_on": auth_provider, "with_polymorphic": "*"}

    def __repr__(self) -> str:
        return f"User #{self.id} {self.username}"


class YaptideUserModel(UserModel, db.Model):
    """Yaptide user model"""

    __tablename__ = "YaptideUser"
    id: Column[int] = db.Column(db.Integer, db.ForeignKey("User.id", ondelete="CASCADE"), primary_key=True)
    password_hash: Column[str] = db.Column(db.String, nullable=False)

    __mapper_args__ = {"polymorphic_identity": "YaptideUser", "polymorphic_load": "inline"}

    def set_password(self, password: str):
        """Sets hashed password"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Checks password correctness"""
        return check_password_hash(self.password_hash, password)


class KeycloakUserModel(UserModel, db.Model):
    """PLGrid user model"""

    __tablename__ = "KeycloakUser"
    id: Column[int] = db.Column(db.Integer, db.ForeignKey("User.id", ondelete="CASCADE"), primary_key=True)
    cert: Column[str] = db.Column(db.String, nullable=True)
    private_key: Column[str] = db.Column(db.String, nullable=True)

    __mapper_args__ = {"polymorphic_identity": "KeycloakUser", "polymorphic_load": "inline"}


class UserActivityModel(db.Model):
    """When a user last followed the status of their simulations: a stream open or a status asked for; the engine
    reads the progress of the others' HPC simulations less often
    """

    __tablename__ = "UserActivity"
    user_id: Column[int] = db.Column(db.Integer, db.ForeignKey("User.id", ondelete="CASCADE"), primary_key=True)
    seen_at: Column[datetime] = db.Column(db.DateTime(timezone=True), nullable=False)


class ClusterModel(db.Model):
    """Cluster info for specific user"""

    __tablename__ = "Cluster"
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    cluster_name: Column[str] = db.Column(db.String, nullable=False)
    busy_until: Column[datetime] = db.Column(
        db.DateTime(timezone=True),
        nullable=True,
        doc="Set while the cluster's SLURM does not answer: the engine tries to submit to it again then",
    )
    notice: Column[str] = db.Column(
        db.Text, nullable=True, doc="What the cluster's admins said when its login node last closed the connection"
    )
    simulations = relationship("BatchSimulationModel")


class SimulationModel(db.Model):
    """Simulation model"""

    __tablename__ = "Simulation"

    id: Column[int] = db.Column(db.Integer, primary_key=True)

    job_id: Column[str] = db.Column(db.String, nullable=False, unique=True, doc="Simulation job ID")

    user_id: Column[int] = db.Column(db.Integer, db.ForeignKey("User.id"), doc="User ID")
    start_time: Column[datetime] = db.Column(db.DateTime(timezone=True), default=now(), doc="Submission time")
    end_time: Column[datetime] = db.Column(
        db.DateTime(timezone=True), nullable=True, doc="Job end time (including merging)"
    )
    title: Column[str] = db.Column(db.String, nullable=False, doc="Job title")
    platform: Column[str] = db.Column(db.String, nullable=False, doc="Execution platform name (i.e. 'direct', 'batch')")
    input_type: Column[str] = db.Column(
        db.String, nullable=False, doc="Input type (i.e. 'yaptide_project', 'input_files')"
    )
    sim_type: Column[str] = db.Column(
        db.String, nullable=False, doc="Simulator type (i.e. 'shieldhit', 'topas', 'fluka')"
    )
    job_state: Column[str] = db.Column(
        db.String,
        nullable=False,
        default=EntityState.UNKNOWN.value,
        doc="Simulation state (i.e. 'pending', 'running', 'completed', 'failed')",
    )
    partial_primaries: Column[int] = db.Column(
        db.BigInteger, nullable=True, doc="Primaries the stored results cover while the simulation runs"
    )
    partial_time: Column[datetime] = db.Column(
        db.DateTime(timezone=True), nullable=True, doc="When the partial results were stored"
    )
    progress_revision: Column[int] = db.Column(
        db.BigInteger,
        nullable=False,
        default=0,
        server_default="0",
        doc="Counts the saves of the tasks' progress, so that each save wakes the streams of the simulation once",
    )

    # the database removes the children (ON DELETE CASCADE); loading them first would read every result page
    tasks = relationship("TaskModel", cascade="delete", passive_deletes=True)
    estimators = relationship("EstimatorModel", cascade="delete", passive_deletes=True)
    inputs = relationship("InputModel", cascade="delete", passive_deletes=True)
    logfiles = relationship("LogfilesModel", cascade="delete", passive_deletes=True)

    __mapper_args__ = {"polymorphic_identity": "Simulation", "polymorphic_on": platform, "with_polymorphic": "*"}

    def update_state(self, update_dict: dict) -> bool:
        """
        Updating database is more costly than a simple query.
        Therefore we check first if update is needed and
        perform it only for such fields which exists and which have updated values.
        Returns bool value telling if it is required to commit changes to db.
        """
        if self.job_state in (EntityState.COMPLETED.value, EntityState.FAILED.value, EntityState.CANCELED.value):
            return False
        db_commit_required = False
        if "job_state" in update_dict and self.job_state != update_dict["job_state"]:
            self.job_state = update_dict["job_state"]
            db_commit_required = True
        # Here we have a special case, `end_time` can be set only once
        # therefore we update it only if it not set previously (`self.end_time is None`)
        # and if update was requested (`"end_time" in update_dict`)
        if "end_time" in update_dict and self.end_time is None:
            # a convertion from string to datetime is needed, as in the POST payload end_time comes in string format
            self.end_time = datetime.strptime(update_dict["end_time"], "%Y-%m-%d %H:%M:%S.%f")
            db_commit_required = True
        return db_commit_required


# Postgres tells the engine (yaptide/engine) about the simulations it has to start or stop - direct ones it runs,
# HPC ones it submits and cancels: every change, from any route, script or psql, sends the event when its
# transaction commits. The migrations 9e1d2f3a4b5c and 4b8e2c6d1a7f create the same for databases created before.
ENGINE_CHANNEL = "yaptide_engine"
NOTIFY_ENGINE_FUNCTION = DDL(
    """
CREATE OR REPLACE FUNCTION notify_engine() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.platform IN ('DIRECT', 'BATCH') THEN
            PERFORM pg_notify(
                'yaptide_engine',
                json_build_object('simulation', OLD.id, 'platform', OLD.platform, 'event', 'DELETED')::text
            );
        END IF;
        RETURN OLD;
    END IF;
    IF NEW.platform IN ('DIRECT', 'BATCH') AND NEW.job_state IN ('PENDING', 'CANCELED') THEN
        PERFORM pg_notify(
            'yaptide_engine',
            json_build_object('simulation', NEW.id, 'platform', NEW.platform, 'event', NEW.job_state)::text
        );
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql
"""
)
NOTIFY_ENGINE_TRIGGER = DDL(
    """
CREATE OR REPLACE TRIGGER simulation_engine_events AFTER INSERT OR UPDATE OF job_state OR DELETE ON "Simulation"
FOR EACH ROW EXECUTE FUNCTION notify_engine()
"""
)
# the open event streams of a user (yaptide/routes/events_routes.py) learn about a new simulation, a new state, partial
# results or a save of the tasks' progress; the migration 2a6c8e0b4d17 creates the same for databases created before
SIMULATION_CHANNEL = "yaptide_simulation"
NOTIFY_SIMULATION_FUNCTION = DDL(
    """
CREATE OR REPLACE FUNCTION notify_simulation() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' OR OLD.job_state IS DISTINCT FROM NEW.job_state
            OR OLD.partial_primaries IS DISTINCT FROM NEW.partial_primaries
            OR OLD.progress_revision IS DISTINCT FROM NEW.progress_revision THEN
        PERFORM pg_notify('yaptide_simulation', json_build_object('simulation', NEW.id, 'user', NEW.user_id)::text);
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql
"""
)
NOTIFY_SIMULATION_TRIGGER = DDL(
    """
CREATE OR REPLACE TRIGGER simulation_stream_events
AFTER INSERT OR UPDATE OF job_state, partial_primaries, progress_revision ON "Simulation"
FOR EACH ROW EXECUTE FUNCTION notify_simulation()
"""
)
NOTIFY_STATEMENTS = (
    NOTIFY_ENGINE_FUNCTION,
    NOTIFY_ENGINE_TRIGGER,
    NOTIFY_SIMULATION_FUNCTION,
    NOTIFY_SIMULATION_TRIGGER,
)
for statement in NOTIFY_STATEMENTS:
    event.listen(SimulationModel.__table__, "after_create", statement.execute_if(dialect="postgresql"))


class CelerySimulationModel(SimulationModel):
    """Celery simulation model"""

    __tablename__ = "CelerySimulation"
    id: Column[int] = db.Column(db.Integer, db.ForeignKey("Simulation.id", ondelete="CASCADE"), primary_key=True)
    merge_id: Column[str] = db.Column(db.String, nullable=True, doc="Celery collect job ID")

    __mapper_args__ = {"polymorphic_identity": PlatformType.DIRECT.value, "polymorphic_load": "inline"}


class BatchSimulationModel(SimulationModel):
    """Batch simulation model"""

    __tablename__ = "BatchSimulation"
    id: Column[int] = db.Column(db.Integer, db.ForeignKey("Simulation.id", ondelete="CASCADE"), primary_key=True)
    cluster_id: Column[int] = db.Column(db.Integer, db.ForeignKey("Cluster.id"), nullable=False, doc="Cluster ID")
    job_dir: Column[str] = db.Column(db.String, nullable=True, doc="Simulation folder name")
    array_id: Column[int] = db.Column(db.Integer, nullable=True, doc="Batch array jon ID")
    collect_id: Column[int] = db.Column(db.Integer, nullable=True, doc="Batch collect job ID")

    __mapper_args__ = {"polymorphic_identity": PlatformType.BATCH.value, "polymorphic_load": "inline"}

    def update_state(self, update_dict):
        """Used to update fields in BatchSimulation. Returns boolean value if commit to database is reuqired"""
        db_commit_required = super().update_state(update_dict)
        if "job_dir" in update_dict and self.job_dir != update_dict["job_dir"]:
            self.job_dir = update_dict["job_dir"]
            db_commit_required = True
        if "array_id" in update_dict and self.array_id != update_dict["array_id"]:
            self.array_id = update_dict["array_id"]
            db_commit_required = True
        if "collect_id" in update_dict and self.collect_id != update_dict["collect_id"]:
            self.collect_id = update_dict["collect_id"]
            db_commit_required = True
        return db_commit_required


def allowed_state_change(current_state: str, next_state: str):
    """Ensures that no such change like Completed -> Canceled happens"""
    return not (
        current_state in [EntityState.FAILED.value, EntityState.COMPLETED.value]
        and next_state in [EntityState.CANCELED]
    )


def value_changed(current_value: str, new_value: str):
    """checks if value from update_dict differs from object in database"""
    return new_value and current_value != new_value


class TaskModel(db.Model):
    """Simulation task model"""

    __tablename__ = "Task"
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    simulation_id: Column[int] = db.Column(
        db.Integer, db.ForeignKey("Simulation.id", ondelete="CASCADE"), doc="Simulation job ID (foreign key)"
    )

    task_id: Column[int] = db.Column(db.Integer, nullable=False, doc="Task ID")
    requested_primaries: Column[int] = db.Column(
        db.Integer, nullable=False, default=0, doc="Requested number of primaries"
    )
    simulated_primaries: Column[int] = db.Column(
        db.Integer, nullable=False, default=0, doc="Simulated number of primaries"
    )
    task_state: Column[str] = db.Column(
        db.String,
        nullable=False,
        default=EntityState.PENDING.value,
        doc="Task state (i.e. 'pending', 'running', 'completed', 'failed')",
    )
    estimated_time: Column[int] = db.Column(db.Integer, nullable=True, doc="Estimated time in seconds")
    start_time: Column[datetime] = db.Column(db.DateTime(timezone=True), nullable=True, doc="Task start time")
    end_time: Column[datetime] = db.Column(db.DateTime(timezone=True), nullable=True, doc="Task end time")
    platform: Column[str] = db.Column(db.String, nullable=False, doc="Execution platform name (i.e. 'direct', 'batch')")
    last_update_time: Column[datetime] = db.Column(
        db.DateTime(timezone=True), default=now(), doc="Task last update time"
    )

    __table_args__ = (UniqueConstraint("simulation_id", "task_id", name="_simulation_id_task_id_uc"),)

    __mapper_args__ = {"polymorphic_identity": "Task", "polymorphic_on": platform, "with_polymorphic": "*"}

    def update_state(self, update_dict: dict):  # skipcq: PY-R1000
        """
        Updating database is more costly than a simple query.
        Therefore we check first if update is needed and
        perform it only for such fields which exists and which have updated values.
        """
        if self.task_state in (EntityState.COMPLETED.value, EntityState.FAILED.value, EntityState.CANCELED.value):
            return
        if value_changed(self.requested_primaries, update_dict.get("requested_primaries")):
            self.requested_primaries = update_dict["requested_primaries"]
        if value_changed(self.simulated_primaries, update_dict.get("simulated_primaries")):
            self.simulated_primaries = update_dict["simulated_primaries"]
        if value_changed(self.task_state, update_dict.get("task_state")) and allowed_state_change(
            self.task_state, update_dict["task_state"]
        ):
            self.task_state = update_dict["task_state"]
            if self.task_state == EntityState.COMPLETED.value:
                self.simulated_primaries = self.requested_primaries
        # Here we have a special case, `estimated_time` cannot be set when `end_time` is set - it is meaningless
        have_estim_time = "estimated_time" in update_dict and self.estimated_time != update_dict["estimated_time"]
        end_time_not_set = self.end_time is None
        if have_estim_time and end_time_not_set:
            self.estimated_time = update_dict["estimated_time"]
        if "start_time" in update_dict and self.start_time is None:
            # a convertion from string to datetime is needed, as in the POST payload start_time comes in string format
            self.start_time = datetime.strptime(update_dict["start_time"], "%Y-%m-%d %H:%M:%S.%f")
        # Here we have a special case, `end_time` can be set only once
        # therefore we update it only if it not set previously (`self.end_time is None`)
        # and if update was requested (`"end_time" in update_dict`)
        if "end_time" in update_dict and self.end_time is None:
            # a convertion from string to datetime is needed, as in the POST payload end_time comes in string format
            self.end_time = datetime.strptime(update_dict["end_time"], "%Y-%m-%d %H:%M:%S.%f")
            self.estimated_time = None
        self.last_update_time = now()

    def get_status_dict(self) -> dict:
        """Returns task information as a dictionary"""
        result = {
            "task_state": self.task_state,
            "requested_primaries": self.requested_primaries,
            "simulated_primaries": self.simulated_primaries,
            "last_update_time": self.last_update_time,
            "task_id": self.id,
        }
        if self.estimated_time:
            result["estimated_time"] = {
                "hours": self.estimated_time // 3600,
                "minutes": (self.estimated_time // 60) % 60,
                "seconds": self.estimated_time % 60,
            }
        if self.start_time:
            result["start_time"] = self.start_time
        if self.end_time:
            result["end_time"] = self.end_time
        return result


class CeleryTaskModel(TaskModel):
    """Celery task model"""

    __tablename__ = "CeleryTask"
    id: Column[int] = db.Column(db.Integer, db.ForeignKey("Task.id", ondelete="CASCADE"), primary_key=True)
    celery_id: Column[str] = db.Column(db.String, nullable=False, default="", doc="Celery task ID")

    def update_state(self, update_dict: dict):
        """Update method for CeleryTaskModel"""
        if "celery_id" in update_dict and self.celery_id != update_dict["celery_id"]:
            self.celery_id = update_dict["celery_id"]
        return super().update_state(update_dict)

    __mapper_args__ = {"polymorphic_identity": PlatformType.DIRECT.value, "polymorphic_load": "inline"}


class BatchTaskModel(TaskModel):
    """Batch task model"""

    __tablename__ = "BatchTask"
    id: Column[int] = db.Column(db.Integer, db.ForeignKey("Task.id", ondelete="CASCADE"), primary_key=True)

    __mapper_args__ = {"polymorphic_identity": PlatformType.BATCH.value, "polymorphic_load": "inline"}


def decompress(data: bytes):
    """Decompresses data and deserializes JSON"""
    data_to_unpack: str = "null"
    if data is not None:
        # Decompress the data
        decompressed_bytes: bytes = gzip.decompress(data)
        data_to_unpack = decompressed_bytes.decode("utf-8")
        # Deserialize the JSON
    return json.loads(data_to_unpack)


def compress(data) -> bytes:
    """Serializes JSON and compresses data"""
    compressed_bytes = b""
    if data is not None:
        # Serialize the JSON
        serialized_data: str = json.dumps(data)
        # Compress the data
        bytes_to_compress: bytes = serialized_data.encode("utf-8")
        compressed_bytes = gzip.compress(bytes_to_compress)
    return compressed_bytes


class InputModel(db.Model):
    """Simulation inputs model"""

    __tablename__ = "Input"
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    simulation_id: Column[int] = db.Column(db.Integer, db.ForeignKey("Simulation.id", ondelete="CASCADE"))
    compressed_data: Column[bytes] = db.Column(db.LargeBinary)

    @property
    def data(self):
        return decompress(self.compressed_data)

    @data.setter
    def data(self, value):
        if value is not None:
            self.compressed_data = compress(value)


class EstimatorModel(db.Model):
    """Simulation single estimator model"""

    __tablename__ = "Estimator"
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    simulation_id: Column[int] = db.Column(
        db.Integer, db.ForeignKey("Simulation.id", ondelete="CASCADE"), nullable=False
    )
    name: Column[str] = db.Column(db.String, nullable=False, doc="Human readable estimator name")
    file_name: Column[str] = db.Column(
        db.String, nullable=False, doc="Estimator name extracted from file generated by simulator"
    )
    compressed_data: Column[bytes] = db.Column(db.LargeBinary, doc="Estimator metadata")
    pages = relationship("PageModel", cascade="delete", passive_deletes=True, order_by="PageModel.page_number")

    @property
    def data(self):
        return decompress(self.compressed_data)

    @data.setter
    def data(self, value):
        if value is not None:
            self.compressed_data = compress(value)


class PageModel(db.Model):
    """Estimator single page model"""

    __tablename__ = "Page"
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    page_name: Column[str] = db.Column(db.String, nullable=False, doc="Page name")
    estimator_id: Column[int] = db.Column(db.Integer, db.ForeignKey("Estimator.id", ondelete="CASCADE"), nullable=False)
    page_number: Column[int] = db.Column(db.Integer, nullable=False, doc="Page number")
    compressed_data: Column[bytes] = db.Column(db.LargeBinary, doc="Page json object - data, axes and metadata")
    page_dimension: Column[int] = db.Column(db.Integer, nullable=False, doc="Dimension of data")
    # set when the page is in object storage; then compressed_data is empty
    stored_object = relationship("PageObjectModel", uselist=False, cascade="all, delete-orphan", lazy="joined")

    @property
    def data(self):
        return decompress(self.compressed_data)

    @data.setter
    def data(self, value):
        if value is not None:
            self.compressed_data = compress(value)


class PageObjectModel(db.Model):
    """Where a result page is kept in object storage"""

    __tablename__ = "PageObject"
    page_id: Column[int] = db.Column(db.Integer, db.ForeignKey("Page.id", ondelete="CASCADE"), primary_key=True)
    key: Column[str] = db.Column(db.String, nullable=False, doc="Object key in the results bucket")
    size: Column[int] = db.Column(db.Integer, nullable=False, doc="Stored size in bytes")
    format: Column[str] = db.Column(db.String, nullable=False, doc="How the page is encoded in the object")


class LogfilesModel(db.Model):
    """Simulation logfiles model"""

    __tablename__ = "Logfiles"
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    simulation_id: Column[int] = db.Column(
        db.Integer, db.ForeignKey("Simulation.id", ondelete="CASCADE"), nullable=False
    )
    compressed_data: Column[bytes] = db.Column(db.LargeBinary, doc="Json object containing logfiles")

    @property
    def data(self):
        return decompress(self.compressed_data)

    @data.setter
    def data(self, value):
        if value is not None:
            self.compressed_data = compress(value)


def prepare_database():
    """Brings the database to the current models, to be used with Flask app context

    A database under migrations gets the ones it lacks. A new one, or one whose tables were only ever created from
    the models, gets the missing tables and is marked as up to date, so that later migrations apply to it.
    Creating tables before migrating would make a migration that creates a table fail, so the two never mix.
    """
    if inspect(db.engine).has_table("alembic_version"):
        flask_migrate.upgrade()
    else:
        db.create_all()
        if db.engine.dialect.name == "postgresql":
            # create_all skips existing tables, and with them their after_create triggers; the stamp below skips
            # their migrations, so a database whose tables were only ever created from the models gets them here
            with db.engine.begin() as connection:
                for notify_statement in NOTIFY_STATEMENTS:
                    connection.execute(notify_statement)
        flask_migrate.stamp()
