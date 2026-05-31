"""One-time application bootstrap: logging, Sentry, DB manager init, status seeding and
screenshot-folder preparation. Everything main() needs to wire up before the loop runs.
"""

import time
import os
import logging
from logging.handlers import RotatingFileHandler

import sentry_sdk

from config import config
from utils.fileutils import cleanup_old_files
from domain.enums.status_enum import STATUS_DB_NAMES
from adapters.database_manager import DatabaseManager

FOLDERS_TO_SAVE_SCREENSHOTS = ["resultados_examen"]
FOLDERS_TO_SAVE_DEBUG_SCREENSHOTS = [
    ".debug/fallos_fill_fields",
    ".debug/fallos_fill_fields_max_attempts",
    ".debug/webpage_error",
    ".debug/webpage_msg_error",
]


def setup_logger() -> logging.Logger:
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "{asctime} - {levelname} - {message}",
        style="{",
        datefmt="%d-%m-%Y %H:%M:%S UTC",
    )
    # Force UTC for log timestamps regardless of the container's TZ.
    # User-facing displays (Telegram) convert to Europe/Madrid explicitly via now_madrid().
    formatter.converter = time.gmtime

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


def setup_sentry(logger: logging.Logger) -> None:
    if not config.sentry_dsn:
        logger.info("Sentry disabled (no DSN configured)")
        return
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


def seed_statuses(db_manager: DatabaseManager, logger: logging.Logger) -> None:
    # Idempotent: insert only the status rows that are missing (names live in status_enum.py).
    try:
        existing_names = {s.nombre for s in db_manager.get_estados()}
        created = 0
        for _status_member, name in STATUS_DB_NAMES:
            if name not in existing_names:
                db_manager.create_estado(name)
                created += 1
        if created:
            logger.info(f"Statuses seeded: {created} new row(s) created")
    except Exception as e:
        logger.error(f"Error initializing statuses: {str(e)}")
        sentry_sdk.capture_exception(e)
        raise


def prepare_screenshot_folders(logger: logging.Logger) -> None:
    folders = FOLDERS_TO_SAVE_SCREENSHOTS + (
        FOLDERS_TO_SAVE_DEBUG_SCREENSHOTS if config.is_debug_mode else []
    )
    for folder in folders:
        folder_path = os.path.join(config.screenshot_folder_prefix, folder)
        os.makedirs(folder_path, exist_ok=True)
        # purge old screenshots so the volume doesn't grow unbounded
        try:
            removed = cleanup_old_files(folder_path, config.screenshot_retention_days)
            if removed:
                logger.info(
                    f"Screenshot cleanup in '{folder_path}': {removed} files removed"
                )
        except Exception as e:
            logger.warning(f"Could not clean '{folder_path}': {e}")
