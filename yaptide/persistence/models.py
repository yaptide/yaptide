# ---------- IMPORTANT ------------
# Read documentation in persistency.md. It contains information about database development with flask-migrate.

import gzip
import json
from datetime import datetime

from sqlalchemy import Column, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql.functions import now
from werkzeug.security import check_password_hash, generate_password_hash

from yaptide.persistence.database import db
from yaptide.utils.enums import EntityState, PlatformType


class UserModel(db.Model):
    """User model"""

    __tablename__ = 'User'
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    username: Column[str] = db.Column(db.String, nullable=False)
    auth_provider: Column[str] = db.Column(db.String, nullable=False)
    simulations = relationship("SimulationModel")

    __table_args__ = (UniqueConstraint('username', 'auth_provider', name='_username_provider_uc'), )

    __mapper_args__ = {"polymorphic_identity": "User", "polymorphic_on": auth_provider, "with_polymorphic": "*"}

    def __repr__(self) -> str:
        return f'User #{self.id} {self.username}'


class YaptideUserModel(UserModel, db.Model):
    """Yaptide user model"""

    __tablename__ = 'YaptideUser'
    id: Column[int] = db.Column(db.Integer, db.ForeignKey('User.id', ondelete="CASCADE"), primary_key=True)
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

    __tablename__ = 'KeycloakUser'
    id: Column[int] = db.Column(db.Integer, db.ForeignKey('User.id', ondelete="CASCADE"), primary_key=True)
    cert: Column[str] = db.Column(db.String, nullable=True)
    private_key: Column[str] = db.Column(db.String, nullable=True)

    __mapper_args__ = {"polymorphic_identity": "KeycloakUser", "polymorphic_load": "inline"}


class ClusterModel(db.Model):
    """Cluster info for specific user"""

    __tablename__ = 'Cluster'
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    cluster_name: Column[str] = db.Column(db.String, nullable=False)
    simulations = relationship("BatchSimulationModel")


class SimulationModel(db.Model):
    """Simulation model"""

    __tablename__ = 'Simulation'

    id: Column[int] = db.Column(db.Integer, primary_key=True)

    job_id: Column[str] = db.Column(db.String, nullable=False, unique=True, doc="Simulation job ID")

    user_id: Column[int] = db.Column(db.Integer, db.ForeignKey('User.id'), doc="User ID")
    start_time: Column[datetime] = db.Column(db.DateTime(timezone=True), default=now(), doc="Submission time")
    end_time: Column[datetime] = db.Column(db.DateTime(timezone=True),
                                           nullable=True,
                                           doc="Job end time (including merging)")
    title: Column[str] = db.Column(db.String, nullable=False, doc="Job title")
    platform: Column[str] = db.Column(db.String, nullable=False, doc="Execution platform name (i.e. 'direct', 'batch')")
    input_type: Column[str] = db.Column(db.String,
                                        nullable=False,
                                        doc="Input type (i.e. 'yaptide_project', 'input_files')")
    sim_type: Column[str] = db.Column(db.String,
                                      nullable=False,
                                      doc="Simulator type (i.e. 'shieldhit', 'topas', 'fluka')")
    job_state: Column[str] = db.Column(db.String,
                                       nullable=False,
                                       default=EntityState.UNKNOWN.value,
                                       doc="Simulation state (i.e. 'pending', 'running', 'completed', 'failed')")

    tasks = relationship("TaskModel", cascade="delete")
    estimators = relationship("EstimatorModel", cascade="delete")
    inputs = relationship("InputModel", cascade="delete")
    logfiles = relationship("LogfilesModel", cascade="delete")

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
            self.end_time = datetime.strptime(update_dict["end_time"], '%Y-%m-%d %H:%M:%S.%f')
            db_commit_required = True
        return db_commit_required


class CelerySimulationModel(SimulationModel):
    """Celery simulation model"""

    __tablename__ = 'CelerySimulation'
    id: Column[int] = db.Column(db.Integer, db.ForeignKey('Simulation.id', ondelete="CASCADE"), primary_key=True)
    merge_id: Column[str] = db.Column(db.String, nullable=True, doc="Celery collect job ID")

    __mapper_args__ = {"polymorphic_identity": PlatformType.DIRECT.value, "polymorphic_load": "inline"}


