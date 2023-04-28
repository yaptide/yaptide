from datetime import datetime
from enum import Enum

from sqlalchemy import Column
from yaptide.persistence.database import db

from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

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

    # TODO: move enums to a separate file
    # TODO: use DBEnum for enums
    # TODO: use auto for enums

    class Platform(Enum):
        """Platform specification"""

        DIRECT = "DIRECT"
        BATCH = "BATCH"

    class JobStatus(Enum):
        """Job status types - move it to more utils like place in future"""

        PENDING = "PENDING"
        RUNNING = "RUNNING"
        CANCELLED = "CANCELLED"
        COMPLETED = "COMPLETED"
        FAILED = "FAILED"

    class InputType(Enum):
        """Input type specification"""

        YAPTIDE_PROJECT = "YAPTIDE_PROJECT"
        INPUT_FILES = "INPUT_FILES"

    class SimType(Enum):
        """Simulation type specification"""

        SHIELDHIT = "SHIELDHIT"
        TOPAS = "TOPAS"
        FLUKA = "FLUKA"
        DUMMY = "DUMMY"

    __tablename__ = 'Simulation'
    
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    
    # we encode job_id as string, because that is the convention in Celery queue and in SLURM
    # currently for Celery one simulation is one job, but in future we might want to split it into multiple tasks
    # example celery job_ids are: 1a2b3c4d-5e6f-7g8h-9i0j-1k2l3m4n5o6p
    # example SLURM job_ids are: 12345678
    job_id: Column[str] = db.Column(db.String, nullable=False, unique=True, doc="Simulation job ID")

    user_id: Column[int] = db.Column(db.Integer, db.ForeignKey('User.id'), doc="User ID")
    start_time: Column[datetime] = db.Column(db.DateTime(timezone=True), default=func.now(), doc="Submission time")
    end_time: Column[datetime] = db.Column(db.DateTime(timezone=True), nullable=True, doc="Job end time (including merging)")
    title: Column[str] = db.Column(db.String, nullable=False, default='', doc="Job title")
    platform: Column[str] = db.Column(db.String, nullable=False, doc="Execution platform name (i.e. 'direct', 'batch')")
    input_type: Column[str] = db.Column(db.String, nullable=False, doc="Input type (i.e. 'yaptide_project', 'input_files')")
    sim_type: Column[str] = db.Column(db.String, nullable=False, doc="Simulator type (i.e. 'shieldhit', 'topas', 'fluka')")
    status: Column[str] = db.Column(db.String, nullable=False, default='PENDING', doc="Simulation status (i.e. 'pending', 'running', 'completed', 'failed')")
    tasks = relationship("TaskModel")
    results = relationship("ResultModel")


class TaskModel(db.Model):
    """Simulation task model"""

    __tablename__ = 'Task'
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    simulation_id: Column[int] = db.Column(db.Integer, db.ForeignKey('Simulation.id'), doc="Simulation job ID (foreign key)")

    # we encode task_id as string, because that is the convention in Celery queue and in SLURM
    # currently for Celery one simulation is one job, but in future we might want to split it into multiple tasks
    # example celery job_ids are: 1a2b3c4d-5e6f-7g8h-9i0j-1k2l3m4n5o6p
    # example SLURM job_ids are: 12345678_12
    task_id: Column[str] = db.Column(db.String, nullable=False, unique=True, doc="Task ID")
    requested_primaries: Column[int] = db.Column(db.Integer, nullable=False, default=0, doc="Requested number of primaries")
    simulated_primaries: Column[int] = db.Column(db.Integer, nullable=False, default=0, doc="Simulated number of primaries")
    status: Column[str] = db.Column(db.String, nullable=False, default='PENDING', doc="Task status (i.e. 'pending', 'running', 'completed', 'failed')")
    estimated_time_seconds: Column[int] = db.Column(db.Integer, nullable=True, doc="Estimated time in seconds")
    start_time: Column[datetime] = db.Column(db.DateTime(timezone=True), default=func.now(), doc="Task start time")  # skipcq: PYL-E1102
    end_time: Column[datetime] = db.Column(db.DateTime(timezone=True), nullable=True, doc="Task end time")

    def update_state(self, update_dict: dict):
        if "requested_primaries" in update_dict and self.status != update_dict["requested_primaries"]:
            self.status = update_dict["requested_primaries"]
        if "simulated_primaries" in update_dict and self.status != update_dict["simulated_primaries"]:
            self.status = update_dict["simulated_primaries"]
        if "status" in update_dict and self.status != update_dict["status"]:
            self.status = update_dict["status"]
        if "estimated_time" in update_dict:
            estimated_time = update_dict["estimated_time"]["seconds"]\
                + update_dict["estimated_time"]["minutes"] * 60\
                + update_dict["estimated_time"]["hours"] * 3600
            if self.estimated_time_seconds != estimated_time:
                self.estimated_time_seconds = estimated_time


class ResultModel(db.Model):
    """Simulation results model"""

    __tablename__ = 'Result'
    id: Column[int] = db.Column(db.Integer, primary_key=True)
    simulation_id: Column[int] = db.Column(db.Integer, db.ForeignKey('Simulation.id'))


def create_models():
    """Function creating database's models"""
    db.create_all()
