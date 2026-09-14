"""Tests for services/audit_service.py — the once-a-day-per-persona re-read of the DGT
prueba history that catches exams nobody registered in the panel. Browser, DB and Telegram
are mock doubles; config and time.sleep are patched so nothing waits."""
import _support  # noqa: F401  (installs sys.path + dep stubs; must be first)

import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock

from services import audit_service
from domain.enums.status_enum import StatusEnum
from domain.errors import ServiceDown

HOY = date(2026, 3, 10)

_CONFIG = SimpleNamespace(audit_enabled=True, time_between_exams=0, service_down_wait_time=0)


def _row(carnet="B", fecha="02/11/2022", calificacion="APTO", tipo="CIRCULACION"):
    return {"carnet": carnet, "fecha": fecha, "calificacion": calificacion, "tipo": tipo}


def _persona(persona_id=2):
    return SimpleNamespace(
        id=persona_id, nif="12345678Z", nombre="Ada", fecha_nacimiento=date(2004, 8, 18),
    )


class ExamenesNoControladosTests(unittest.TestCase):
    def test_row_without_a_registered_exam_is_reported(self):
        nuevos = audit_service.examenes_no_controlados([_row()], set())
        self.assertEqual(
            nuevos, [{"carnet": "B", "fecha": date(2022, 11, 2), "aprobado": True}]
        )

    def test_registered_exam_is_ignored(self):
        registrados = {("B", date(2022, 11, 2))}
        self.assertEqual(audit_service.examenes_no_controlados([_row()], registrados), [])

    def test_dateless_row_is_ignored(self):
        # inferred passes are stored without a date and never correspond to an exam day
        self.assertEqual(audit_service.examenes_no_controlados([_row(fecha="")], set()), [])

    def test_same_day_pruebas_collapse_into_one_exam(self):
        history = [_row(tipo="TEORICO COMUN"), _row(tipo="CIRCULACION")]
        nuevos = audit_service.examenes_no_controlados(history, set())
        self.assertEqual(len(nuevos), 1)

    def test_one_no_apto_marks_the_day_as_failed(self):
        history = [_row(tipo="TEORICO COMUN"), _row(tipo="CIRCULACION", calificacion="NO APTO")]
        nuevos = audit_service.examenes_no_controlados(history, set())
        self.assertFalse(nuevos[0]["aprobado"])

    def test_results_are_ordered_by_date(self):
        history = [_row(fecha="05/03/2026"), _row(carnet="A2", fecha="01/02/2026")]
        nuevos = audit_service.examenes_no_controlados(history, set())
        self.assertEqual([n["fecha"] for n in nuevos], [date(2026, 2, 1), date(2026, 3, 5)])

    def test_unknown_carnet_raises(self):
        with self.assertRaises(ValueError):
            audit_service.examenes_no_controlados([_row(carnet="ZZ")], set())

    def test_unknown_calificacion_raises(self):
        with self.assertRaises(ValueError):
            audit_service.examenes_no_controlados([_row(calificacion="REGULAR")], set())


class MensajeExamenesNuevosTests(unittest.TestCase):
    def _nuevos(self, cuantos):
        return [
            {"carnet": "B", "fecha": date(2026, 3, 1 + i), "aprobado": True}
            for i in range(cuantos)
        ]

    def test_lists_every_exam_when_there_are_few(self):
        texto = audit_service._mensaje_examenes_nuevos(_persona(), self._nuevos(2))
        self.assertIn("B — 01/03/2026 — APROBADO", texto)
        self.assertIn("B — 02/03/2026 — APROBADO", texto)
        self.assertIn("Ada", texto)

    def test_long_lists_are_capped_with_a_counter(self):
        # the first audit can surface a whole pre-bot history; Telegram caps at ~4096 chars
        cuantos = audit_service.MAX_ALERT_LINES + 4
        texto = audit_service._mensaje_examenes_nuevos(_persona(), self._nuevos(cuantos))
        self.assertEqual(texto.count("•"), audit_service.MAX_ALERT_LINES)
        self.assertIn("y 4 más", texto)

    def test_name_is_html_escaped(self):
        persona = _persona()
        persona.nombre = "Ada <b>"
        texto = audit_service._mensaje_examenes_nuevos(persona, self._nuevos(1))
        self.assertIn("Ada &lt;b&gt;", texto)


