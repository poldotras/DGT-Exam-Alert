from enum import Enum


class StatusEnum(Enum):
    PENDING = 1
    REVIEWING = 2
    REVIEWED_EXPIRED = 3
    APPROVED = 4
    FAILED = 5
