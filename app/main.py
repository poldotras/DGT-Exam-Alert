import time
import os
import traceback
import json
import logging
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

import sentry_sdk

from config import config
from utils import fetch_datos_examenes, cleanup_old_files
from enums.estados_enum import EstadosEnum
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

# tiempo de espera cuando no hay exámenes pendientes
SLEEP_IF_NO_WORK = 30


def setup_logger() -> logging.Logger:
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "{asctime} - {levelname} - {message}",
        style="{",
        datefmt="%d-%m-%Y %H:%M:%S",
    )

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


def setup_sentry() -> None:
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


def seed_estados(db_manager: DatabaseManager, logger: logging.Logger) -> None:
    # TODO: Convertir esto en un Seeder propio
    try:
        estados = db_manager.get_estados()
        if not estados:
            db_manager.create_estado("Pendiente")
            db_manager.create_estado("Revisando")
            db_manager.create_estado("Revisado/Caducado")
            db_manager.create_estado("Aprobado")
            db_manager.create_estado("Suspendido")
            logger.info("Estados creados en la base de datos")
    except Exception as e:
        logger.error(f"Error inicializando estados: {str(e)}")
        sentry_sdk.capture_exception(e)
        raise


def prepare_screenshot_folders(logger: logging.Logger) -> None:
    folders = FOLDERS_TO_SAVE_SCREENSHOTS + (
        FOLDERS_TO_SAVE_DEBUG_SCREENSHOTS if config.is_debug_mode else []
    )
    for folder in folders:
        folder_path = os.path.join(config.folder_screenshot_prefix, folder)
        os.makedirs(folder_path, exist_ok=True)
        # purgar capturas antiguas para evitar que el volumen crezca sin límite
        try:
            eliminados = cleanup_old_files(folder_path, config.dias_retencion_screenshots)
            if eliminados:
                logger.info(
                    f"Limpieza de screenshots en '{folder_path}': {eliminados} ficheros eliminados"
                )
        except Exception as e:
            logger.warning(f"No se pudo limpiar '{folder_path}': {e}")


def _dates_from_field(fecha_examen_field):
    """Normalise the polymorphic 'fecha_examen' JSON value into a list of date objects."""
    if isinstance(fecha_examen_field, str):
        return [datetime.strptime(fecha_examen_field, "%d/%m/%Y").date()]
    if isinstance(fecha_examen_field, dict):
        # expecting {'start': 'DD/MM/YYYY', 'end': 'DD/MM/YYYY'}
        start_date = datetime.strptime(fecha_examen_field.get("start"), "%d/%m/%Y").date()
        end_date = datetime.strptime(fecha_examen_field.get("end"), "%d/%m/%Y").date()
        return [start_date + timedelta(days=x) for x in range((end_date - start_date).days + 1)]
    if isinstance(fecha_examen_field, list):
        return [datetime.strptime(f, "%d/%m/%Y").date() for f in fecha_examen_field]
    return []


def seed_personas(
    db_manager: DatabaseManager,
    logger: logging.Logger,
    json_path: str = "personas.json",
) -> None:
    """Validate the personas JSON and create users/exams that don't exist yet."""
    try:
        with open(json_path, "r") as file:
            json_input = json.loads(file.read())

        for entrada_persona_examen in json_input:
            carnet_examen = entrada_persona_examen.get("carnet")
            fecha_examen_field = entrada_persona_examen.get("fecha_examen")
            nif_persona = entrada_persona_examen.get("nif")
            nombre_persona = entrada_persona_examen.get("nombre")
            fecha_nacimiento_persona = entrada_persona_examen.get("fecha_nacimiento")

            persona_db = db_manager.get_persona_by_nif(nif_persona)
            if not persona_db:
                if isinstance(fecha_nacimiento_persona, str):
                    fecha_nacimiento_persona = datetime.strptime(fecha_nacimiento_persona, "%d/%m/%Y").date()
                persona_db = db_manager.create_persona(
                    nif=nif_persona,
                    nombre=nombre_persona,
                    fecha_nacimiento=fecha_nacimiento_persona,
                )

            # fetch the person's existing exams so we can avoid inserting duplicates
            existing_examens_query = db_manager.get_examenes_by_persona_id(
                persona_db.id,
                {"tipo_examen": carnet_examen},
            )
            existing_examens = {examen.fecha_examen for examen in existing_examens_query}

            candidate_dates = set(_dates_from_field(fecha_examen_field))
            all_dates_to_add = sorted(candidate_dates - existing_examens)

            logger.info(
                f"Procesando {persona_db.nombre} - Tipo: {carnet_examen} "
                f"- Fechas a añadir: {len(all_dates_to_add)}"
            )
            for idx, date_to_add in enumerate(all_dates_to_add, start=1):
                db_manager.create_examen(
                    persona_id=persona_db.id,
                    fecha_examen=date_to_add,
                    tipo_examen=carnet_examen,
                )
                logger.info(
                    f"Añadido examen para {persona_db.nombre} - Tipo: {carnet_examen} "
                    f"- Fecha: {date_to_add.strftime('%d/%m/%Y')} - {idx}/{len(all_dates_to_add)}"
                )

        logger.info("Personas y exámenes inicializados correctamente")
    except FileNotFoundError:
        logger.error(f"Archivo {json_path} no encontrado")
        sentry_sdk.capture_exception(FileNotFoundError(f"{json_path} not found"))
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Error decodificando JSON: {str(e)}")
        sentry_sdk.capture_exception(e)
        raise
    except Exception as e:
        logger.error(f"Error inicializando personas y exámenes: {str(e)}")
        sentry_sdk.capture_exception(e)
        raise


