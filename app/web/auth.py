"""HTTP Basic Auth for the panel, checked against config.panel_user / panel_password.

If PANEL_PASSWORD is empty the panel is left open (auth skipped); create_app logs a loud
warning at startup so it is never silently unprotected.
"""
from flask import request, Response

from config import config


def _unauthorized():
    return Response(
        "Autenticación requerida.",
        401,
        {"WWW-Authenticate": 'Basic realm="DGT Panel"'},
    )


def require_auth():
    """Flask before_request hook: enforce Basic Auth unless PANEL_PASSWORD is unset.

    Static assets (style.css) are always served so the panel renders correctly — some
    browsers don't resend Basic Auth credentials for /static, leaving the page unstyled.
    """
    if not config.panel_password:
        return None  # auth disabled (warned at startup)
    if request.endpoint == "static":
        return None  # let CSS/static load without credentials
    auth = request.authorization
    if auth and auth.username == config.panel_user and auth.password == config.panel_password:
        return None
    return _unauthorized()
