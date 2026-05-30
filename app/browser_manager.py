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

from config import config
from errors.ServiceDown import ServiceDown
from utils import generate_random_string

IDS_DGT_WEBSITE = [
    "formularioBusquedaNotas:nifnie",
    "formularioBusquedaNotas:fechaExamen",
    "formularioBusquedaNotas:clasepermiso",
    "formularioBusquedaNotas:fechaNacimiento",
]

RESULT_ID = "formularioResultadoNotas:j_id38:0:j_id70"
RATE_LIMIT_TEXT = "operación solicitada no está disponible en estos momentos"
NO_RECORD_TEXT = "No hay ningún registro para los datos introducidos"

URL = "https://sedeclave.dgt.gob.es/WEB_NOTP_CONSULTA/consultaNota.faces"


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
            WebDriverWait(self._driver, config.tiempo_espera_pagina).until(
                EC.presence_of_element_located((By.ID, IDS_DGT_WEBSITE[0]))
            )
        except TimeoutException:
            if config.is_debug_mode:
                self._driver.save_screenshot(
                    f"{config.folder_screenshot_prefix}/.debug/webpage_error/{generate_random_string()}.png"
                )
            raise Exception("La web de la DGT no cargó el formulario dentro del tiempo esperado")

    def fill_fields(self, datos_fields, max_attempts: int = 5):
        for intento in range(1, max_attempts + 1):
            indices_rellenados = set()
            for i, value in enumerate(datos_fields):
                # if i not in datos_rellenados: # TODO: Reviar si es necesario
                try:
                    element = WebDriverWait(self._driver, config.tiempo_espera_campo).until(
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
                limpiar_btn = WebDriverWait(self._driver, config.tiempo_espera_campo).until(
                    EC.element_to_be_clickable((By.XPATH, "//input[@title='Limpiar']"))
                )
                limpiar_btn.click()
            except (TimeoutException, NoSuchElementException, WebDriverException):
                if config.is_debug_mode:
                    self._driver.save_screenshot(
                        f"{config.folder_screenshot_prefix}/.debug/fallos_fill_fields/{generate_random_string()}.png"
                    )
                self.reset_website()

        if config.is_debug_mode:
            self._driver.save_screenshot(
                f"{config.folder_screenshot_prefix}/.debug/fallos_fill_fields_max_attempts/{generate_random_string()}.png"
            )
        raise Exception(f"No se pudieron llenar todos los campos después de {max_attempts} intentos")

    def submit_form(self):
        WebDriverWait(self._driver, config.tiempo_espera_campo).until(
            EC.element_to_be_clickable((By.XPATH, "//input[@title='Buscar']"))
        ).click()

    @staticmethod
    def _wait_for_result_or_error(driver):
        """WebDriverWait callable: returns (kind, element) when the page is ready,
        or False to keep polling.

        Kinds:
          - "result"     → el resultado del examen está disponible
          - "msg_error"  → mensaje de error (incluye "no hay registro")
          - "rate_limit" → SOLO cuando el texto coincide con el de servicio caído;
                           otros textos en .mensajeError se ignoran y seguimos polleando
        """
        resultado = driver.find_elements(By.ID, RESULT_ID)
        if resultado:
            return ("result", resultado[0])

        msg_error = driver.find_elements(By.CLASS_NAME, "msgError")
        if msg_error:
            return ("msg_error", msg_error[0])

        rate_limit = driver.find_elements(By.CLASS_NAME, "mensajeError")
        if rate_limit and RATE_LIMIT_TEXT in rate_limit[0].text:
            return ("rate_limit", rate_limit[0])

        return False

    def get_result(self):
        """Wait until the page shows a result, an error, or the timeout is hit."""
        try:
            kind, element = WebDriverWait(
                self._driver,
                config.tiempo_maximo_espera_resultados,
                poll_frequency=config.poll_interval,
            ).until(self._wait_for_result_or_error)
        except TimeoutException:
            if config.is_debug_mode:
                self._driver.save_screenshot(
                    f"{config.folder_screenshot_prefix}/.debug/webpage_error/{generate_random_string()}.png"
                )
            raise Exception("Tiempo máximo de espera superado sin obtener resultado ni mensaje de error")

        if kind == "result":
            # esperar a que el texto del resultado se materialice antes de capturar
            try:
                WebDriverWait(self._driver, 5).until(
                    lambda d: d.find_element(By.ID, RESULT_ID).text.strip() != ""
                )
            except TimeoutException:
                self._logger.warning("Texto de resultado vacío tras espera; capturando igualmente")

            screenshot_path = f"{config.folder_screenshot_prefix}/resultados_examen/{generate_random_string()}.png"
            self._driver.save_screenshot(screenshot_path)
            return {
                "text": element.text,
                "screenshot_path": screenshot_path,
            }

        if kind == "msg_error":
            msg_error_text = element.text
            if NO_RECORD_TEXT in msg_error_text:
                return False

            if config.is_debug_mode:
                self._driver.save_screenshot(
                    f"{config.folder_screenshot_prefix}/.debug/webpage_msg_error/{generate_random_string()}.png"
                )
            raise Exception(f"Error encontrado: {msg_error_text}")

        if kind == "rate_limit":
            if config.is_debug_mode:
                self._driver.save_screenshot(
                    f"{config.folder_screenshot_prefix}/.debug/webpage_error/{generate_random_string()}.png"
                )
            raise ServiceDown()

        # nunca debería llegar aquí: el closure sólo devuelve los tres kinds de arriba
        raise Exception(f"kind desconocido tras WebDriverWait: {kind!r}")
