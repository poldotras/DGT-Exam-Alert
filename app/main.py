import time
import os
import traceback
import json
from datetime import datetime, timedelta, date
import sentry_sdk
import logging

from utils import fetch_datos_examenes
from enums.estados_enum import EstadosEnum
from errors.ServiceDown import ServiceDown

from database_manager import DatabaseManager
from browser_manager import BrowserManager
from telegram_bot import TelegramBot

#TODO: Añadir borrar fotos antiguas
TIEMPO_ENTRE_EXAMENES = os.getenv("TIEMPO_ENTRE_EXAMENES", 300)
TIEMPO_ESPERA_SERVICE_DOWN = int(os.getenv('TIEMPO_ESPERA_SERVICE_DOWN', 60))
DIAS_SE_CONSIDERA_CADUCADO = int(os.getenv("DIAS_SE_CONSIDERA_CADUCADO", 7))

FOLDER_SCREENSHOT_PREFIX = os.getenv("FOLDER_SCREENSHOT_PREFIX", "screenshots")
FOLDERS_TO_SAVE_SCREENSHOTS = ["resultados_examen"]
FOLDERS_TO_SAVE_DEBUG_SCREENSHOTS = [".debug/fallos_fill_fields", ".debug/fallos_fill_fields_max_attempts", ".debug/webpage_error", ".debug/webpage_msg_error"]
IS_DEBUG_MODE = bool(int(os.getenv("DEBUG_APP", 0)))

sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
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

#TODO: Rotate logs files to avoid filling up the disk, maybe with a max size of 5MB and keeping the last 5 files
file_handler = logging.FileHandler("app.log", mode="a", encoding="utf-8")
file_handler.setLevel(logging.WARNING)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)


# Initialize database manager with environment configuration
try:
    db_manager = DatabaseManager(
        host=os.getenv("MYSQL_HOST", "database"),
        database=os.getenv("MYSQL_DATABASE", ""),
        user=os.getenv("MYSQL_USER", ""),
        password=os.getenv("MYSQL_PASSWORD", ""),
        logger=logger,
    )
    logger.info("Database manager initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize database manager: {str(e)}")
    sentry_sdk.capture_exception(e)
    raise

browser_manager = BrowserManager(
    logger=logger,
    sentry_sdk=sentry_sdk,
)

telegram_bot = TelegramBot(
    token=os.getenv("TELEGRAM_BOT_TOKEN"),
    chat_id=os.getenv("TELEGRAM_CHAT_ID"),
    logger=logger,
)

#Esto tendria que ser Seeder para crear los estados en la base de datos si no existen
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

CARPETAS_SCREENSHOTS = FOLDERS_TO_SAVE_SCREENSHOTS + (FOLDERS_TO_SAVE_DEBUG_SCREENSHOTS if IS_DEBUG_MODE else [])

for folder in CARPETAS_SCREENSHOTS:
    folder_path = os.path.join(FOLDER_SCREENSHOT_PREFIX, folder)
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)

#Validate data JSON and create users if necessary
try:
    json_input = None

    with open("personas.json", "r") as file:
        fileContent = file.read()
        json_input = json.loads(fileContent)

    #Create Users if not exists
    for entrada_persona_examen in json_input:
        carnet_examen = entrada_persona_examen.get("carnet")
        fecha_examen_field = entrada_persona_examen.get("fecha_examen")
        nif_persona = entrada_persona_examen.get("nif")
        nombre_persona = entrada_persona_examen.get("nombre")
        fecha_nacimiento_persona = entrada_persona_examen.get("fecha_nacimiento")

        persona_db = db_manager.get_persona_by_nif(nif_persona)
        if not persona_db:
            # convert birthdate string to date object if necessary
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
                                        {
                                            "tipo_examen": carnet_examen
                                        }
                                    )
        existing_examens = [examen.fecha_examen for examen in existing_examens_query]

        # where keys are tipo de examen and values are either a single date or a range of dates
        # now we'll only add dates that aren't already recorded

        all_dates_to_add = []

        # decide based on the type of the field
        if isinstance(fecha_examen_field, str):
            all_dates_to_add.append(datetime.strptime(fecha_examen_field, "%d/%m/%Y").date())
        elif isinstance(fecha_examen_field, dict):
            # expecting {'start': 'DD/MM/YYYY', 'end': 'DD/MM/YYYY'}
            start_date = datetime.strptime(fecha_examen_field.get("start"), "%d/%m/%Y").date()
            end_date = datetime.strptime(fecha_examen_field.get("end"), "%d/%m/%Y").date()
            all_dates_to_add.extend([start_date + timedelta(days=x) for x in range((end_date - start_date).days + 1)])
        elif isinstance(fecha_examen_field, list):
            # list of individual date strings
            for fecha in fecha_examen_field:
                all_dates_to_add.append(datetime.strptime(fecha, "%d/%m/%Y").date())

        all_dates_to_add = [date for date in all_dates_to_add if date not in existing_examens]  # filter out existing dates
        all_dates_to_add = list(set(all_dates_to_add))  # remove duplicates if any

        logger.info(f"Procesando {persona_db.nombre} - Tipo: {carnet_examen} - Fechas a añadir: {len(all_dates_to_add)}")
        count = 0
        for date_to_add in all_dates_to_add:
            db_manager.create_examen(
                persona_id=persona_db.id,
                fecha_examen=date_to_add,
                tipo_examen=carnet_examen,
            )
            count += 1
            logger.info(f"Añadido examen para {persona_db.nombre} - Tipo: {carnet_examen} - Fecha: {date_to_add.strftime('%d/%m/%Y')} - {count}/{len(all_dates_to_add)}")
    
    logger.info("Personas y exámenes inicializados correctamente")
