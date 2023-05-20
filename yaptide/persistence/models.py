from datetime import datetime
from enum import Enum

import gzip
import json

from sqlalchemy import Column
from sqlalchemy.orm import relationship
from sqlalchemy.sql.functions import now
from yaptide.persistence.database import db

from werkzeug.security import generate_password_hash, check_password_hash


class UserModel(db.Model):
    """User model"""

    __tablename__ = 'User'
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    username: Column[str] = db.Column(db.String, nullable=False, unique=True)
    password_hash: Column[str] = db.Column(db.String, nullable=False)
    simulations = relationship("SimulationModel")
    clusters = relationship("ClusterModel")

    def set_password(self, password: str):
        """Sets hashed password"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Checks password correctness"""
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f'User #{self.id} {self.username}'


class ClusterModel(db.Model):
    """Cluster info for specific user"""

    __tablename__ = 'Cluster'
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    user_id: Column[int] = db.Column(db.Integer, db.ForeignKey('User.id'))
    cluster_name: Column[str] = db.Column(db.String, nullable=False)
    cluster_username: Column[str] = db.Column(db.String, nullable=False)
    cluster_ssh_key: Column[str] = db.Column(db.String, nullable=False)


class SimulationModel(db.Model):
    """Simulation model"""

    # Still needs to be done:
    # - move enums to a separate file
    # - use DBEnum for enums
    # - use auto for enums

    class Platform(Enum):
        """Platform specification"""

        DIRECT = "DIRECT"
        BATCH = "BATCH"

    class JobState(Enum):
        """Job state types - move it to more utils like place in future"""

        PENDING = "PENDING"
        RUNNING = "RUNNING"
        CANCELLED = "CANCELLED"
        COMPLETED = "COMPLETED"
        FAILED = "FAILED"

    class InputType(Enum):
        """Input type specification"""

        EDITOR = "EDITOR"
        FILES = "FILES"

    class SimType(Enum):
        """Simulation type specification"""

        SHIELDHIT = "shieldhit"
        TOPAS = "topas"
        FLUKA = "fluka"
        DUMMY = "dummy"

    __tablename__ = 'Simulation'

    id: Column[int] = db.Column(db.Integer, primary_key=True)

    # we encode job_id as string, because that is the convention in Celery queue and in SLURM
    # currently for Celery one simulation is one job, but in future we might want to split it into multiple tasks
    # example celery job_ids are: 1a2b3c4d-5e6f-7g8h-9i0j-1k2l3m4n5o6p
    # example SLURM job_ids are: 12345678
    job_id: Column[str] = db.Column(db.String, nullable=True, unique=True, doc="Simulation job ID")

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
                                       default='PENDING',
                                       doc="Simulation state (i.e. 'pending', 'running', 'completed', 'failed')")
    update_key_hash: Column[str] = db.Column(db.String,
                                             doc="Update key shared by tasks granting access to update themselves")
    tasks = relationship("TaskModel")
    results = relationship("EstimatorModel")

    def set_update_key(self, update_key: str):
        """Sets hashed update key"""
        self.update_key_hash = generate_password_hash(update_key)

    def check_update_key(self, update_key: str) -> bool:
        """Checks update key correctness"""
        return check_password_hash(self.update_key_hash, update_key)

    def update_state(self, update_dict: dict) -> bool:
        """
        Updating database is more costly than a simple query.
        Therefore we check first if update is needed and
        perform it only for such fields which exists and which have updated values.
        Returns bool value telling if it is required to commit changes to db.
        """
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


