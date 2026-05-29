import os
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    ElementNotInteractableException,
    WebDriverException,
    TimeoutException,
    InvalidSessionIdException,
)

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
TIEMPO_ESPERA_CAMPO = int(os.getenv("TIEMPO_ESPERA_CAMPO", 5))
TIEMPO_ESPERA_PAGINA = int(os.getenv("TIEMPO_ESPERA_PAGINA", 15))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 2))
FOLDER_SCREENSHOT_PREFIX = os.getenv("FOLDER_SCREENSHOT_PREFIX", "screenshots")
IS_DEBUG_MODE = bool(int(os.getenv("DEBUG_APP", 0)))


class BrowserManager:
    def __init__(self, logger, sentry_sdk):
        self._logger = logger
        self._sentry_sdk = sentry_sdk
        self._driver = self._create_driver()
        self._logger.info("Navegador iniciado")

    def _create_driver(self):
        """Create and configure a headless Chrome webdriver instance."""
        opciones = Options()
        opciones.add_argument("--log-level=3")   # reduce logging noise
        opciones.add_argument("--headless")      # run in headless mode for better performance and no UI
        opciones.add_argument("--incognito")     # use incognito to avoid caching issues
        opciones.add_argument("--disable-gpu")   # recommended for headless mode
        opciones.add_argument("--no-sandbox")    # required for some Linux environments

        driver = webdriver.Chrome(options=opciones)
        # implicit_wait sigue activo para los find_element singular del flujo de formulario;
        # los find_elements (plural) del polling de get_result devuelven [] al instante igualmente.
        driver.implicitly_wait(2)
        return driver

    def _is_session_alive(self):
        """Cheap probe to check the webdriver session is still usable."""
        try:
            _ = self._driver.current_url
            return True
        except (WebDriverException, InvalidSessionIdException):
            return False

    def _ensure_driver(self):
        """If the session is dead, quit it cleanly and create a fresh one."""
        if self._is_session_alive():
            return
        self._logger.warning("Driver con sesión muerta detectado, recreando navegador")
        try:
            self._driver.quit()
        except Exception:
            pass
        self._driver = self._create_driver()

    def reset_website(self):
        """Navigate to the DGT website and wait for the form to be ready."""
        self._ensure_driver()
        self._driver.get(URL)
        # esperar a que el primer campo del formulario esté presente en lugar de un sleep ciego
        try:
            WebDriverWait(self._driver, TIEMPO_ESPERA_PAGINA).until(
                EC.presence_of_element_located((By.ID, IDS_DGT_WEBSITE[0]))
            )
        except TimeoutException:
            if IS_DEBUG_MODE:
                self._driver.save_screenshot(
                    f"{FOLDER_SCREENSHOT_PREFIX}/.debug/webpage_error/{generate_random_string()}.png"
                )
            raise Exception("La web de la DGT no cargó el formulario dentro del tiempo esperado")

    def fill_fields(self, datos_fields, max_attempts: int = 5):
        for intento in range(1, max_attempts + 1):
            indices_rellenados = set()
            for i, value in enumerate(datos_fields):
                # if i not in datos_rellenados: # TODO: Reviar si es necesario
                try:
                    element = WebDriverWait(self._driver, TIEMPO_ESPERA_CAMPO).until(
                        EC.element_to_be_clickable((By.ID, IDS_DGT_WEBSITE[i]))
                    )
                    element.send_keys(value)
                    indices_rellenados.add(i)
                except (TimeoutException, NoSuchElementException, ElementNotInteractableException) as e:
                    self._logger.debug(f"Campo {IDS_DGT_WEBSITE[i]} no disponible en intento {intento}: {e}")

            if len(indices_rellenados) == len(datos_fields):
                return

            self._logger.info(
                f"Intento {intento}/{max_attempts} para llenar el formulario, "
                f"campos completados: {len(indices_rellenados)}/{len(datos_fields)}"
            )

            try:
                limpiar_btn = WebDriverWait(self._driver, TIEMPO_ESPERA_CAMPO).until(
                    EC.element_to_be_clickable((By.XPATH, "//input[@title='Limpiar']"))
                )
                limpiar_btn.click()
            except (TimeoutException, NoSuchElementException, WebDriverException):
                if IS_DEBUG_MODE:
                    self._driver.save_screenshot(
                        f"{FOLDER_SCREENSHOT_PREFIX}/.debug/fallos_fill_fields/{generate_random_string()}.png"
                    )
                self.reset_website()

        if IS_DEBUG_MODE:
            self._driver.save_screenshot(
                f"{FOLDER_SCREENSHOT_PREFIX}/.debug/fallos_fill_fields_max_attempts/{generate_random_string()}.png"
            )
        raise Exception(f"No se pudieron llenar todos los campos después de {max_attempts} intentos")

    def submit_form(self):
        WebDriverWait(self._driver, TIEMPO_ESPERA_CAMPO).until(
            EC.element_to_be_clickable((By.XPATH, "//input[@title='Buscar']"))
        ).click()

    def get_result(self):
        """Poll until the page shows a result, an error, or the timeout is hit."""
        t1 = time.time()

        while (time.time() - t1) < TIEMPO_MAXIMO_ESPERA_RESULTADOS:
            resultado_elements = self._driver.find_elements(By.ID, "formularioResultadoNotas:j_id38:0:j_id70")
            if resultado_elements:
                # esperar a que el texto del resultado se materialice antes de capturar
                try:
                    WebDriverWait(self._driver, 5).until(
                        lambda d: d.find_element(
                            By.ID, "formularioResultadoNotas:j_id38:0:j_id70"
                        ).text.strip() != ""
                    )
                except TimeoutException:
                    self._logger.warning("Texto de resultado vacío tras espera; capturando igualmente")

                screenshot_path = f"{FOLDER_SCREENSHOT_PREFIX}/resultados_examen/{generate_random_string()}.png"
                self._driver.save_screenshot(screenshot_path)
                return {
                    "text": resultado_elements[0].text,
                    "screenshot_path": screenshot_path,
                }

            msg_error_elements = self._driver.find_elements(By.CLASS_NAME, "msgError")
            if msg_error_elements:
                msg_error = msg_error_elements[0].text
                if "No hay ningún registro para los datos introducidos" in msg_error:
                    return False

                if IS_DEBUG_MODE:
                    self._driver.save_screenshot(
                        f"{FOLDER_SCREENSHOT_PREFIX}/.debug/webpage_msg_error/{generate_random_string()}.png"
                    )
                raise Exception(f"Error encontrado: {msg_error}")

            rate_limit_elements = self._driver.find_elements(By.CLASS_NAME, "mensajeError")
            if rate_limit_elements and "operación solicitada no está disponible en estos momentos" in rate_limit_elements[0].text:
                if IS_DEBUG_MODE:
                    self._driver.save_screenshot(
                        f"{FOLDER_SCREENSHOT_PREFIX}/.debug/webpage_error/{generate_random_string()}.png"
                    )
                raise ServiceDown()

            # ni resultado, ni msgError, ni mensajeError: la página aún no muestra nada relevante, seguimos polleando
            time.sleep(POLL_INTERVAL)

        if IS_DEBUG_MODE:
            self._driver.save_screenshot(
                f"{FOLDER_SCREENSHOT_PREFIX}/.debug/webpage_error/{generate_random_string()}.png"
            )
        raise Exception("Tiempo máximo de espera superado sin obtener resultado ni mensaje de error")