class AuditPersonaTests(unittest.TestCase):
    def setUp(self):
        self.db = mock.Mock()
        self.db.get_fechas_con_resultado.return_value = [("B", date(2022, 11, 2))]
        self.db.get_examenes_registrados.return_value = set()
        self.db.get_pruebas_aprobadas.return_value = set()
        self.db.get_carnets_pendientes.return_value = set()
        self.db.registrar_resultado_prueba.return_value = False
        self.browser = mock.Mock()
        self.telegram = mock.Mock()
        self.logger = mock.Mock()
        patcher = mock.patch.multiple(audit_service, config=_CONFIG, time=mock.Mock())
        patcher.start()
        self.addCleanup(patcher.stop)

    def _audit(self, persona=None):
        return audit_service.audit_persona(
            persona or _persona(), self.db, self.browser, self.telegram, self.logger, HOY,
        )

    def test_without_known_dates_it_only_records_the_run(self):
        self.db.get_fechas_con_resultado.return_value = []
        self.assertTrue(self._audit())
        self.browser.submit_form.assert_not_called()
        self.db.marcar_auditoria.assert_called_once_with(2, HOY)

    def test_untracked_exam_is_registered_with_its_result_and_notified(self):
        self.browser.get_result.return_value = {
            "history": [_row(fecha="05/03/2026", calificacion="NO APTO")], "screenshot_path": "x.png",
        }
        self.assertTrue(self._audit())
        self.db.create_examen.assert_called_once_with(
            persona_id=2, fecha_examen=date(2026, 3, 5), tipo_examen="B",
            estado_id=StatusEnum.FAILED.value,
        )
        self.telegram.send_message.assert_called_once()
        self.db.marcar_auditoria.assert_called_once_with(2, HOY)

    def test_already_registered_exam_is_not_reported(self):
        self.browser.get_result.return_value = {"history": [_row()], "screenshot_path": "x.png"}
        self.db.get_examenes_registrados.return_value = {("B", date(2022, 11, 2))}
        self.assertTrue(self._audit())
        self.db.create_examen.assert_not_called()
        self.telegram.send_message.assert_not_called()
        self.db.marcar_auditoria.assert_called_once_with(2, HOY)

    def test_history_is_synced_even_when_nothing_is_missing(self):
        self.browser.get_result.return_value = {"history": [_row()], "screenshot_path": "x.png"}
        self.db.get_examenes_registrados.return_value = {("B", date(2022, 11, 2))}
        self.db.registrar_resultado_prueba.return_value = True
        self._audit()
        self.db.registrar_resultado_prueba.assert_any_call(
            2, "B", "circulacion", date(2022, 11, 2), "APTO"
        )

    def test_search_uses_the_persona_and_the_known_exam(self):
        self.browser.get_result.return_value = {"history": [], "screenshot_path": None}
        self._audit()
        self.browser.fill_fields.assert_called_once_with(
            ["12345678Z", "02/11/2022", "B", "18/08/2004"]
        )

    def test_no_record_falls_back_to_an_older_known_date(self):
        self.db.get_fechas_con_resultado.return_value = [
            ("B", date(2026, 3, 5)), ("A2", date(2025, 1, 7)),
        ]
        self.browser.get_result.side_effect = [False, {"history": [], "screenshot_path": None}]
        self.assertTrue(self._audit())
        self.assertEqual(self.browser.submit_form.call_count, 2)

    def test_purged_records_still_count_as_the_daily_pass(self):
        # "no hay ningún registro" is definitive (an outage raises instead), so retrying
        # the same dates for the rest of the day would only burn DGT searches
        self.browser.get_result.return_value = False
        self.assertTrue(self._audit())
        self.logger.warning.assert_called()
        self.db.create_examen.assert_not_called()
        self.db.marcar_auditoria.assert_called_once_with(2, HOY)

    def test_unparseable_history_still_counts_as_the_daily_pass(self):
        # a label we don't contemplate must not leave the persona due (it would re-query
        # the very same page on every loop iteration until midnight)
        self.browser.get_result.return_value = {
            "history": [_row(calificacion="REGULAR")], "screenshot_path": "x.png",
        }
        self.assertTrue(self._audit())
        self.logger.error.assert_called()
        self.db.create_examen.assert_not_called()
        self.db.marcar_auditoria.assert_called_once_with(2, HOY)

    def test_tries_at_most_the_capped_number_of_dates(self):
        self.db.get_fechas_con_resultado.return_value = [
            ("B", date(2026, 3, d)) for d in range(1, 8)
        ]
        self.browser.get_result.return_value = False
        self._audit()
        self.assertEqual(self.browser.submit_form.call_count, audit_service.MAX_CANDIDATE_DATES)


class RunDueAuditTests(unittest.TestCase):
    def setUp(self):
        self.db = mock.Mock()
        self.browser = mock.Mock()
        self.telegram = mock.Mock()
        self.logger = mock.Mock()
        patcher = mock.patch.multiple(audit_service, config=_CONFIG, time=mock.Mock())
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self):
        return audit_service.run_due_audit(self.db, self.browser, self.telegram, self.logger)

    def test_disabled_does_nothing(self):
        with mock.patch.object(audit_service, "config", SimpleNamespace(audit_enabled=False)):
            self.assertFalse(self._run())
        self.db.get_personas_a_auditar.assert_not_called()

    def test_nothing_due_returns_false(self):
        self.db.get_personas_a_auditar.return_value = []
        self.assertFalse(self._run())

    def test_audits_only_the_first_persona_due(self):
        self.db.get_personas_a_auditar.return_value = [_persona(2), _persona(3)]
        self.db.get_fechas_con_resultado.return_value = []
        self.assertTrue(self._run())
        self.db.marcar_auditoria.assert_called_once_with(2, mock.ANY)

    def test_service_down_backs_off_without_crashing(self):
        self.db.get_personas_a_auditar.return_value = [_persona()]
        self.db.get_fechas_con_resultado.return_value = [("B", date(2022, 11, 2))]
        self.browser.reset_website.side_effect = ServiceDown()
        self.assertFalse(self._run())
        self.logger.warning.assert_called()
        self.db.marcar_auditoria.assert_not_called()

    def test_unexpected_error_is_captured_not_raised(self):
        self.db.get_personas_a_auditar.side_effect = RuntimeError("boom")
        self.assertFalse(self._run())
        self.logger.error.assert_called()


if __name__ == "__main__":
    unittest.main()
