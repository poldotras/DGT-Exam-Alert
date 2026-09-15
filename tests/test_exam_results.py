"""Tests for the per-exam result logic in services/exam_service.py, using mock doubles
for the DatabaseManager and TelegramBot (no real DB / browser / network). The history
registration it delegates to is covered in test_history_service.py."""
import _support  # noqa: F401  (installs sys.path + dep stubs; must be first)

import unittest
from unittest import mock

from services import exam_service as main
from domain.enums.status_enum import StatusEnum
from domain.enums.resultado_enum import ResultadoEnum


def _row(carnet="B", fecha="02/11/2022", calificacion="APTO", tipo="CIRCULACION"):
    return {"carnet": carnet, "fecha": fecha, "calificacion": calificacion, "tipo": tipo}


class ResultForExamenTests(unittest.TestCase):
    def test_matches_by_carnet_and_date(self):
        history = [_row(calificacion="APTO")]
        self.assertEqual(main._result_for_examen(history, "B", "02/11/2022"), ResultadoEnum.APTO)

    def test_no_match_returns_none(self):
        history = [_row(fecha="01/01/2000")]
        self.assertIsNone(main._result_for_examen(history, "B", "02/11/2022"))


class HandleResultTests(unittest.TestCase):
    def setUp(self):
        self.db = mock.Mock()
        self.db.get_pruebas_aprobadas.return_value = set()
        self.db.get_carnets_pendientes.return_value = set()
        self.db.registrar_resultado_prueba.return_value = False
        self.telegram = mock.Mock()
        self.logger = mock.Mock()
        self.exam_data = {"exam_id": 1, "persona_id": 2, "type": "B", "exam_date_str": "02/11/2022"}

    def test_aprobado_updates_state_and_notifies(self):
        result = {"history": [_row(calificacion="APTO")], "screenshot_path": "x.png"}
        main._handle_result(self.exam_data, result, self.db, self.telegram, self.logger)
        self.db.update_estado_examen.assert_any_call(1, StatusEnum.APPROVED.value)
        self.telegram.send_result.assert_called_once_with(True, "x.png")

    def test_suspendido_updates_state_and_notifies(self):
        result = {"history": [_row(calificacion="NO APTO")], "screenshot_path": "y.png"}
        main._handle_result(self.exam_data, result, self.db, self.telegram, self.logger)
        self.db.update_estado_examen.assert_any_call(1, StatusEnum.FAILED.value)
        self.telegram.send_result.assert_called_once_with(False, "y.png")

    def test_not_found_logs_critical_and_does_not_notify(self):
        result = {"history": [], "screenshot_path": None}
        main._handle_result(self.exam_data, result, self.db, self.telegram, self.logger)
        self.logger.critical.assert_called()
        self.telegram.send_result.assert_not_called()


if __name__ == "__main__":
    unittest.main()
