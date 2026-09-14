"""Daily audit of the DGT prueba history: one pass per persona per day.

The bot only ever queries the exams somebody registered in the panel, so an exam a person
really sat but nobody added is invisible to it. Once a day, for each persona, this service
reopens the DGT results page using a date the person is ALREADY known to have a result for,
expands the full history ("ver todas las pruebas" — the page's other-exams section) and
compares it against the exams registered in `examenes`:

  - every prueba row is (re)registered through history_service, so results, inferred passes
    and completed carnets stay in sync with the DGT;
  - any (clase de permiso, fecha) in that history with NO exam registered is an exam that
    escaped the watch list: it is stored with the result it already carries and notified
    through Telegram, so it is never reported twice.

A persona is audited at most once a day (tracked in the `auditorias` table), and only if
the audit actually completed — a DGT outage leaves it due and it is retried later.
"""

import html
import logging
import time
from datetime import datetime

import sentry_sdk

from config import config
from utils.timeutils import today_madrid
from domain.enums.carnet_enum import CarnetEnum
from domain.enums.resultado_enum import ResultadoEnum
from domain.enums.status_enum import StatusEnum
from domain.errors import ServiceDown

from services.history_service import sync_persona_history

from adapters.database_manager import DatabaseManager
from adapters.browser_manager import BrowserManager
from adapters.telegram_bot import TelegramBot

# Known dates tried before giving up on a persona for this round: the DGT may no longer
# answer for the newest one (purged record), so fall back to the next most recent.
MAX_CANDIDATE_DATES = 3

# Exams listed in one Telegram alert before collapsing the rest into a counter. The first
# audit of a persona usually finds their whole pre-bot DGT history in one go.
MAX_ALERT_LINES = 15


