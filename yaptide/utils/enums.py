from enum import Enum


class PlatformType(Enum):
    """Platform specification"""

    DIRECT = "DIRECT"
    """
    Simulation run with Celery directly on the server.
    """
    BATCH = "BATCH"
    """
    Simulation run on the cluster with Slurm.
    """


class JobState(Enum):
    """Job state types"""

    PREPARING = "PREPARING"
    """
    Job is added to the database and is waiting for being queued.
    """
    SIMULATION_QUEUED = "SIMULATION_QUEUED"
    """
    Main calculations are queued.
    """
    SIMULATION_RUNNING = "SIMULATION_RUNNING"
    """
    Main calculations are running.
    """
    MERGING_QUEUED = "MERGING_QUEUED"
    """
    Merging of the results is queued.
    """
    MERGING_RUNNING = "MERGING_RUNNING"
    """
    Merging of the results is running.
    """
    FAILED = "FAILED"
    """
    Job is failed.
    Job in this state cannot be canceled.
    """
    COMPLETED = "COMPLETED"
    """
    Job is completed.
    Job in this state cannot be canceled.
    """
    CANCELED = "CANCELED"
    """
    Job is canceled.
    Job in this state cannot be canceled.
    """


class TaskState(Enum):
    """Task state types"""
    QUEUED = "QUEUED"
    """
    Task is queued.
    """
    INITIALIZING = "INITIALIZING"
    """
    Task is allocating memory and other resources.
    """
    RUNNING = "RUNNING"
    """
    Task is running.
    """
    FINALIZING = "FINALIZING"
    """
    Task is clearing memory and other resources.
    """
    FAILED = "FAILED"
    """
    Task is failed.
    Task in this state cannot be canceled.
    """
    COMPLETED = "COMPLETED"
    """
    Task is completed.
    Task in this state cannot be canceled.
    """
    CANCELED = "CANCELED"
    """
    Task is canceled.
    Task in this state cannot be canceled.
    """


class InputType(Enum):
    """Input type specification"""

    EDITOR = "EDITOR"
    """
    Simulation was submitted with the usage of UI editor json.
    """
    FILES = "FILES"
    """
    Simulation was submitted with the usage of input files in the format expected by the simulator.
    """


class SimulationType(Enum):
    """Simulation type specification"""

    SHIELDHIT = "shieldhit"
    """
    Simulation run with SHIELD-HIT12A.
    """
    TOPAS = "topas"
    """
    Simulation run with TOPAS.
    """
    FLUKA = "fluka"
    """
    Simulation run with FLUKA.
    """
    DUMMY = "dummy"
    """
    Simulation run with dummy simulator.
    """
