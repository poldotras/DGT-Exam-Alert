"""personas.json loading: schema validation + seeding users/exams into the DB.

Schema-as-data: each entry in PERSON_FIELD_VALIDATORS is a (key -> validator) pair.
A validator is a callable that takes the value and returns None on success or a string
describing the failure. The shape of the schema (keys, validators) lives in one place;
the loop in _validate_person_entry is dumb.

Invalid entries are skipped (logged), never raised — the rest of personas.json continues.
"""

import re
import json
import logging
from datetime import datetime, timedelta

import sentry_sdk

from domain.enums.carnet_enum import CarnetEnum
from adapters.database_manager import DatabaseManager

# Matches both Spanish NIFs (8 digits + letter) and NIEs (X/Y/Z + 7 digits + letter)
NIF_PATTERN = re.compile(r"^[XYZ0-9]\d{7}[A-Z]$")


def _check_date_str(label):
    """Factory: returns a validator that accepts only 'dd/mm/yyyy' strings."""
    def check(value):
        if not isinstance(value, str):
            return f"{label}: expected dd/mm/yyyy string, got {type(value).__name__}"
        try:
            datetime.strptime(value, "%d/%m/%Y")
        except ValueError:
            return f"{label}: invalid date '{value}' (expected dd/mm/yyyy)"
        return None
    return check


def _check_non_empty_string(label):
    """Factory: returns a validator that accepts only non-empty strings."""
    def check(value):
        if not isinstance(value, str):
            return f"{label}: expected string, got {type(value).__name__}"
        if not value.strip():
            return f"{label}: empty string"
        return None
    return check


def _check_nif(value):
    if not isinstance(value, str):
        return f"invalid NIF/NIE: expected string, got {type(value).__name__}"
    if not NIF_PATTERN.match(value.strip().upper()):
        return f"invalid NIF/NIE '{value}'"
    return None


def _check_exam_date_field(value):
    """Polymorphic: accepts str (one date), dict {start, end}, or list of dates."""
    if isinstance(value, str):
        return _check_date_str("exam date")(value)
    if isinstance(value, dict):
        if "start" not in value or "end" not in value:
            return "exam date dict missing 'start' or 'end'"
        for sub_key in ("start", "end"):
            err = _check_date_str(f"exam date {sub_key}")(value[sub_key])
            if err:
                return err
        if datetime.strptime(value["start"], "%d/%m/%Y") > datetime.strptime(value["end"], "%d/%m/%Y"):
            return f"exam date range: start ({value['start']}) is after end ({value['end']})"
        return None
    if isinstance(value, list):
        for d in value:
            err = _check_date_str("exam date list")(d)
            if err:
                return err
        return None
    return f"exam date: unexpected type {type(value).__name__}, expected str / dict / list"


# The schema. Adding/removing a person field = editing this dict only.
# Note: NO 'prueba' — the prueba is discovered from the DGT result history, not the JSON.
PERSON_FIELD_VALIDATORS = {
    "nif": _check_nif,
    "nombre": _check_non_empty_string("nombre"),
    "carnet": _check_non_empty_string("carnet"),
    "fecha_nacimiento": _check_date_str("fecha_nacimiento"),
    "fecha_examen": _check_exam_date_field,
}


def _validate_person_entry(entry, idx: int, logger: logging.Logger) -> bool:
    """Return True if the entry passes shape checks; logs and returns False otherwise.

    Does not raise — invalid entries are skipped, the rest of personas.json continues.
    """
    if not isinstance(entry, dict):
        logger.error(f"personas.json entry {idx}: not an object, got {type(entry).__name__}, skipping")
        return False

    missing = PERSON_FIELD_VALIDATORS.keys() - entry.keys()
    if missing:
        logger.error(f"personas.json entry {idx}: missing keys {sorted(missing)}, skipping")
        return False

    for key, validator in PERSON_FIELD_VALIDATORS.items():
        err = validator(entry[key])
        if err:
            logger.error(f"personas.json entry {idx}: {err}, skipping")
            return False

    # the carnet must be a valid DGT 'clase de permiso' code (else the form query is invalid)
    if not CarnetEnum.is_valid(entry["carnet"]):
        logger.error(
            f"personas.json entry {idx}: invalid carnet '{entry['carnet']}' "
            f"(not a DGT clase de permiso code), skipping"
        )
        return False

    return True