def _handle_dict_result(
    examen_id: int,
    result: dict,
    db_manager: DatabaseManager,
    telegram_bot: TelegramBot,
    logger: logging.Logger,
) -> None:
    result_text = (result.get("text") or "").strip()
    result_screenshot_path = result.get("screenshot_path")

    if result_text == "APTO":
        db_manager.update_estado_examen(examen_id, EstadosEnum.APROBADO.value)
        telegram_bot.resultado(True, result_screenshot_path)
    elif result_text == "NO APTO":
        db_manager.update_estado_examen(examen_id, EstadosEnum.SUSPENDIDO.value)
        telegram_bot.resultado(False, result_screenshot_path)
    else:
        # texto inesperado: no escribimos estado en BBDD para que el examen se reintente
        logger.critical(
            f"Resultado inesperado para examen {examen_id}: '{result_text}'. No se actualiza estado."
        )
        sentry_sdk.capture_message(
            f"Texto de resultado inesperado: '{result_text}' para examen {examen_id}",
            level="error",
        )


def process_examen(
    datos_examen: dict,
    browser_manager: BrowserManager,
    telegram_bot: TelegramBot,
    db_manager: DatabaseManager,
    logger: logging.Logger,
) -> None:
    examen_id = datos_examen["examen_id"]
    fecha_examen_str = datos_examen["fecha_examen_str"]
    logger.info(
        f"Procesando examen ID {examen_id} para NIF {datos_examen['nif']} "
        f"con fecha de examen {fecha_examen_str}"
    )

    datos_fields = [
        datos_examen.get("nif"),
        datos_examen.get("fecha_examen_str"),
        datos_examen.get("tipo"),
        datos_examen.get("fecha_nacimiento_str"),
    ]

    # actualizar estado a REVISANDO antes de intentar la búsqueda
    db_manager.update_estado_examen(examen_id, EstadosEnum.REVISANDO.value)

    try:
        # Abre la web de la DGT para cada examen a revisar
        browser_manager.reset_website()
        browser_manager.fill_fields(datos_fields)
        browser_manager.submit_form()
        result = browser_manager.get_result()

        if result is None:
            return

        logger.info(
            f"Resultado obtenido para examen con NIF {datos_examen['nif']} "
            f"y fecha de examen {fecha_examen_str}: {result}"
        )

        if isinstance(result, dict):
            _handle_dict_result(examen_id, result, db_manager, telegram_bot, logger)
        elif isinstance(result, bool):
            # si la fecha de examen lleva más de x días y no se obtiene resultado, marcar como caducado
            exam_date = datetime.strptime(fecha_examen_str, "%d/%m/%Y").date()
            if (datetime.today().date() - exam_date).days > config.dias_se_considera_caducado:
                db_manager.update_estado_examen(examen_id, EstadosEnum.REVISADO_CADUCADO.value)
        else:
            raise Exception(f"Resultado inesperado: {result}")

        telegram_bot.update_funcionando()
        time.sleep(config.tiempo_entre_examenes)

    except ServiceDown:
        logger.warning(
            f"Servicio de la DGT parece estar caído. "
            f"Esperando {config.tiempo_espera_service_down} segundos antes de reintentar."
        )
        time.sleep(config.tiempo_espera_service_down)
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error("Se ha producido un error inesperado:", exc_info=e)
        traceback.print_exc()
        # TODO: add telegram message to notify about the error


def run_loop(
    db_manager: DatabaseManager,
    browser_manager: BrowserManager,
    telegram_bot: TelegramBot,
    logger: logging.Logger,
) -> None:
    while True:
        # volver a leer la BBDD en cada iteración principal
        datos_examenes_revisar = fetch_datos_examenes(db_manager)
        if not datos_examenes_revisar:
            time.sleep(SLEEP_IF_NO_WORK)
            continue

        for datos_examen in datos_examenes_revisar:
            process_examen(datos_examen, browser_manager, telegram_bot, db_manager, logger)


def main() -> None:
    logger = setup_logger()
    setup_sentry()

    db_manager = init_db_manager(logger)
    browser_manager = BrowserManager(logger=logger, sentry_sdk=sentry_sdk)
    telegram_bot = TelegramBot(
        token=config.telegram_bot_token,
        chat_id=config.telegram_chat_id,
        logger=logger,
    )

    seed_estados(db_manager, logger)
    prepare_screenshot_folders(logger)
    seed_personas(db_manager, logger)

    run_loop(db_manager, browser_manager, telegram_bot, logger)


if __name__ == "__main__":
    main()
