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

DGT_FORM_FIELD_IDS = [
    "formularioBusquedaNotas:nifnie",
    "formularioBusquedaNotas:fechaExamen",
    "formularioBusquedaNotas:clasepermiso",
    "formularioBusquedaNotas:fechaNacimiento",
]

RESULT_ID = "formularioResultadoNotas:j_id38:0:j_id70"
# Strings the DGT page renders verbatim in Spanish — these are external contracts, do not translate
RATE_LIMIT_TEXT = "operación solicitada no está disponible en estos momentos"
NO_RECORD_TEXT = "No hay ningún registro para los datos introducidos"

URL = "https://sedeclave.dgt.gob.es/WEB_NOTP_CONSULTA/consultaNota.faces"


class BrowserManager:
    def __init__(self, logger, sentry_sdk):
        self._logger = logger
        self._sentry_sdk = sentry_sdk
        self._driver = self._create_driver()
        self._logger.info("Browser started")

    def _create_driver(self):
        """Create and configure a headless Chrome webdriver instance."""
        options = Options()
        options.add_argument("--log-level=3")   # reduce logging noise
        options.add_argument("--headless")      # run in headless mode for better performance and no UI
        options.add_argument("--incognito")     # use incognito to avoid caching issues
        options.add_argument("--disable-gpu")   # recommended for headless mode
        options.add_argument("--no-sandbox")    # required for some Linux environments

        driver = webdriver.Chrome(options=options)
        # implicit_wait still active for singular find_element calls in the form flow;
        # the plural find_elements used in get_result polling return [] instantly anyway.
        driver.implicitly_wait(2)
        # Abort a hanging navigation before Selenium's 120s client read timeout fires,
        # so we get a clean TimeoutException instead of a raw ReadTimeoutError.
        driver.set_page_load_timeout(config.page_load_timeout)
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
        self._logger.warning("Dead driver session detected, recreating browser")
        try:
            self._driver.quit()
        except Exception:
            pass
        self._driver = self._create_driver()

    def reset_website(self):
        """Navigate to the DGT website and wait for the form to be ready."""
        self._ensure_driver()
        # driver.get() can hang if the DGT site is slow/down; set_page_load_timeout makes it
        # raise TimeoutException instead. Treat that as a transient outage (ServiceDown) so the
        # main loop backs off and retries rather than spamming Sentry (see DGT-ALERT-1W).
        try:
            self._driver.get(URL)
        except TimeoutException:
            self._logger.warning("Timed out loading the DGT site (page load timeout)")
            raise ServiceDown()
        # wait for the first form field to be present instead of a blind sleep
        try:
            WebDriverWait(self._driver, config.page_wait_time).until(
                EC.presence_of_element_located((By.ID, DGT_FORM_FIELD_IDS[0]))
            )
        except TimeoutException:
            if config.is_debug_mode:
                self._driver.save_screenshot(
                    f"{config.screenshot_folder_prefix}/.debug/webpage_error/{generate_random_string()}.png"
                )
            raise Exception("The DGT site did not load the form within the expected time")

    def fill_fields(self, form_fields, max_attempts: int = 5):
        for attempt in range(1, max_attempts + 1):
            filled_indices = set()
            for i, value in enumerate(form_fields):
                # if i not in datos_rellenados: # TODO: Reviar si es necesario
                try:
                    element = WebDriverWait(self._driver, config.field_wait_time).until(
                        EC.element_to_be_clickable((By.ID, DGT_FORM_FIELD_IDS[i]))
                    )
                    element.send_keys(value)
                    filled_indices.add(i)
                except (TimeoutException, NoSuchElementException, ElementNotInteractableException) as e:
                    self._logger.debug(f"Field {DGT_FORM_FIELD_IDS[i]} unavailable on attempt {attempt}: {e}")

            if len(filled_indices) == len(form_fields):
                return

            self._logger.info(
                f"Attempt {attempt}/{max_attempts} to fill the form, "
                f"fields completed: {len(filled_indices)}/{len(form_fields)}"
            )

            try:
                clear_btn = WebDriverWait(self._driver, config.field_wait_time).until(
                    EC.element_to_be_clickable((By.XPATH, "//input[@title='Limpiar']"))
                )
                clear_btn.click()
            except (TimeoutException, NoSuchElementException, WebDriverException):
                if config.is_debug_mode:
                    self._driver.save_screenshot(
                        f"{config.screenshot_folder_prefix}/.debug/fallos_fill_fields/{generate_random_string()}.png"
                    )
                self.reset_website()

        if config.is_debug_mode:
            self._driver.save_screenshot(
                f"{config.screenshot_folder_prefix}/.debug/fallos_fill_fields_max_attempts/{generate_random_string()}.png"
            )
        raise Exception(f"Could not fill all fields after {max_attempts} attempts")

    def submit_form(self):
        # The click submits the form (a navigation). Like reset_website, it can hit the
        # page load timeout if the DGT backend stalls (see DGT-ALERT-1T) — treat as ServiceDown.
        try:
            WebDriverWait(self._driver, config.field_wait_time).until(
                EC.element_to_be_clickable((By.XPATH, "//input[@title='Buscar']"))
            ).click()
        except TimeoutException as e:
            # Distinguish the two TimeoutException sources: the WebDriverWait (button never
            # clickable) vs the page-load timeout from the navigation the click triggers.
            # Both mean the site isn't responding usefully; back off via ServiceDown.
            self._logger.warning(f"Timed out submitting the search form: {e}")
            raise ServiceDown()

    @staticmethod
    def _wait_for_result_or_error(driver):
        """WebDriverWait callable: returns (kind, element) when the page is ready,
        or False to keep polling.

        Kinds:
          - "result"     → the exam result is available
          - "msg_error"  → error message (includes "no record" case)
          - "rate_limit" → ONLY when the text matches the service-down banner;
                           other texts inside .mensajeError are ignored and polling continues
        """
        result = driver.find_elements(By.ID, RESULT_ID)
        if result:
            return ("result", result[0])

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
                config.max_result_wait_time,
                poll_frequency=config.poll_interval,
            ).until(self._wait_for_result_or_error)
        except TimeoutException:
            if config.is_debug_mode:
                self._driver.save_screenshot(
                    f"{config.screenshot_folder_prefix}/.debug/webpage_error/{generate_random_string()}.png"
                )
            raise Exception("Maximum wait time exceeded without a result or error message")

        if kind == "result":
            # wait for the result text to materialise before capturing the screenshot
            try:
                WebDriverWait(self._driver, 5).until(
                    lambda d: d.find_element(By.ID, RESULT_ID).text.strip() != ""
                )
            except TimeoutException:
                self._logger.warning("Result text empty after wait; capturing anyway")

            screenshot_path = f"{config.screenshot_folder_prefix}/resultados_examen/{generate_random_string()}.png"
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
                    f"{config.screenshot_folder_prefix}/.debug/webpage_msg_error/{generate_random_string()}.png"
                )
            raise Exception(f"Error found: {msg_error_text}")

        if kind == "rate_limit":
            if config.is_debug_mode:
                self._driver.save_screenshot(
                    f"{config.screenshot_folder_prefix}/.debug/webpage_error/{generate_random_string()}.png"
                )
            raise ServiceDown()

        # should never get here: the closure only returns the three kinds above
        raise Exception(f"Unknown kind after WebDriverWait: {kind!r}")