def _dates_from_field(exam_date_field):
    """Normalise the polymorphic 'fecha_examen' JSON value into a list of date objects.

    Assumes the field has already been validated by `_validate_person_entry`.
    """
    if isinstance(exam_date_field, str):
        return [datetime.strptime(exam_date_field, "%d/%m/%Y").date()]
    if isinstance(exam_date_field, dict):
        # expecting {'start': 'DD/MM/YYYY', 'end': 'DD/MM/YYYY'}
        start_date = datetime.strptime(exam_date_field.get("start"), "%d/%m/%Y").date()
        end_date = datetime.strptime(exam_date_field.get("end"), "%d/%m/%Y").date()
        return [start_date + timedelta(days=x) for x in range((end_date - start_date).days + 1)]
    if isinstance(exam_date_field, list):
        return [datetime.strptime(f, "%d/%m/%Y").date() for f in exam_date_field]
    return []


def seed_people(
    db_manager: DatabaseManager,
    logger: logging.Logger,
    json_path: str = "personas.json",
) -> None:
    """Validate the people JSON and create users/exams that don't exist yet."""
    # Note: JSON keys (nif, nombre, carnet, fecha_examen, fecha_nacimiento) stay in Spanish
    # because they are the external contract with personas.json
    try:
        with open(json_path, "r") as file:
            json_input = json.loads(file.read())

        if not isinstance(json_input, list):
            raise ValueError(f"personas.json root must be a list, got {type(json_input).__name__}")

        valid_count = 0
        skipped_count = 0
        for idx, entry in enumerate(json_input):
            if not _validate_person_entry(entry, idx, logger):
                skipped_count += 1
                continue
            valid_count += 1

            # carnet is stored exactly as written in personas.json (must be an official DGT code)
            license_type = entry.get("carnet")
            exam_date_field = entry.get("fecha_examen")
            nif = entry.get("nif")
            person_name = entry.get("nombre")
            birthdate = entry.get("fecha_nacimiento")

            person_db = db_manager.get_persona_by_nif(nif)
            if not person_db:
                if isinstance(birthdate, str):
                    birthdate = datetime.strptime(birthdate, "%d/%m/%Y").date()
                person_db = db_manager.create_persona(
                    nif=nif,
                    nombre=person_name,
                    fecha_nacimiento=birthdate,
                )

            # dedupe the polling queue by (carnet, date)
            existing_exams_query = db_manager.get_examenes_by_persona_id(
                person_db.id,
                {"tipo_examen": license_type},
            )
            existing_exams = {exam.fecha_examen for exam in existing_exams_query}

            candidate_dates = set(_dates_from_field(exam_date_field))
            dates_to_add = sorted(candidate_dates - existing_exams)

            logger.info(
                f"Processing {person_db.nombre} - Carnet: {license_type} "
                f"- Dates to add: {len(dates_to_add)}"
            )
            for position, date_to_add in enumerate(dates_to_add, start=1):
                db_manager.create_examen(
                    persona_id=person_db.id,
                    fecha_examen=date_to_add,
                    tipo_examen=license_type,
                )
                logger.info(
                    f"Added exam for {person_db.nombre} - Carnet: {license_type} "
                    f"- Date: {date_to_add.strftime('%d/%m/%Y')} - {position}/{len(dates_to_add)}"
                )

        if skipped_count:
            logger.warning(
                f"personas.json: {skipped_count} entries skipped due to validation errors "
                f"(see previous logs); {valid_count} valid entries processed"
            )
        logger.info("People and exams initialized successfully")
    except FileNotFoundError:
        logger.error(f"File {json_path} not found")
        sentry_sdk.capture_exception(FileNotFoundError(f"{json_path} not found"))
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON: {str(e)}")
        sentry_sdk.capture_exception(e)
        raise
    except Exception as e:
        logger.error(f"Error initializing people and exams: {str(e)}")
        sentry_sdk.capture_exception(e)
        raise
