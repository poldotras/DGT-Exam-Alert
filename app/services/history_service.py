"""Persisting a scraped DGT prueba history for one persona.

Shared by the two flows that read the DGT results page: the exam polling
(services/exam_service) and the daily audit (services/audit_service). Given the parsed
rows it registers every prueba, derives the implied passes and cancels the carnets whose
pipeline is complete — the domain rules themselves live in domain/exam_pipeline.
"""

import logging
from datetime import datetime

import sentry_sdk

from domain.enums.carnet_enum import CarnetEnum
from domain.enums.prueba_enum import PruebaEnum
from domain.enums.resultado_enum import ResultadoEnum
from domain import exam_pipeline

from adapters.database_manager import DatabaseManager


def aprobadas_enums(persona_id: int, db_manager: DatabaseManager) -> set:
    """Read the person's passed (carnet, prueba) from the DB and lift them to enums."""
    return {
        (CarnetEnum(c), PruebaEnum(p))
        for (c, p) in db_manager.get_pruebas_aprobadas(persona_id)
    }


def register_history(persona_id: int, history: list, db_manager: DatabaseManager, logger: logging.Logger) -> None:
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


def register_inferred(persona_id: int, db_manager: DatabaseManager, logger: logging.Logger) -> None:
    """Derive and persist implied passes (earlier-in-pipeline + prerequisite carnets)
    as APTO rows with no date, based on what's really recorded so far.
    """
    implied = exam_pipeline.infer_implied_passes(aprobadas_enums(persona_id, db_manager))
    for carnet, prueba in sorted(implied, key=lambda e: (e[0].value, e[1].value)):
        if db_manager.registrar_resultado_prueba(persona_id, carnet.value, prueba.value, None, ResultadoEnum.APTO.value):
            logger.info(f"Inferred pass {carnet.value}/{prueba.value} (sin fecha)")


def reconcile_completed_carnets(persona_id: int, db_manager: DatabaseManager, logger: logging.Logger) -> None:
    """For each carnet the person still has pending exams in, cancel them all if its
    pipeline is now complete (real + inferred passes).
    """
    aprobadas = aprobadas_enums(persona_id, db_manager)
    for carnet_code in db_manager.get_carnets_pendientes(persona_id):
        carnet = CarnetEnum(carnet_code)  # examenes carnets were validated at seed time
        if exam_pipeline.is_carnet_complete(carnet, aprobadas):
            cancelled = db_manager.cancelar_pendientes_de_carnet(persona_id, carnet_code)
            logger.info(
                f"Carnet '{carnet_code}' COMPLETE for persona {persona_id}: "
                f"cancelled {cancelled} remaining pending exam(s)"
            )


def sync_persona_history(persona_id: int, history: list, db_manager: DatabaseManager, logger: logging.Logger) -> None:
    """Register the full history + inference + cancellation for a persona.

    Isolated on purpose: an unknown DGT label here fails loud (Sentry) but must never undo
    the notification the caller already sent, nor break the polling loop.
    """
    try:
        register_history(persona_id, history, db_manager, logger)
        register_inferred(persona_id, db_manager, logger)
        reconcile_completed_carnets(persona_id, db_manager, logger)
    except Exception as e:
        logger.error(
            f"Failed to register/reconcile full prueba history for persona {persona_id}: {e}",
            exc_info=e,
        )
        sentry_sdk.capture_exception(e)
