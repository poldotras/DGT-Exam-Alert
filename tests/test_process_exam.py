"""Tests for process_exam orchestration in main.py. time.sleep is patched so the test
doesn't actually wait; browser / db / telegram are mocks."""
import _support  # noqa: F401  (installs sys.path + dep stubs; must be first)

import unittest
from unittest import mock

import main
from enums.status_enum import StatusEnum
from errors.ServiceDown import ServiceDown


def _exam(date_str="02/11/2022"):
    return {
        "exam_id": 1,
        "persona_id": 2,
        "nif": "12345678Z",
        "exam_date_str": date_str,
        "type": "B",
        "birthdate_str": "18/08/2004",
    }


class ProcessExamTests(unittest.TestCase):
    def setUp(self):
        self.browser = mock.Mock()
        self.db = mock.Mock()
        self.db.get_pruebas_aprobadas.return_value = set()
        self.db.get_carnets_pendientes.return_value = set()
        self.telegram = mock.Mock()
        self.logger = mock.Mock()

    def test_marks_reviewing_before_search(self):
        self.browser.get_result.return_value = False
        with mock.patch("main.time.sleep"):
            main.process_exam(_exam(), self.browser, self.telegram, self.db, self.logger)
        self.db.update_estado_examen.assert_any_call(1, StatusEnum.REVIEWING.value)

    def test_no_record_and_old_exam_is_marked_expired(self):
        self.browser.get_result.return_value = False
        with mock.patch("main.time.sleep"):
            main.process_exam(_exam("01/01/2000"), self.browser, self.telegram, self.db, self.logger)
        self.db.update_estado_examen.assert_any_call(1, StatusEnum.REVIEWED_EXPIRED.value)

    def test_no_record_and_recent_exam_is_not_expired(self):
        self.browser.get_result.return_value = False
        future = "31/12/2099"
        with mock.patch("main.time.sleep"):
            main.process_exam(_exam(future), self.browser, self.telegram, self.db, self.logger)
        states = [c.args[1] for c in self.db.update_estado_examen.call_args_list]
        self.assertNotIn(StatusEnum.REVIEWED_EXPIRED.value, states)

    def test_result_dict_handles_and_pings_alive(self):
        self.browser.get_result.return_value = {"history": [], "screenshot_path": None}
        with mock.patch("main.time.sleep"):
            main.process_exam(_exam(), self.browser, self.telegram, self.db, self.logger)
        self.telegram.update_alive_status.assert_called_once()

    def test_service_down_backs_off_without_crashing(self):
        self.browser.reset_website.side_effect = ServiceDown()
        with mock.patch("main.time.sleep") as sleep:
            main.process_exam(_exam(), self.browser, self.telegram, self.db, self.logger)
        self.logger.warning.assert_called()
        sleep.assert_called()  # backed off

    def test_unexpected_error_is_captured_not_raised(self):
        self.browser.reset_website.side_effect = RuntimeError("boom")
        with mock.patch("main.time.sleep"), mock.patch("main.traceback.print_exc"):
            main.process_exam(_exam(), self.browser, self.telegram, self.db, self.logger)
        self.logger.error.assert_called()


if __name__ == "__main__":
    unittest.main()
