from enum import Enum


class ResultadoEnum(Enum):
    APTO = "APTO"
    NO_APTO = "NO APTO"

    @classmethod
    def from_dgt(cls, text):
        """Parse a DGT 'CALIFICACIÓN EXAMEN' label into a member.
        Raises ValueError if the text is not one we contemplate.
        """
        if isinstance(text, str):
            normalized = " ".join(text.upper().split())
            for member in cls:
                if member.value == normalized:
                    return member
        raise ValueError(f"Unrecognised DGT calificación: {text!r}")
