from enum import Enum


class PlatformType(Enum):
    """Platform specification"""

    DIRECT = "DIRECT"
    BATCH = "BATCH"


class EntityState(Enum):
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


class SimulationType(Enum):
    """Simulation type specification"""

    SHIELDHIT = "shieldhit"
    TOPAS = "topas"
    FLUKA = "fluka"
    DUMMY = "dummy"