def _parse_fecha(raw):
    """dd/mm/yyyy -> date, or None if missing/unparseable (inferred rows have no date)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%d/%m/%Y").date()
    except ValueError:
        return None


def examenes_no_controlados(history: list, registrados: set) -> list:
    """Pure: the exams in a scraped DGT history that are NOT in the registered set.

    `history` holds the raw parsed rows ({carnet, tipo, fecha, calificacion}); `registrados`
    the (tipo_examen, fecha) pairs already in `examenes`, whatever their state. Returns one
    dict {"carnet", "fecha", "aprobado"} per missing (carnet, fecha), ordered by date: a day
    with several pruebas of the same carnet is a single exam, failed if ANY of them is NO APTO.

    Rows without a usable date are skipped — they can't be matched to an exam day. An
    unknown carnet code or calificación RAISES (fails loud → Sentry) rather than storing junk.
    """
    encontrados = {}
    for row in history:
        fecha = _parse_fecha(row.get("fecha"))
        if fecha is None:
            continue
        carnet = CarnetEnum.from_dgt((row.get("carnet") or "").strip()).value  # raises if unknown
        if (carnet, fecha) in registrados:
            continue
        aprobado = ResultadoEnum.from_dgt(row.get("calificacion")) == ResultadoEnum.APTO  # raises if unknown
        clave = (carnet, fecha)
        encontrados[clave] = aprobado if clave not in encontrados else (encontrados[clave] and aprobado)

    return [
        {"carnet": carnet, "fecha": fecha, "aprobado": aprobado}
        for (carnet, fecha), aprobado in sorted(encontrados.items(), key=lambda item: (item[0][1], item[0][0]))
    ]


def _mensaje_examenes_nuevos(persona, nuevos: list) -> str:
    """Telegram alert for the exams the audit found outside the watch list (Spanish copy).

    Capped at MAX_ALERT_LINES entries: the FIRST audit of a persona typically finds their
    whole pre-bot history at once, and Telegram rejects messages over ~4096 characters.
    """
    lineas = [
        "⚠️ <b>Examen(es) no controlado(s) detectado(s)</b>",
        f"Persona: {html.escape(persona.nombre)} ({html.escape(persona.nif)})",
        "",
    ]
    for examen in nuevos[:MAX_ALERT_LINES]:
        resultado = "APROBADO ✅" if examen["aprobado"] else "SUSPENDIDO ❌"
        lineas.append(f"• {examen['carnet']} — {examen['fecha'].strftime('%d/%m/%Y')} — {resultado}")
    if len(nuevos) > MAX_ALERT_LINES:
        lineas.append(f"… y {len(nuevos) - MAX_ALERT_LINES} más (consúltalos en el panel)")
    lineas.append("")
    lineas.append("Estaban en la DGT pero no en el panel: se han añadido con su resultado.")
    return "\n".join(lineas)


def _fetch_history(persona, candidatos: list, browser_manager: BrowserManager, logger: logging.Logger):
    """Reopen the DGT results page with each known (carnet, fecha) until one answers, and
    return its full parsed history. None if the DGT had no record for any of them.

    Paces itself like the regular polling (config.time_between_exams between searches).
    """
    birthdate_str = persona.fecha_nacimiento.strftime("%d/%m/%Y")
    for carnet, fecha in candidatos:
        fecha_str = fecha.strftime("%d/%m/%Y")
        logger.info(
            f"Auditing persona {persona.id}: reopening the DGT history with {carnet} {fecha_str}"
        )
        browser_manager.reset_website()
        browser_manager.fill_fields([persona.nif, fecha_str, carnet, birthdate_str])
        browser_manager.submit_form()
        result = browser_manager.get_result()
        time.sleep(config.time_between_exams)

        if isinstance(result, dict):
            return result.get("history", [])

        logger.warning(
            f"Audit of persona {persona.id}: the DGT has no record for {carnet} {fecha_str} "
            f"(already-known result); trying an older date"
        )
    return None


def _report_untracked_exams(
    persona,
    history: list,
    db_manager: DatabaseManager,
    telegram_bot: TelegramBot,
    logger: logging.Logger,
) -> None:
    """Register the scraped history and store + notify the exams that were never watched."""
    # keep pruebas / inferred passes / completed carnets in sync with what the DGT shows
    sync_persona_history(persona.id, history, db_manager, logger)

    nuevos = examenes_no_controlados(history, db_manager.get_examenes_registrados(persona.id))
    if not nuevos:
        logger.info(
            f"Audit of persona {persona.id} clean: {len(history)} prueba row(s), "
            f"every exam already registered"
        )
        return

    for examen in nuevos:
        # the result is already known, so the exam goes straight to its final state
        # instead of PENDING (which would re-query the DGT and notify it a second time)
        estado = StatusEnum.APPROVED if examen["aprobado"] else StatusEnum.FAILED
        db_manager.create_examen(
            persona_id=persona.id,
            fecha_examen=examen["fecha"],
            tipo_examen=examen["carnet"],
            estado_id=estado.value,
        )
        logger.warning(
            f"Audit of persona {persona.id}: exam {examen['carnet']} "
            f"{examen['fecha'].strftime('%d/%m/%Y')} was NOT registered; "
            f"added as {estado.name}"
        )

    telegram_bot.send_message(_mensaje_examenes_nuevos(persona, nuevos))


def audit_persona(
    persona,
    db_manager: DatabaseManager,
    browser_manager: BrowserManager,
    telegram_bot: TelegramBot,
    logger: logging.Logger,
    hoy,
) -> bool:
    """Run one persona's daily audit and record the pass. Always returns True: the caller
    only sees False when something transient (an outage, an unexpected error) aborted the
    run before it was recorded, which is what leaves the persona due for a retry.
    """
    candidatos = db_manager.get_fechas_con_resultado(persona.id)[:MAX_CANDIDATE_DATES]
    if not candidatos:
        # nothing to query with: the DGT form needs a date that really has a result
        logger.info(f"Audit of persona {persona.id} skipped: no known exam date with a result yet")
        db_manager.marcar_auditoria(persona.id, hoy)
        return True

    history = _fetch_history(persona, candidatos, browser_manager, logger)
    if history is None:
        # "no hay ningún registro" is the DGT's definitive answer (an outage raises instead),
        # so the records were purged: retrying today would only burn searches. It fixes
        # itself as soon as the person has a newer result to query with.
        logger.warning(
            f"Audit of persona {persona.id}: the DGT no longer has a record for any of its "
            f"known exam dates, so its history could not be re-read today"
        )
    else:
        try:
            _report_untracked_exams(persona, history, db_manager, telegram_bot, logger)
        except Exception as e:
            # A label we don't contemplate fails loud (Sentry) but the day's pass still counts:
            # the page would parse the same way on every retry, so leaving the persona due
            # would just hammer the DGT until midnight.
            logger.error(
                f"Audit of persona {persona.id} could not compare the DGT history: {e}", exc_info=e,
            )
            sentry_sdk.capture_exception(e)

    db_manager.marcar_auditoria(persona.id, hoy)
    return True


def run_due_audit(
    db_manager: DatabaseManager,
    browser_manager: BrowserManager,
    telegram_bot: TelegramBot,
    logger: logging.Logger,
) -> bool:
    """Audit the persona whose daily pass is most overdue, if any. Returns True if one ran.

    Only ONE persona per call: the polling loop calls it on every iteration, so the audits
    spread out instead of hogging the browser. Errors are swallowed the same way
    process_exam does — a failing audit must never break the loop, and leaves the persona
    due so the next iteration retries.
    """
    if not config.audit_enabled:
        return False

    hoy = today_madrid()
    try:
        pendientes = db_manager.get_personas_a_auditar(hoy)
        if not pendientes:
            return False
        return audit_persona(pendientes[0], db_manager, browser_manager, telegram_bot, logger, hoy)
    except ServiceDown:
        logger.warning(
            f"The DGT service appears to be down during the audit. "
            f"Waiting {config.service_down_wait_time} seconds before retrying."
        )
        time.sleep(config.service_down_wait_time)
        return False
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error("The daily audit failed:", exc_info=e)
        return False
