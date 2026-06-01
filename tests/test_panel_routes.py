"""Flask route tests for the panel, using the test client with a mocked DatabaseManager.

Requires Flask, which is NOT installed on the host (no pip) — the whole class is skipped
there. It runs anywhere Flask is available (the panel container, CI, or a local venv):

    PANEL_PASSWORD= python3 -m unittest tests.test_panel_routes
"""
import _support  # noqa: F401  (installs sys.path + dep stubs; must be first)

import json
import unittest
from types import SimpleNamespace
from unittest import mock

try:
    import flask  # noqa: F401
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False


@unittest.skipUnless(HAS_FLASK, "Flask no instalado (los tests de rutas corren en el contenedor del panel)")
class PanelRoutesTests(unittest.TestCase):
    def setUp(self):
        from web.app import create_app
        # force auth OFF for the route tests, regardless of the env's PANEL_PASSWORD
        patcher = mock.patch("web.auth.config", SimpleNamespace(panel_user="admin", panel_password=""))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.db = mock.Mock()
        self.db.get_all_personas.return_value = []
        self.db.get_examenes_activos.return_value = []
        app = create_app(db=self.db)
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_home_ok(self):
        # the home shows personas + exams under review on one page
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_create_persona_invalid_nif_rerenders_without_creating(self):
        resp = self.client.post("/personas", data={
            "nif": "malo", "nombre": "Ada", "fecha_nacimiento": "18/08/2004"})
        self.assertEqual(resp.status_code, 400)
        self.db.create_persona.assert_not_called()

    def test_create_persona_valid_creates_and_redirects(self):
        self.db.get_persona_by_nif.return_value = None
        self.db.create_persona.return_value = mock.Mock(id=7)
        resp = self.client.post("/personas", data={
            "nif": "12345678Z", "nombre": "Ada", "fecha_nacimiento": "18/08/2004"})
        self.assertEqual(resp.status_code, 302)
        self.db.create_persona.assert_called_once()

    def test_add_examen_invalid_carnet_does_not_create(self):
        self.db.get_persona_by_id.return_value = mock.Mock(id=1)
        resp = self.client.post("/personas/1/examenes", data={
            "carnet": "ZZ", "fecha_examen": "02/11/2022"})
        self.assertEqual(resp.status_code, 302)
        self.db.create_examen.assert_not_called()

    def test_add_examen_valid_creates(self):
        self.db.get_persona_by_id.return_value = mock.Mock(id=1)
        self.db.get_examenes_by_persona_id.return_value = []
        resp = self.client.post("/personas/1/examenes", data={
            "carnet": "B", "fecha_examen": "02/11/2022"})
        self.assertEqual(resp.status_code, 302)
        self.db.create_examen.assert_called_once()

    def test_add_examen_range_creates_one_per_day(self):
        self.db.get_persona_by_id.return_value = mock.Mock(id=1)
        self.db.get_examenes_by_persona_id.return_value = []
        resp = self.client.post("/personas/1/examenes", data={
            "carnet": "B", "fecha_examen": "01/01/2030", "fecha_fin": "03/01/2030"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.db.create_examen.call_count, 3)  # 3-day inclusive range

    def test_cancelar_examen_sets_cancelled_and_redirects(self):
        from domain.enums.status_enum import StatusEnum
        resp = self.client.post("/examenes/5/cancelar")
        self.assertEqual(resp.status_code, 302)
        self.db.update_estado_examen.assert_called_once_with(5, StatusEnum.CANCELLED.value)

    def test_basic_auth_blocks_when_password_set(self):
        with mock.patch("web.auth.config", SimpleNamespace(panel_user="admin", panel_password="secret")):
            self.assertEqual(self.client.get("/").status_code, 401)


@unittest.skipUnless(HAS_FLASK, "Flask no instalado (los tests de rutas corren en el contenedor del panel)")
class PanelPwaTests(unittest.TestCase):
    """PWA plumbing that makes the panel installable as an app on iOS and Android."""

    def _client(self, password=""):
        from web.app import create_app
        patcher = mock.patch("web.auth.config", SimpleNamespace(panel_user="admin", panel_password=password))
        patcher.start()
        self.addCleanup(patcher.stop)
        db = mock.Mock()
        db.get_all_personas.return_value = []
        db.get_examenes_activos.return_value = []
        app = create_app(db=db)
        app.config.update(TESTING=True)
        return app.test_client()

    def test_manifest_served_with_required_fields(self):
        resp = self._client().get("/manifest.webmanifest")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["Content-Type"], "application/manifest+json")
        data = json.loads(resp.data)
        # the minimum an installable PWA needs: standalone display, start_url, and 192/512 icons
        self.assertEqual(data["display"], "standalone")
        self.assertEqual(data["start_url"], "/")
        icons = {(i["sizes"], i["purpose"]) for i in data["icons"]}
        self.assertIn(("192x192", "any"), icons)
        self.assertIn(("512x512", "any"), icons)
        self.assertIn(("512x512", "maskable"), icons)

    def test_service_worker_served_at_root_with_fetch_handler(self):
        resp = self._client().get("/sw.js")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("javascript", resp.headers["Content-Type"])
        # root scope is what lets the worker control every page of the panel
        self.assertEqual(resp.headers.get("Service-Worker-Allowed"), "/")
        # a fetch handler is required for the install criteria on Android/Chrome
        self.assertIn(b'addEventListener("fetch"', resp.data)

    def test_manifest_and_worker_bypass_auth(self):
        # With a password set the panel is locked, but the browser must still read the
        # manifest and register the worker (without credentials) to offer "install".
        client = self._client(password="secret")
        self.assertEqual(client.get("/").status_code, 401)
        self.assertEqual(client.get("/manifest.webmanifest").status_code, 200)
        self.assertEqual(client.get("/sw.js").status_code, 200)


if __name__ == "__main__":
    unittest.main()
