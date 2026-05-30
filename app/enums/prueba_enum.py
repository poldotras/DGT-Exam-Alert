from enum import Enum


class PruebaEnum(Enum):
    """Canonical exam components. Values are the strings stored in the `pruebas` table."""
    TEORICO_COMUN = "teorico_comun"
    TEORICO_ESPECIFICO = "teorico_especifico"
    CIRCUITO = "circuito"
    CIRCULACION = "circulacion"
