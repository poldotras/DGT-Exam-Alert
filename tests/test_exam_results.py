"""Tests for the result/registration business logic in main.py, using mock doubles for
the DatabaseManager and TelegramBot (no real DB / browser / network)."""
import _support  # noqa: F401  (installs sys.path + dep stubs; must be first)

import unittest
from datetime import date
from unittest import mock

import main
from enums.status_enum import StatusEnum
from enums.resultado_enum import ResultadoEnum


def _row(carnet="B", fecha="02/11/2022", calificacion="APTO", tipo="CIRCULACION"):
    return {"carnet": carnet, "fecha": fecha, "calificacion": calificacion, "tipo": tipo}


class ResultForExamenTests(unittest.TestCase):
    def test_matches_by_carnet_and_date(self):
        history = [_row(calificacion="APTO")]
        self.assertEqual(main._result_for_examen(history, "B", "02/11/2022"), ResultadoEnum.APTO)

    def test_no_match_returns_none(self):
        history = [_row(fecha="01/01/2000")]
        self.assertIsNone(main._result_for_examen(history, "B", "02/11/2022"))


class RegisterHistoryTests(unittest.TestCase):
    def setUp(self):
        self.db = mock.Mock()
        self.logger = mock.Mock()

    def test_registers_parsed_row(self):
        self.db.registrar_resultado_prueba.return_value = True
        main._register_history(2, [_row(tipo="TEORICO COMUN")], self.db, self.logger)
        self.db.registrar_resultado_prueba.assert_called_once_with(
            2, "B", "teorico_comun", date(2022, 11, 2), "APTO"
        )

    def test_unknown_tipo_raises(self):
        with self.assertRaises(ValueError):
            main._register_history(2, [_row(tipo="NO EXISTE")], self.db, self.logger)

    def test_unparseable_date_is_stored_as_none(self):
        self.db.registrar_resultado_prueba.return_value = True
        main._register_history(2, [_row(fecha="bad-date")], self.db, self.logger)
        self.logger.warning.assert_called()
        _, args, _ = self.db.registrar_resultado_prueba.mock_calls[0]
        self.assertIsNone(args[3])  # fecha argument


class RegisterInferredTests(unittest.TestCase):
    def test_inferred_earlier_pass_is_registered(self):
        db = mock.Mock()
        db.get_pruebas_aprobadas.return_value = {("B", "circulacion")}
        db.registrar_resultado_prueba.return_value = True
        main._register_inferred(2, db, mock.Mock())
        # passing CIRCULACION of B implies TEORICO_COMUN of B, registered with no date
        db.registrar_resultado_prueba.assert_called_once_with(
            2, "B", "teorico_comun", None, "APTO"
        )


class ReconcileCompletedCarnetsTests(unittest.TestCase):
    def test_complete_carnet_cancels_pending(self):
        db = mock.Mock()
        db.get_pruebas_aprobadas.return_value = {("B", "teorico_comun"), ("B", "circulacion")}
        db.get_carnets_pendientes.return_value = {"B"}
        db.cancelar_pendientes_de_carnet.return_value = 1
        main._reconcile_completed_carnets(2, db, mock.Mock())
        db.cancelar_pendientes_de_carnet.assert_called_once_with(2, "B")

    def test_incomplete_carnet_is_not_cancelled(self):
        db = mock.Mock()
        db.get_pruebas_aprobadas.return_value = {("B", "circulacion")}  # no teorico_comun
        db.get_carnets_pendientes.return_value = {"B"}
        main._reconcile_completed_carnets(2, db, mock.Mock())
        db.cancelar_pendientes_de_carnet.assert_not_called()


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
