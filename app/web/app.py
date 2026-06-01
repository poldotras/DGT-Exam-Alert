"""Flask app factory for the management panel.

Reuses the bot's DatabaseManager (shared MySQL) and domain logic; server-rendered with
Jinja2 and protected by HTTP Basic Auth. Run with gunicorn via the factory:

    gunicorn --bind 0.0.0.0:8000 --chdir /app "web.app:create_app()"
"""
import logging

from flask import Flask

from config import config
from adapters.database_manager import DatabaseManager
from web.auth import require_auth
from web.routes_personas import bp as personas_bp
from web.routes_examenes import bp as examenes_bp
from web.routes_pwa import bp as pwa_bp


def _build_logger():
    logger = logging.getLogger("panel")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def create_app(db=None):
    """Build the Flask app. Pass `db` (a DatabaseManager double) in tests to avoid a real
    MySQL connection; in production it is built from config.
    """
    app = Flask(__name__)
    app.secret_key = config.panel_password or "dev-insecure-key"  # signs flash cookies

    logger = _build_logger()
    if not config.panel_password:
        logger.warning("PANEL_PASSWORD vacío: el panel queda SIN autenticación (Basic Auth desactivada)")

    # Shared DB: same MySQL as the bot. DatabaseManager ensures the tables exist.
    app.config["DB"] = db if db is not None else DatabaseManager(
        host=config.mysql_host,
        database=config.mysql_database,
        user=config.mysql_user,
        password=config.mysql_password,
        logger=logger,
    )

    app.before_request(require_auth)
    app.register_blueprint(personas_bp)
    app.register_blueprint(examenes_bp)
    app.register_blueprint(pwa_bp)
    return app