except FileNotFoundError:
    logger.error("Archivo personas.json no encontrado")
    sentry_sdk.capture_exception(FileNotFoundError("personas.json not found"))
    raise
except json.JSONDecodeError as e:
    logger.error(f"Error decodificando JSON: {str(e)}")
    sentry_sdk.capture_exception(e)
    raise
except Exception as e:
    logger.error(f"Error inicializando personas y exámenes: {str(e)}")
    sentry_sdk.capture_exception(e)
    raise


while True:
    # volver a leer la BBDD en cada iteración principal
    datos_examenes_revisar = fetch_datos_examenes(db_manager)
    if not datos_examenes_revisar:
        time.sleep(30)
        continue

    for datos_examen in datos_examenes_revisar:
        logger.info(f"Procesando examen ID {datos_examen['examen_id']} para NIF {datos_examen['nif']} con fecha de examen {datos_examen['fecha_examen_str']}")
        
        examen_id = datos_examen["examen_id"]
        fecha_examen_str = datos_examen["fecha_examen_str"]

        datos_fields = [
            datos_examen.get("nif"),
            datos_examen.get("fecha_examen_str"),
            datos_examen.get("tipo"),
            datos_examen.get("fecha_nacimiento_str"),
        ]

        # actualizar estado a REVISANDO antes de intentar la búsqueda
        db_manager.update_estado_examen(examen_id, EstadosEnum.REVISANDO.value)

        try:
            #Abre la web de la DGT para cada examen a revisar
            browser_manager.reset_website()
            browser_manager.fill_fields(datos_fields)
            browser_manager.submit_form()
            result = browser_manager.get_result()

            if result != None:
                logger.info(f"Resultado obtenido para examen con NIF {datos_examen['nif']} y fecha de examen {datos_examen['fecha_examen_str']}: {result}")
                
                if isinstance(result, dict):
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
                        logger.critical(f"Resultado inesperado para examen {examen_id}: '{result_text}'. No se actualiza estado.")
                        sentry_sdk.capture_message(
                            f"Texto de resultado inesperado: '{result_text}' para examen {examen_id}",
                            level="error",
                        )
                elif isinstance(result, bool):
                    # si la fecha de examen lleva más de x días y no se obtiene resultados se marca el examen como caducado
                    exam_date = datetime.strptime(fecha_examen_str, "%d/%m/%Y").date()
                    if (datetime.today().date() - exam_date).days > DIAS_SE_CONSIDERA_CADUCADO:
                        db_manager.update_estado_examen(examen_id, EstadosEnum.REVISADO_CADUCADO.value)
                else:
                    raise Exception(f"Resultado inesperado: {result}")
    

                telegram_bot.update_funcionando()
                time.sleep(int(TIEMPO_ENTRE_EXAMENES))

        except ServiceDown as sd:
            sleep_time = TIEMPO_ESPERA_SERVICE_DOWN
            logger.warning(f"Servicio de la DGT parece estar caído. Esperando {sleep_time} segundos antes de reintentar.")
            time.sleep(sleep_time)

        except Exception as e:
            sentry_sdk.capture_exception(e)
            logger.error("Se ha producido un error inesperado:", exc_info=e)
            traceback.print_exc()  # display full traceback for debugging
            #TODO: add telegram message to notify about the error
            continue
