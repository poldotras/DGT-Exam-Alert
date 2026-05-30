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
from enums.status_enum import StatusEnum, STATUS_DB_NAMES
from enums.carnet_enum import CarnetEnum
from enums.prueba_enum import PruebaEnum
from enums.resultado_enum import ResultadoEnum
from errors.ServiceDown import ServiceDown
import exam_pipeline

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
    # Idempotent: insert only the status rows that are missing (names live in status_enum.py).
    try:
        existing_names = {s.nombre for s in db_manager.get_estados()}
        created = 0
        for _status_member, name in STATUS_DB_NAMES:
            if name not in existing_names:
                db_manager.create_estado(name)
                created += 1
        if created:
            logger.info(f"Statuses seeded: {created} new row(s) created")
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


def _aprobadas_enums(persona_id: int, db_manager: DatabaseManager) -> set:
    """Read the person's passed (carnet, prueba) from the DB and lift them to enums."""
    return {
        (CarnetEnum(c), PruebaEnum(p))
        for (c, p) in db_manager.get_pruebas_aprobadas(persona_id)
    }


def _register_history(persona_id: int, history: list, db_manager: DatabaseManager, logger: logging.Logger) -> None:
    """Persist every parsed prueba row. The TIPO DE PRUEBA, CLASE DE PERMISO and CALIFICACIÓN
    are parsed into enums; any value we don't contemplate RAISES (fails loud → Sentry).
    """
    for row in history:
        prueba = exam_pipeline.parse_tipo_prueba(row.get("tipo"))          # raises if unknown
        resultado = ResultadoEnum.from_dgt(row.get("calificacion"))        # raises if unknown
        carnet = CarnetEnum.from_dgt((row.get("carnet") or "").strip())    # raises if unknown

        fecha = None
        fecha_raw = (row.get("fecha") or "").strip()
        if fecha_raw:
            try:
                fecha = datetime.strptime(fecha_raw, "%d/%m/%Y").date()
            except ValueError:
                logger.warning(f"Unparseable FECHA '{fecha_raw}' for {carnet.value}/{prueba.value}; storing without date")

        if db_manager.registrar_resultado_prueba(persona_id, carnet.value, prueba.value, fecha, resultado.value):
            logger.info(f"Registered prueba {carnet.value}/{prueba.value} {fecha_raw or '(sin fecha)'} -> {resultado.value}")


def _register_inferred(persona_id: int, db_manager: DatabaseManager, logger: logging.Logger) -> None:
    """Derive and persist implied passes (earlier-in-pipeline + prerequisite carnets)
    as APTO rows with no date, based on what's really recorded so far.
    """
    implied = exam_pipeline.infer_implied_passes(_aprobadas_enums(persona_id, db_manager))
    for carnet, prueba in sorted(implied, key=lambda e: (e[0].value, e[1].value)):
        if db_manager.registrar_resultado_prueba(persona_id, carnet.value, prueba.value, None, ResultadoEnum.APTO.value):
            logger.info(f"Inferred pass {carnet.value}/{prueba.value} (sin fecha)")


def _reconcile_completed_carnets(persona_id: int, db_manager: DatabaseManager, logger: logging.Logger) -> None:
    """For each carnet the person still has pending exams in, cancel them all if its
    pipeline is now complete (real + inferred passes).
    """
    aprobadas = _aprobadas_enums(persona_id, db_manager)
    for carnet_code in db_manager.get_carnets_pendientes(persona_id):
        carnet = CarnetEnum(carnet_code)  # examenes carnets were validated at seed time
        if exam_pipeline.is_carnet_complete(carnet, aprobadas):
            cancelled = db_manager.cancelar_pendientes_de_carnet(persona_id, carnet_code)
            logger.info(
                f"Carnet '{carnet_code}' COMPLETE for persona {persona_id}: "
                f"cancelled {cancelled} remaining pending exam(s)"
            )


def _result_for_examen(history: list, carnet: str, exam_date_str: str):
    """Find the parsed row matching the queried (carnet, date). Returns a ResultadoEnum
    (raises on an unrecognised CALIFICACIÓN) or None if no row matches.
    """
    for row in history:
        if ((row.get("carnet") or "").strip() == carnet
                and (row.get("fecha") or "").strip() == exam_date_str):
            return ResultadoEnum.from_dgt(row.get("calificacion"))
    return None


def _handle_result(
    exam_data: dict,
    result: dict,
    db_manager: DatabaseManager,
    telegram_bot: TelegramBot,
    logger: logging.Logger,
) -> None:
    """Register the full scraped history, infer implied passes, set this exam's state,
    notify Telegram, and cancel any carnet whose pipeline is now complete.
    """
    exam_id = exam_data["exam_id"]
    persona_id = exam_data["persona_id"]
    carnet = exam_data["type"]
    exam_date_str = exam_data["exam_date_str"]
    history = result.get("history", [])
    screenshot_path = result.get("screenshot_path")

    _register_history(persona_id, history, db_manager, logger)
    _register_inferred(persona_id, db_manager, logger)

    # this exam's own result (match by carnet + date in the parsed history)
    my_result = _result_for_examen(history, carnet, exam_date_str)
    if my_result == ResultadoEnum.APTO:
        db_manager.update_estado_examen(exam_id, StatusEnum.APPROVED.value)
        telegram_bot.send_result(True, screenshot_path)
    elif my_result == ResultadoEnum.NO_APTO:
        db_manager.update_estado_examen(exam_id, StatusEnum.FAILED.value)
        telegram_bot.send_result(False, screenshot_path)
    else:
        # queried exam not found in the parsed history — unexpected, leave for retry
        logger.critical(
            f"Exam {exam_id}: queried result ({carnet} {exam_date_str}) not found in parsed "
            f"history ({len(history)} rows). State not updated."
        )
        sentry_sdk.capture_message(
            f"Queried exam result not found in DGT history: {carnet} {exam_date_str}",
            level="error",
        )

    # cancel any carnet that is now fully complete (covers this carnet and any others
    # the registered history may have completed)
    _reconcile_completed_carnets(persona_id, db_manager, logger)


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

        if result is False:
            # no record on the DGT yet; if the exam date is old enough, mark expired
            exam_date = datetime.strptime(exam_date_str, "%d/%m/%Y").date()
            if (today_madrid() - exam_date).days > config.expired_after_days:
                db_manager.update_estado_examen(exam_id, StatusEnum.REVIEWED_EXPIRED.value)
            return

        if not isinstance(result, dict):
            raise Exception(f"Unexpected result type from get_result: {result!r}")

        logger.info(
            f"Result obtained for NIF {exam_data['nif']} {exam_data['type']} {exam_date_str}: "
            f"{len(result.get('history', []))} prueba row(s) in history"
        )
        _handle_result(exam_data, result, db_manager, telegram_bot, logger)

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
