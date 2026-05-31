"""Centralised configuration loaded from environment variables.

Reads each variable exactly once at import time and exposes them through a
frozen dataclass `config`. Other modules should `from config import config`
instead of calling `os.getenv` directly.
"""

import os
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _env_str(name: str, default: str = "") -> str:
    raw = os.getenv(name)
    return raw if raw is not None else default


def _env_bool(name: str, default: bool = False) -> bool:
    """Match the existing repo convention `bool(int(os.getenv(name, 0)))`,
    plus accept the more readable 'true'/'false' just in case."""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    lowered = raw.strip().lower()
    if lowered in ("0", "false", "no", "off"):
        return False
    if lowered in ("1", "true", "yes", "on"):
        return True
    # fallback to numeric interpretation
    try:
        return bool(int(lowered))
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    # Loop / business
    time_between_exams: int = field(default_factory=lambda: _env_int("TIEMPO_ENTRE_EXAMENES", 300))
    service_down_wait_time: int = field(default_factory=lambda: _env_int("TIEMPO_ESPERA_SERVICE_DOWN", 60))
    expired_after_days: int = field(default_factory=lambda: _env_int("DIAS_SE_CONSIDERA_CADUCADO", 7))

    # Selenium / browser
    max_result_wait_time: int = field(default_factory=lambda: _env_int("TIEMPO_MAXIMO_ESPERA_RESULTADOS", 300))
    field_wait_time: int = field(default_factory=lambda: _env_int("TIEMPO_ESPERA_CAMPO", 5))
    page_wait_time: int = field(default_factory=lambda: _env_int("TIEMPO_ESPERA_PAGINA", 15))
    # Hard cap for driver.get()/navigation. Must stay below Selenium's 120s client read
    # timeout so chromedriver aborts the page load first and raises a clean TimeoutException
    # instead of a raw urllib3 ReadTimeoutError (see Sentry DGT-ALERT-1W/1T/1V).
    page_load_timeout: int = field(default_factory=lambda: _env_int("TIEMPO_CARGA_PAGINA", 60))
    poll_interval: int = field(default_factory=lambda: _env_int("POLL_INTERVAL", 2))

    # Logging
    log_file: str = field(default_factory=lambda: _env_str("LOG_FILE", "app.log"))
    log_max_bytes: int = field(default_factory=lambda: _env_int("LOG_MAX_BYTES", 5 * 1024 * 1024))
    log_backup_count: int = field(default_factory=lambda: _env_int("LOG_BACKUP_COUNT", 5))

    # Screenshots
    screenshot_folder_prefix: str = field(default_factory=lambda: _env_str("FOLDER_SCREENSHOT_PREFIX", "screenshots"))
    screenshot_retention_days: int = field(default_factory=lambda: _env_int("DIAS_RETENCION_SCREENSHOTS", 30))

    # Modes
    is_debug_mode: bool = field(default_factory=lambda: _env_bool("DEBUG_APP", False))

    # External services
    sentry_dsn: str = field(default_factory=lambda: _env_str("SENTRY_DSN", ""))

    mysql_host: str = field(default_factory=lambda: _env_str("MYSQL_HOST", "database"))
    mysql_database: str = field(default_factory=lambda: _env_str("MYSQL_DATABASE", ""))
    mysql_user: str = field(default_factory=lambda: _env_str("MYSQL_USER", ""))
    mysql_password: str = field(default_factory=lambda: _env_str("MYSQL_PASSWORD", ""))

    telegram_bot_token: str = field(default_factory=lambda: _env_str("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: _env_str("TELEGRAM_CHAT_ID", ""))

    # Web panel (HTTP Basic Auth + listening port)
    panel_user: str = field(default_factory=lambda: _env_str("PANEL_USER", "admin"))
    panel_password: str = field(default_factory=lambda: _env_str("PANEL_PASSWORD", ""))
    panel_port: int = field(default_factory=lambda: _env_int("PANEL_PORT", 8000))


# Singleton instantiated at import time
config = Config()
