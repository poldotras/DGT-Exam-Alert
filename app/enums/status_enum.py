from enum import Enum


class StatusEnum(Enum):
    PENDING = 1
    REVIEWING = 2
    REVIEWED_EXPIRED = 3
    APPROVED = 4
    FAILED = 5
    CANCELLED = 6


# DB row names for each status, in StatusEnum order. Names stay in Spanish to match the
# existing `estados` rows. APPEND-ONLY: new statuses go at the end so their auto-increment id
# lines up with the enum value (e.g. CANCELLED=6 is the 6th row).
STATUS_DB_NAMES = [
    (StatusEnum.PENDING, "Pendiente"),
    (StatusEnum.REVIEWING, "Revisando"),
    (StatusEnum.REVIEWED_EXPIRED, "Revisado/Caducado"),
    (StatusEnum.APPROVED, "Aprobado"),
    (StatusEnum.FAILED, "Suspendido"),
    (StatusEnum.CANCELLED, "Cancelado"),
]
