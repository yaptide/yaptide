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


class EntityState(Enum):
    """Job and task state types"""

    UNKNOWN = "UNKNOWN"
    """
    This state is used only for jobs which are not yet submitted but was created in the database.
    Jobs in this state cannot be canceled.
    """
    PENDING = "PENDING"
    """
    Jobs and tasks in this state are waiting for execution.
    """
    RUNNING = "RUNNING"
    """
    Jobs and tasks in this state are currently running.
    """
    CANCELED = "CANCELED"
    """
    Jobs and tasks in this state are canceled.
    Jobs and tasks in this state cannot be canceled.
    """
    COMPLETED = "COMPLETED"
    """
    Jobs and tasks in this state are completed.
    Jobs and tasks in this state cannot be canceled.
    """
    FAILED = "FAILED"
    """
    Jobs and tasks in this state are failed.
    Jobs and tasks in this state cannot be canceled.
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