class TaskModel(db.Model):
    """Simulation task model"""

    __tablename__ = 'Task'
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    simulation_id: Column[int] = db.Column(db.Integer,
                                           db.ForeignKey('Simulation.id'),
                                           doc="Simulation job ID (foreign key)")

    # we encode task_id as string, because that is the convention in Celery queue and in SLURM
    # currently for Celery one simulation is one job, but in future we might want to split it into multiple tasks
    # example celery job_ids are: 1a2b3c4d-5e6f-7g8h-9i0j-1k2l3m4n5o6p
    # example SLURM job_ids are: 12345678_12
    task_id: Column[str] = db.Column(db.String, nullable=False, unique=True, doc="Task ID")
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
                                        default='PENDING',
                                        doc="Task state (i.e. 'pending', 'running', 'completed', 'failed')")
    estimated_time: Column[int] = db.Column(db.Integer, nullable=True, doc="Estimated time in seconds")
    start_time: Column[datetime] = db.Column(db.DateTime(timezone=True), nullable=True, doc="Task start time")
    end_time: Column[datetime] = db.Column(db.DateTime(timezone=True), nullable=True, doc="Task end time")
    last_update_time: Column[datetime] = db.Column(
        db.DateTime(timezone=True),
        default=now(),
        doc="Task last update time")

    def update_state(self, update_dict: dict):
        """
        Updating database is more costly than a simple query.
        Therefore we check first if update is needed and
        perform it only for such fields which exists and which have updated values.
        """
        if "requested_primaries" in update_dict and self.requested_primaries != update_dict["requested_primaries"]:
            self.requested_primaries = update_dict["requested_primaries"]
        if "simulated_primaries" in update_dict and self.simulated_primaries != update_dict["simulated_primaries"]:
            self.simulated_primaries = update_dict["simulated_primaries"]
        if "task_state" in update_dict and self.task_state != update_dict["task_state"]:
            self.task_state = update_dict["task_state"]
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


class InputModel(db.Model):
    """Simulation inputs model"""

    __tablename__ = 'Input'
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    simulation_id: Column[int] = db.Column(db.Integer, db.ForeignKey('Simulation.id'))
    compressed_data: Column[str] = db.Column(db.Text)

    @property
    def data(self):
        if self.compressed_data is not None:
            # Decompress the data
            decompressed_data = gzip.decompress(self.compressed_data).decode('utf-8')
            # Deserialize the JSON
            return json.loads(decompressed_data)
        return None

    @data.setter
    def data(self, value):
        if value is not None:
            # Serialize the JSON
            serialized_data = json.dumps(value)
            # Compress the data
            self.compressed_data = gzip.compress(serialized_data.encode('utf-8'))


class EstimatorModel(db.Model):
    """Simulation single estimator model"""

    __tablename__ = 'Estimator'
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    simulation_id: Column[int] = db.Column(db.Integer, db.ForeignKey('Simulation.id'), nullable=False)
    name: Column[str] = db.Column(db.String, nullable=False, doc="Estimator name")
    compressed_data: Column[str] = db.Column(db.Text, doc="Estimator metadata")

    @property
    def data(self):
        if self.compressed_data is not None:
            # Decompress the data
            decompressed_data = gzip.decompress(self.compressed_data).decode('utf-8')
            # Deserialize the JSON
            return json.loads(decompressed_data)
        return None

    @data.setter
    def data(self, value):
        if value is not None:
            # Serialize the JSON
            serialized_data = json.dumps(value)
            # Compress the data
            self.compressed_data = gzip.compress(serialized_data.encode('utf-8'))


class PageModel(db.Model):
    """Estimator single page model"""

    __tablename__ = 'Page'
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    estimator_id: Column[int] = db.Column(db.Integer, db.ForeignKey('Estimator.id'), nullable=False)
    page_number: Column[int] = db.Column(db.String, nullable=False, doc="Page number")
    compressed_data: Column[str] = db.Column(db.Text, doc="Page json object - data, axes and metadata")

    @property
    def data(self):
        if self.compressed_data is not None:
            # Decompress the data
            decompressed_data = gzip.decompress(self.compressed_data).decode('utf-8')
            # Deserialize the JSON
            return json.loads(decompressed_data)
        return None

    @data.setter
    def data(self, value):
        if value is not None:
            # Serialize the JSON
            serialized_data = json.dumps(value)
            # Compress the data
            self.compressed_data = gzip.compress(serialized_data.encode('utf-8'))


class LogfilesModel(db.Model):
    """"""

    __tablename__ = 'Logfiles'
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    simulation_id: Column[int] = db.Column(db.Integer, db.ForeignKey('Simulation.id'), nullable=False)
    compressed_data: Column[str] = db.Column(db.Text, doc="Json object containing logfiles")

    @property
    def data(self):
        if self.compressed_data is not None:
            # Decompress the data
            decompressed_data = gzip.decompress(self.compressed_data).decode('utf-8')
            # Deserialize the JSON
            return json.loads(decompressed_data)
        return None

    @data.setter
    def data(self, value):
        if value is not None:
            # Serialize the JSON
            serialized_data = json.dumps(value)
            # Compress the data
            self.compressed_data = gzip.compress(serialized_data.encode('utf-8'))



def create_models():
    """Function creating database's models"""
    db.create_all()
