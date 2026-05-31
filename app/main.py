"""Entry point: build the dependencies, run the one-time bootstrap (logging, Sentry, DB,
status seeding, screenshot folders) and hand off to the polling loop.

Personas and exams are managed entirely through the web panel (app/web); there is no
personas.json seeding anymore.
"""

import sentry_sdk

from config import config
from services.bootstrap import (
    setup_logger,
    setup_sentry,
    init_db_manager,
    seed_statuses,
    prepare_screenshot_folders,
)
from services.exam_service import run_loop
from adapters.browser_manager import BrowserManager
from adapters.telegram_bot import TelegramBot


def main() -> None:
    logger = setup_logger()
    setup_sentry(logger)

    db_manager = init_db_manager(logger)
    browser_manager = BrowserManager(logger=logger, sentry_sdk=sentry_sdk)
    telegram_bot = TelegramBot(
        token=config.telegram_bot_token,
        chat_id=config.telegram_chat_id,
        logger=logger,
    )

    seed_statuses(db_manager, logger)
    prepare_screenshot_folders(logger)

    run_loop(db_manager, browser_manager, telegram_bot, logger)


if __name__ == "__main__":
    main()
