"""Exam-processing service: the polling loop plus the business logic for a single exam.

Pulls due exams from the DB, drives the browser to fetch each result, notifies via
Telegram and persists the outcome (registering the scraped prueba history through
history_service). Every loop iteration also gives the daily audit a turn, so exams nobody
registered in the panel still surface (services/audit_service).
"""

import time
import traceback
import logging
from datetime import datetime
from typing import List, Dict

import sentry_sdk

from config import config
from utils.timeutils import today_madrid
from domain.enums.status_enum import StatusEnum
from domain.enums.resultado_enum import ResultadoEnum
from domain.errors import ServiceDown

from services.history_service import sync_persona_history
from services.audit_service import run_due_audit

from adapters.database_manager import DatabaseManager
from adapters.browser_manager import BrowserManager
from adapters.telegram_bot import TelegramBot

# Sleep time when there are no exams to process
SLEEP_IF_NO_WORK = 30


def fetch_exams_to_review(db_manager: DatabaseManager) -> List[Dict]:
    """Retrieve exams that need reviewing and serialize their data.

    The caller passes in the DatabaseManager instance. Returned list contains dicts
    with the following keys:
      - "exam_id"        (int)
      - "persona_id"     (int)
      - "nif"            (str)
      - "exam_date_str"  (str, formatted dd/MM/YYYY)
      - "type"           (str)
      - "birthdate_str"  (str)
    """
    raw = db_manager.get_examenes_a_revisar()
    serialized: List[Dict] = []
    for exam in raw:
        # include id and date in serialization to allow state updates later
        serialized.append({
            "exam_id": exam.id,
            "persona_id": exam.persona_id,
            "nif": exam.persona.nif,
            "exam_date_str": exam.fecha_examen.strftime("%d/%m/%Y"),
            "type": exam.tipo_examen,
            "birthdate_str": exam.persona.fecha_nacimiento.strftime("%d/%m/%Y"),
        })
    return serialized


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
    """Notify this exam's result, then register the full scraped history, infer implied
    passes and cancel any carnet whose pipeline is now complete.

    The notification comes FIRST and the full-history processing is isolated: an unknown
    label while re-parsing the history must never block the notification of a valid result.
    """
    exam_id = exam_data["exam_id"]
    persona_id = exam_data["persona_id"]
    carnet = exam_data["type"]
    exam_date_str = exam_data["exam_date_str"]
    history = result.get("history", [])
    screenshot_path = result.get("screenshot_path")

    # 1) This exam's own result (match by carnet + date in the in-memory history). Parses
    #    only the queried row — independent of the rest of the history.
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

    # 2) Register the full history + inference + cancellation (isolated inside the helper).
    sync_persona_history(persona_id, history, db_manager, logger)


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
        # One persona per iteration at most, so the daily audits interleave with the
        # regular polling instead of blocking it for several minutes in a row.
        audited = run_due_audit(db_manager, browser_manager, telegram_bot, logger)

        # re-read the DB on every main iteration
        exams_to_review = fetch_exams_to_review(db_manager)
        if not exams_to_review:
            if not audited:
                # an audit already paced itself; only idle when nothing at all happened
                time.sleep(SLEEP_IF_NO_WORK)
            continue

        for exam_data in exams_to_review:
            process_exam(exam_data, browser_manager, telegram_bot, db_manager, logger)
