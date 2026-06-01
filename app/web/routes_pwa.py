"""Blueprint: PWA plumbing so the panel can be installed as an app on iOS and Android.

Serves two files from the site root (not from /static) so they get the right scope and
content type:

- ``/manifest.webmanifest`` — the web app manifest (name, icons, colors, display mode).
- ``/sw.js`` — the service worker, served at root so its scope covers the whole panel.

Icons live in ``static/icons`` and are served by Flask's normal static endpoint. These
endpoints are exempted from Basic Auth in ``web.auth`` so the browser can read the manifest
(fetched without credentials by default) and register the worker before the user logs in.
"""
import os

from flask import Blueprint, Response, current_app, url_for

bp = Blueprint("pwa", __name__)


@bp.route("/manifest.webmanifest")
def manifest():
    data = {
        "id": "/",
        "name": "DGT Exam Alert",
        "short_name": "DGT Panel",
        "description": "Panel para gestionar los avisos de exámenes de la DGT.",
        "lang": "es",
        "dir": "ltr",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait-primary",
        "background_color": "#f8fafc",
        "theme_color": "#0f172a",
        "icons": [
            {"src": url_for("static", filename="icons/icon-192.png"),
             "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": url_for("static", filename="icons/icon-512.png"),
             "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": url_for("static", filename="icons/icon-maskable-192.png"),
             "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
            {"src": url_for("static", filename="icons/icon-maskable-512.png"),
             "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    resp = current_app.response_class(
        response=current_app.json.dumps(data),
        mimetype="application/manifest+json",
    )
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.route("/sw.js")
def service_worker():
    """Serve the worker from root scope so it can control every page of the panel.

    The script body lives in ``static/sw.js``; we serve it from the site root (not /static)
    so its scope is "/". ``no-cache`` makes the browser revalidate it, which is how service
    worker updates get picked up.
    """
    with open(os.path.join(current_app.static_folder, "sw.js"), encoding="utf-8") as fh:
        body = fh.read()
    resp = Response(body, mimetype="application/javascript")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp
