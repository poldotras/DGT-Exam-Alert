"""Reusable input validators for personas and exams, used by the web panel.

Pure (re + datetime only, no I/O). These were the reusable validators of the old
personas.json loader; the panel is now the single way to manage personas and exams.
"""
import re
from datetime import datetime, timedelta

# Matches both Spanish NIFs (8 digits + letter) and NIEs (X/Y/Z + 7 digits + letter)
NIF_PATTERN = re.compile(r"^[XYZ0-9]\d{7}[A-Z]$")


def check_date_str(label):
    """Factory: returns a validator that accepts only 'dd/mm/yyyy' strings (None if ok)."""
    def check(value):
        if not isinstance(value, str):
            return f"{label}: expected dd/mm/yyyy string, got {type(value).__name__}"
        try:
            datetime.strptime(value, "%d/%m/%Y")
        except ValueError:
            return f"{label}: invalid date '{value}' (expected dd/mm/yyyy)"
        return None
    return check


def check_nif(value):
    """Return an error string if value is not a valid Spanish NIF/NIE, else None."""
    if not isinstance(value, str):
        return f"invalid NIF/NIE: expected string, got {type(value).__name__}"
    if not NIF_PATTERN.match(value.strip().upper()):
        return f"invalid NIF/NIE '{value}'"
    return None


def check_exam_date_field(value):
    """Polymorphic exam-date validator: str (one date), dict {start, end}, or list of dates."""
    if isinstance(value, str):
        return check_date_str("exam date")(value)
    if isinstance(value, dict):
        if "start" not in value or "end" not in value:
            return "exam date dict missing 'start' or 'end'"
        for sub_key in ("start", "end"):
            err = check_date_str(f"exam date {sub_key}")(value[sub_key])
            if err:
                return err
        if datetime.strptime(value["start"], "%d/%m/%Y") > datetime.strptime(value["end"], "%d/%m/%Y"):
            return f"exam date range: start ({value['start']}) is after end ({value['end']})"
        return None
    if isinstance(value, list):
        for d in value:
            err = check_date_str("exam date list")(d)
            if err:
                return err
        return None
    return f"exam date: unexpected type {type(value).__name__}, expected str / dict / list"


def dates_from_field(exam_date_field):
    """Normalise a validated exam-date value into a list of date objects.

    str -> [date]; {start, end} -> every day in the inclusive range; list -> [dates].
    """
    if isinstance(exam_date_field, str):
        return [datetime.strptime(exam_date_field, "%d/%m/%Y").date()]
    if isinstance(exam_date_field, dict):
        start_date = datetime.strptime(exam_date_field.get("start"), "%d/%m/%Y").date()
        end_date = datetime.strptime(exam_date_field.get("end"), "%d/%m/%Y").date()
        return [start_date + timedelta(days=x) for x in range((end_date - start_date).days + 1)]
    if isinstance(exam_date_field, list):
        return [datetime.strptime(f, "%d/%m/%Y").date() for f in exam_date_field]
    return []
