import time
import os
import re
import traceback
import json
import logging
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

import sentry_sdk

from config import config
from utils import fetch_exams_to_review, cleanup_old_files, today_madrid
from enums.status_enum import StatusEnum
from errors.ServiceDown import ServiceDown

from database_manager import DatabaseManager
from browser_manager import BrowserManager
from telegram_bot import TelegramBot


FOLDERS_TO_SAVE_SCREENSHOTS = ["resultados_examen"]
FOLDERS_TO_SAVE_DEBUG_SCREENSHOTS = [
    ".debug/fallos_fill_fields",
    ".debug/fallos_fill_fields_max_attempts",
    ".debug/webpage_error",
    ".debug/webpage_msg_error",
]

# Sleep time when there are no exams to process
SLEEP_IF_NO_WORK = 30


def setup_logger() -> logging.Logger:
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "{asctime} - {levelname} - {message}",
        style="{",
        datefmt="%d-%m-%Y %H:%M:%S UTC",
    )
    # Force UTC for log timestamps regardless of the container's TZ.
    # User-facing displays (Telegram) convert to Europe/Madrid explicitly via now_madrid().
    formatter.converter = time.gmtime

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        config.log_file,
        mode="a",
        maxBytes=config.log_max_bytes,
        backupCount=config.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.WARNING)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def setup_sentry(logger: logging.Logger) -> None:
    if not config.sentry_dsn:
        logger.info("Sentry disabled (no DSN configured)")
        return
    sentry_sdk.init(
        dsn=config.sentry_dsn,
        # Add data like request headers and IP for users,
        # see https://docs.sentry.io/platforms/python/data-management/data-collected/ for more info
        send_default_pii=True,
        # Enable sending logs to Sentry
        enable_logs=True,
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for tracing.
        traces_sample_rate=1.0,
        # Set profile_session_sample_rate to 1.0 to profile 100%
        # of profile sessions.
        profile_session_sample_rate=1.0,
    )


def init_db_manager(logger: logging.Logger) -> DatabaseManager:
    try:
        db_manager = DatabaseManager(
            host=config.mysql_host,
            database=config.mysql_database,
            user=config.mysql_user,
            password=config.mysql_password,
            logger=logger,
        )
        logger.info("Database manager initialized successfully")
        return db_manager
    except Exception as e:
        logger.error(f"Failed to initialize database manager: {str(e)}")
        sentry_sdk.capture_exception(e)
        raise


def seed_statuses(db_manager: DatabaseManager, logger: logging.Logger) -> None:
    # TODO: Move this into a proper Seeder
    # Note: status row names kept in Spanish to stay consistent with the existing DB rows
    try:
        statuses = db_manager.get_estados()
        if not statuses:
            db_manager.create_estado("Pendiente")
            db_manager.create_estado("Revisando")
            db_manager.create_estado("Revisado/Caducado")
            db_manager.create_estado("Aprobado")
            db_manager.create_estado("Suspendido")
            logger.info("Statuses created in the database")
    except Exception as e:
        logger.error(f"Error initializing statuses: {str(e)}")
        sentry_sdk.capture_exception(e)
        raise


def prepare_screenshot_folders(logger: logging.Logger) -> None:
    folders = FOLDERS_TO_SAVE_SCREENSHOTS + (
        FOLDERS_TO_SAVE_DEBUG_SCREENSHOTS if config.is_debug_mode else []
    )
    for folder in folders:
        folder_path = os.path.join(config.screenshot_folder_prefix, folder)
        os.makedirs(folder_path, exist_ok=True)
        # purge old screenshots so the volume doesn't grow unbounded
        try:
            removed = cleanup_old_files(folder_path, config.screenshot_retention_days)
            if removed:
                logger.info(
                    f"Screenshot cleanup in '{folder_path}': {removed} files removed"
                )
        except Exception as e:
            logger.warning(f"Could not clean '{folder_path}': {e}")


