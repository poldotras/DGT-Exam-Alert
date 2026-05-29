import os
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium import webdriver

from errors.ServiceDown import ServiceDown
from utils import generate_random_string

IDS_DGT_WEBSITE = [
    "formularioBusquedaNotas:nifnie",
    "formularioBusquedaNotas:fechaExamen",
    "formularioBusquedaNotas:clasepermiso",
    "formularioBusquedaNotas:fechaNacimiento",
]

URL = "https://sedeclave.dgt.gob.es/WEB_NOTP_CONSULTA/consultaNota.faces"

#TODO: Eliminar os.getenv de este manager, unificar
TIEMPO_MAXIMO_ESPERA_RESULTADOS = int(os.getenv("TIEMPO_MAXIMO_ESPERA_RESULTADOS", 300))
FOLDER_SCREENSHOT_PREFIX = os.getenv("FOLDER_SCREENSHOT_PREFIX", "screenshots")
IS_DEBUG_MODE = bool(int(os.getenv("DEBUG_APP", 0)))
#TODO: REMPLAZAR LOS SLEEPS POR COMPROBACIONES

class BrowserManager:
    _logger = None
    _sentry_sdk = None
    _driver = None

    def __init__(self, logger, sentry_sdk):
        self._logger = logger
        self._sentry_sdk = sentry_sdk

        """Create and configure a headless Chrome webdriver instance."""
        opciones = Options()
        opciones.add_argument("--log-level=3") # reduce logging noise
        opciones.add_argument("--headless") # run in headless mode for better performance and no UI
        opciones.add_argument("--incognito") # use incognito to avoid caching issues
        opciones.add_argument("--disable-gpu") # recommended for headless mode
        opciones.add_argument("--no-sandbox") # required for some Linux environments

        self._driver = webdriver.Chrome(options=opciones)
        self._driver.implicitly_wait(2)

        self._logger.info("Navegador iniciado")
        
        # pequeña pausa para que el proceso de Chrome se estabilize
        time.sleep(3)

    def reset_website(self):
        """Navigate to the DGT website and wait for it to load."""
        self._driver.get(URL)
        # esperar a que el sitio cargue completamente
        time.sleep(5)

    def fill_fields(self, datos_fields, max_attempts: int = 5):
        intentos = 0

        while intentos < max_attempts:
            datos_rellenados= []
            for i, value in enumerate(datos_fields):
                if i not in datos_rellenados:
                    try:
                        self._driver.find_element(By.ID, IDS_DGT_WEBSITE[i]).send_keys(value)
                    except Exception:
                        # ignore individual field failures and try again
                        pass
                    else:
                        datos_rellenados.append(IDS_DGT_WEBSITE[i])
                    time.sleep(1)

            if len(datos_rellenados) == len(datos_fields):
                break

            self._logger.info(f"Intento {intentos + 1} de {max_attempts} para llenar el formulario, campos completados: {len(datos_rellenados)}/{len(datos_fields)}")

            try:
                self._driver.find_element(By.XPATH, "//input[@title='Limpiar']").click()
                time.sleep(1)
            except Exception:
                if IS_DEBUG_MODE:
                    self._driver.save_screenshot(f"{FOLDER_SCREENSHOT_PREFIX}/.debug/fallos_fill_fields/{generate_random_string()}.png")
                self.reset_website()
            intentos += 1
        if intentos >= max_attempts:
            if IS_DEBUG_MODE:
                self._driver.save_screenshot(f"{FOLDER_SCREENSHOT_PREFIX}/.debug/fallos_fill_fields_max_attempts/{generate_random_string()}.png")
            raise Exception(f"No se pudieron llenar todos los campos después de {max_attempts} intentos")

    def submit_form(self):
        self._driver.find_element(By.XPATH, "//input[@title='Buscar']").click()

    def get_result(self):
        # esperar resultado o mensaje de error
        t1 = time.time()

        while (time.time() - t1) < TIEMPO_MAXIMO_ESPERA_RESULTADOS:
            time.sleep(5)

            resultado_element = self._driver.find_elements(By.ID, "formularioResultadoNotas:j_id38:0:j_id70")
            if resultado_element:
                time.sleep(5)

                screenshot_path = f"{FOLDER_SCREENSHOT_PREFIX}/resultados_examen/{generate_random_string()}.png"
                self._driver.save_screenshot(screenshot_path)
                time.sleep(3)
                return {
                    "text": resultado_element[0].text,
                    "screenshot_path": screenshot_path
                }
            
            msg_error_element = self._driver.find_elements(By.CLASS_NAME, "msgError")
            if msg_error_element:
                msg_error = msg_error_element[0].text
                if "No hay ningún registro para los datos introducidos" in msg_error:
                    return False
                
                if IS_DEBUG_MODE:
                    self._driver.save_screenshot(f"{FOLDER_SCREENSHOT_PREFIX}/.debug/webpage_msg_error/{generate_random_string()}.png")
                raise Exception(f"Error encontrado: {msg_error}")
            
            rate_limit_or_internal_error_page = self._driver.find_element(By.CLASS_NAME, "mensajeError")
            
            if rate_limit_or_internal_error_page and "operación solicitada no está disponible en estos momentos" in rate_limit_or_internal_error_page.text:
                if IS_DEBUG_MODE:
                    self._driver.save_screenshot(f"{FOLDER_SCREENSHOT_PREFIX}/.debug/webpage_error/{generate_random_string()}.png")
                raise ServiceDown()
            
            #TODO: SI FALLA TODO= REINTENTAR?(PRO si la web esta caida seguira reintentando pero si es solo esos datos se quedara pillado en ese examen)
            # raise Exception("No se ha encontrado mensaje de error ni resultado") 
        
        if IS_DEBUG_MODE:
            self._driver.save_screenshot(f"{FOLDER_SCREENSHOT_PREFIX}/.debug/webpage_error/{generate_random_string()}.png")
        raise Exception("Tiempo máximo de espera superado sin obtener resultado ni mensaje de error")