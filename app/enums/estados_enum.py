from enum import Enum

class EstadosEnum(Enum):
    PENDIENTE = 1
    REVISANDO = 2
    REVISADO_CADUCADO = 3
    APROBADO = 4
    SUSPENDIDO = 5