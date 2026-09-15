"""Tests for services/history_service.py — persisting a scraped DGT prueba history
(registration, inferred passes, carnet reconciliation) with a mocked DatabaseManager."""
import _support  # noqa: F401  (installs sys.path + dep stubs; must be first)

import unittest
from datetime import date
from unittest import mock

from services import history_service


def _row(carnet="B", fecha="02/11/2022", calificacion="APTO", tipo="CIRCULACION"):
    return {"carnet": carnet, "fecha": fecha, "calificacion": calificacion, "tipo": tipo}


class RegisterHistoryTests(unittest.TestCase):
    def setUp(self):
        self.db = mock.Mock()
        self.logger = mock.Mock()

    def test_registers_parsed_row(self):
        self.db.registrar_resultado_prueba.return_value = True
        history_service.register_history(2, [_row(tipo="TEORICO COMUN")], self.db, self.logger)
        self.db.registrar_resultado_prueba.assert_called_once_with(
            2, "B", "teorico_comun", date(2022, 11, 2), "APTO"
        )

    def test_unknown_tipo_raises(self):
        with self.assertRaises(ValueError):
            history_service.register_history(2, [_row(tipo="NO EXISTE")], self.db, self.logger)

    def test_unparseable_date_is_stored_as_none(self):
        self.db.registrar_resultado_prueba.return_value = True
        history_service.register_history(2, [_row(fecha="bad-date")], self.db, self.logger)
        self.logger.warning.assert_called()
        _, args, _ = self.db.registrar_resultado_prueba.mock_calls[0]
        self.assertIsNone(args[3])  # fecha argument


class RegisterInferredTests(unittest.TestCase):
    def test_inferred_earlier_pass_is_registered(self):
        db = mock.Mock()
        db.get_pruebas_aprobadas.return_value = {("B", "circulacion")}
        db.registrar_resultado_prueba.return_value = True
        history_service.register_inferred(2, db, mock.Mock())
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
        history_service.reconcile_completed_carnets(2, db, mock.Mock())
        db.cancelar_pendientes_de_carnet.assert_called_once_with(2, "B")

    def test_incomplete_carnet_is_not_cancelled(self):
        db = mock.Mock()
        db.get_pruebas_aprobadas.return_value = {("B", "circulacion")}  # no teorico_comun
        db.get_carnets_pendientes.return_value = {"B"}
        history_service.reconcile_completed_carnets(2, db, mock.Mock())
        db.cancelar_pendientes_de_carnet.assert_not_called()


class SyncPersonaHistoryTests(unittest.TestCase):
    def test_runs_the_three_steps(self):
        db = mock.Mock()
        db.get_pruebas_aprobadas.return_value = set()
        db.get_carnets_pendientes.return_value = set()
        db.registrar_resultado_prueba.return_value = True
        history_service.sync_persona_history(2, [_row()], db, mock.Mock())
        db.registrar_resultado_prueba.assert_called()
        db.get_carnets_pendientes.assert_called_once_with(2)

    def test_unknown_label_is_swallowed_not_raised(self):
        # an unknown DGT label must reach Sentry, never break the caller's flow
        db = mock.Mock()
        logger = mock.Mock()
        history_service.sync_persona_history(2, [_row(tipo="NO EXISTE")], db, logger)
        logger.error.assert_called()


if __name__ == "__main__":
    unittest.main()