# ---------------------------------------------------------------------------
# personas.json validation
#
# Schema-as-data: each entry in PERSON_FIELD_VALIDATORS is a (key -> validator)
# pair. A validator is a callable that takes the value and returns None on
# success or a string describing the failure. The shape of the schema (keys,
# validators) lives in one place; the loop in _validate_person_entry is dumb.
# ---------------------------------------------------------------------------

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

            # fetch the person's existing exams so we can avoid inserting duplicates
            existing_exams_query = db_manager.get_examenes_by_persona_id(
                person_db.id,
                {"tipo_examen": license_type},
            )
            existing_exams = {exam.fecha_examen for exam in existing_exams_query}

            candidate_dates = set(_dates_from_field(exam_date_field))
            dates_to_add = sorted(candidate_dates - existing_exams)

            logger.info(
                f"Processing {person_db.nombre} - Type: {license_type} "
                f"- Dates to add: {len(dates_to_add)}"
            )
            for idx, date_to_add in enumerate(dates_to_add, start=1):
                db_manager.create_examen(
                    persona_id=person_db.id,
                    fecha_examen=date_to_add,
                    tipo_examen=license_type,
                )
                logger.info(
                    f"Added exam for {person_db.nombre} - Type: {license_type} "
                    f"- Date: {date_to_add.strftime('%d/%m/%Y')} - {idx}/{len(dates_to_add)}"
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


def _handle_dict_result(
    exam_id: int,
    result: dict,
    db_manager: DatabaseManager,
    telegram_bot: TelegramBot,
    logger: logging.Logger,
) -> None:
    result_text = (result.get("text") or "").strip()
    result_screenshot_path = result.get("screenshot_path")

    if result_text == "APTO":
        db_manager.update_estado_examen(exam_id, StatusEnum.APPROVED.value)
        telegram_bot.send_result(True, result_screenshot_path)
    elif result_text == "NO APTO":
        db_manager.update_estado_examen(exam_id, StatusEnum.FAILED.value)
        telegram_bot.send_result(False, result_screenshot_path)
    else:
        # unexpected text: do not update the DB so the exam gets retried next loop
        logger.critical(
            f"Unexpected result for exam {exam_id}: '{result_text}'. State not updated."
        )
        sentry_sdk.capture_message(
            f"Unexpected result text: '{result_text}' for exam {exam_id}",
            level="error",
        )


def process_exam(
    exam_data: dict,
    browser_manager: BrowserManager,
    telegram_bot: TelegramBot,
    db_manager: DatabaseManager,
    logger: logging.Logger,
) -> None:
    exam_id = exam_data["exam_id"]
    exam_date_str = exam_data["exam_date_str"]
    logger.info(
        f"Processing exam ID {exam_id} for NIF {exam_data['nif']} "
        f"with exam date {exam_date_str}"
    )

    form_fields = [
        exam_data.get("nif"),
        exam_data.get("exam_date_str"),
        exam_data.get("type"),
        exam_data.get("birthdate_str"),
    ]

    # mark as REVIEWING before attempting the search
    db_manager.update_estado_examen(exam_id, StatusEnum.REVIEWING.value)

    try:
        # Open the DGT site for each exam being reviewed
        browser_manager.reset_website()
        browser_manager.fill_fields(form_fields)
        browser_manager.submit_form()
        result = browser_manager.get_result()

        if result is None:
            return

        logger.info(
            f"Result obtained for exam with NIF {exam_data['nif']} "
            f"and exam date {exam_date_str}: {result}"
        )

        if isinstance(result, dict):
            _handle_dict_result(exam_id, result, db_manager, telegram_bot, logger)
        elif isinstance(result, bool):
            # if the exam date is older than N days and no result was found, mark as expired
            exam_date = datetime.strptime(exam_date_str, "%d/%m/%Y").date()
            if (today_madrid() - exam_date).days > config.expired_after_days:
                db_manager.update_estado_examen(exam_id, StatusEnum.REVIEWED_EXPIRED.value)
        else:
            raise Exception(f"Unexpected result: {result}")

        telegram_bot.update_alive_status()
        time.sleep(config.time_between_exams)

    except ServiceDown:
        logger.warning(
            f"The DGT service appears to be down. "
            f"Waiting {config.service_down_wait_time} seconds before retrying."
        )
        time.sleep(config.service_down_wait_time)
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error("An unexpected error occurred:", exc_info=e)
        traceback.print_exc()
        # TODO: send a Telegram message to notify about the error


def run_loop(
    db_manager: DatabaseManager,
    browser_manager: BrowserManager,
    telegram_bot: TelegramBot,
    logger: logging.Logger,
) -> None:
    while True:
        # re-read the DB on every main iteration
        exams_to_review = fetch_exams_to_review(db_manager)
        if not exams_to_review:
            time.sleep(SLEEP_IF_NO_WORK)
            continue

        for exam_data in exams_to_review:
            process_exam(exam_data, browser_manager, telegram_bot, db_manager, logger)


def main() -> None:
    logger = setup_logger()
    setup_sentry(logger)

    db_manager = init_db_manager(logger)
    browser_manager = BrowserManager(logger=logger, sentry_sdk=sentry_sdk)
    telegram_bot = TelegramBot(
        token=config.telegram_bot_token,
        chat_id=config.telegram_chat_id,
        logger=logger,
    )

    seed_statuses(db_manager, logger)
    prepare_screenshot_folders(logger)
    seed_people(db_manager, logger)

    run_loop(db_manager, browser_manager, telegram_bot, logger)


if __name__ == "__main__":
    main()