class BatchSimulationModel(SimulationModel):
    """Batch simulation model"""

    __tablename__ = 'BatchSimulation'
    id: Column[int] = db.Column(db.Integer, db.ForeignKey('Simulation.id', ondelete="CASCADE"), primary_key=True)
    cluster_id: Column[int] = db.Column(db.Integer, db.ForeignKey('Cluster.id'), nullable=False, doc="Cluster ID")
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
    return not (current_state in [EntityState.FAILED.value, EntityState.COMPLETED.value]
                and next_state in [EntityState.CANCELED])


def value_changed(current_value: str, new_value: str):
    """checks if value from update_dict differs from object in database"""
    return new_value and current_value != new_value


class TaskModel(db.Model):
    """Simulation task model"""

    __tablename__ = 'Task'
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    simulation_id: Column[int] = db.Column(db.Integer,
                                           db.ForeignKey('Simulation.id', ondelete="CASCADE"),
                                           doc="Simulation job ID (foreign key)")

    task_id: Column[int] = db.Column(db.Integer, nullable=False, doc="Task ID")
    requested_primaries: Column[int] = db.Column(db.Integer,
                                                 nullable=False,
                                                 default=0,
                                                 doc="Requested number of primaries")
    simulated_primaries: Column[int] = db.Column(db.Integer,
                                                 nullable=False,
                                                 default=0,
                                                 doc="Simulated number of primaries")
    task_state: Column[str] = db.Column(db.String,
                                        nullable=False,
                                        default=EntityState.PENDING.value,
                                        doc="Task state (i.e. 'pending', 'running', 'completed', 'failed')")
    estimated_time: Column[int] = db.Column(db.Integer, nullable=True, doc="Estimated time in seconds")
    start_time: Column[datetime] = db.Column(db.DateTime(timezone=True), nullable=True, doc="Task start time")
    end_time: Column[datetime] = db.Column(db.DateTime(timezone=True), nullable=True, doc="Task end time")
    platform: Column[str] = db.Column(db.String, nullable=False, doc="Execution platform name (i.e. 'direct', 'batch')")
    last_update_time: Column[datetime] = db.Column(db.DateTime(timezone=True),
                                                   default=now(),
                                                   doc="Task last update time")

    __table_args__ = (UniqueConstraint('simulation_id', 'task_id', name='_simulation_id_task_id_uc'), )

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
                self.task_state, update_dict["task_state"]):
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
            self.start_time = datetime.strptime(update_dict["start_time"], '%Y-%m-%d %H:%M:%S.%f')
        # Here we have a special case, `end_time` can be set only once
        # therefore we update it only if it not set previously (`self.end_time is None`)
        # and if update was requested (`"end_time" in update_dict`)
        if "end_time" in update_dict and self.end_time is None:
            # a convertion from string to datetime is needed, as in the POST payload end_time comes in string format
            self.end_time = datetime.strptime(update_dict["end_time"], '%Y-%m-%d %H:%M:%S.%f')
            self.estimated_time = None
        self.last_update_time = now()

    def get_status_dict(self) -> dict:
        """Returns task information as a dictionary"""
        result = {
            "task_state": self.task_state,
            "requested_primaries": self.requested_primaries,
            "simulated_primaries": self.simulated_primaries,
            "last_update_time": self.last_update_time,
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

    __tablename__ = 'CeleryTask'
    id: Column[int] = db.Column(db.Integer, db.ForeignKey('Task.id', ondelete="CASCADE"), primary_key=True)
    celery_id: Column[str] = db.Column(db.String, nullable=False, default="", doc="Celery task ID")
    sim_pid: Column[int] = db.Column(db.Integer,
                                     nullable=True,
                                     doc='Id of simulation process used to communicate with shieldhit process')
    path_to_sim: Column[str] = db.Column(db.String,
                                         nullable=True,
                                         doc='Path to simulation input and output files in tmp directory')

    def update_state(self, update_dict: dict):
        """Update method for CeleryTaskModel"""
        if "celery_id" in update_dict and self.celery_id != update_dict["celery_id"]:
            self.celery_id = update_dict["celery_id"]
        return super().update_state(update_dict)

    __mapper_args__ = {"polymorphic_identity": PlatformType.DIRECT.value, "polymorphic_load": "inline"}


class BatchTaskModel(TaskModel):
    """Batch task model"""

    __tablename__ = 'BatchTask'
    id: Column[int] = db.Column(db.Integer, db.ForeignKey('Task.id', ondelete="CASCADE"), primary_key=True)

    __mapper_args__ = {"polymorphic_identity": PlatformType.BATCH.value, "polymorphic_load": "inline"}


def decompress(data: bytes):
    """Decompresses data and deserializes JSON"""
    data_to_unpack: str = 'null'
    if data is not None:
        # Decompress the data
        decompressed_bytes: bytes = gzip.decompress(data)
        data_to_unpack = decompressed_bytes.decode('utf-8')
        # Deserialize the JSON
    return json.loads(data_to_unpack)


def compress(data) -> bytes:
    """Serializes JSON and compresses data"""
    compressed_bytes = b''
    if data is not None:
        # Serialize the JSON
        serialized_data: str = json.dumps(data)
        # Compress the data
        bytes_to_compress: bytes = serialized_data.encode('utf-8')
        compressed_bytes = gzip.compress(bytes_to_compress)
    return compressed_bytes


class InputModel(db.Model):
    """Simulation inputs model"""

    __tablename__ = 'Input'
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    simulation_id: Column[int] = db.Column(db.Integer, db.ForeignKey('Simulation.id', ondelete="CASCADE"))
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

    __tablename__ = 'Estimator'
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    simulation_id: Column[int] = db.Column(db.Integer,
                                           db.ForeignKey('Simulation.id', ondelete="CASCADE"),
                                           nullable=False)
    name: Column[str] = db.Column(db.String, nullable=False, doc="Human readable estimator name")
    file_name: Column[str] = db.Column(db.String,
                                       nullable=False,
                                       doc="Estimator name extracted from file generated by simulator")
    compressed_data: Column[bytes] = db.Column(db.LargeBinary, doc="Estimator metadata")
    pages = relationship("PageModel", cascade="delete")

    @property
    def data(self):
        return decompress(self.compressed_data)

    @data.setter
    def data(self, value):
        if value is not None:
            self.compressed_data = compress(value)


class PageModel(db.Model):
    """Estimator single page model"""

    __tablename__ = 'Page'
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    page_name: Column[str] = db.Column(db.String, nullable=False, doc="Page name")
    estimator_id: Column[int] = db.Column(db.Integer, db.ForeignKey('Estimator.id', ondelete="CASCADE"), nullable=False)
    page_number: Column[int] = db.Column(db.Integer, nullable=False, doc="Page number")
    compressed_data: Column[bytes] = db.Column(db.LargeBinary, doc="Page json object - data, axes and metadata")
    page_dimension: Column[int] = db.Column(db.Integer, nullable=False, doc="Dimension of data")

    @property
    def data(self):
        return decompress(self.compressed_data)

    @data.setter
    def data(self, value):
        if value is not None:
            self.compressed_data = compress(value)


class LogfilesModel(db.Model):
    """Simulation logfiles model"""

    __tablename__ = 'Logfiles'
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    simulation_id: Column[int] = db.Column(db.Integer,
                                           db.ForeignKey('Simulation.id', ondelete="CASCADE"),
                                           nullable=False)
    compressed_data: Column[bytes] = db.Column(db.LargeBinary, doc="Json object containing logfiles")

    @property
    def data(self):
        return decompress(self.compressed_data)

    @data.setter
    def data(self, value):
        if value is not None:
            self.compressed_data = compress(value)


def create_all():
    """Creates all tables, to be used with Flask app context."""
    db.create_all()
