from enum import Enum


class CarnetEnum(Enum):
    """Official DGT 'clase de permiso' codes (the <select> option values).
    Values double as what is stored in the DB and sent to the form.
    """
    A = "A"
    AM = "AM"
    AML = "AML"
    A1 = "A1"
    A2 = "A2"
    B = "B"
    EB = "EB"          # B+E
    B96 = "B96"
    C = "C"
    EC = "EC"          # C+E
    C1 = "C1"
    EC1 = "EC1"        # C1+E
    D = "D"
    ED = "ED"          # D+E
    D1 = "D1"
    ED1 = "ED1"        # D1+E
    LCC = "LCC"
    LCM = "LCM"
    LVA = "LVA"
    BC = "BC"          # M.P. Básico Común
    CI = "CI"          # M.P. Cisternas
    CX1 = "CX1"        # M.P. Explosivos
    C7 = "C7"          # M.P. Radiactivo
    RPV = "RPV"        # Pérdida vigencia

    @classmethod
    def is_valid(cls, code):
        """True if `code` is a known carnet value (no raising — for lenient JSON checks)."""
        return code in cls._value2member_map_

    @classmethod
    def from_dgt(cls, code):
        """Parse a carnet code (from the DGT result page). Raises ValueError if unknown."""
        try:
            return cls(code)
        except ValueError:
            raise ValueError(f"Unknown carnet code: {code!r}")
