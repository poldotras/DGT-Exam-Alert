"""Tests for the stdlib-only helpers in utils.py."""
import _support  # noqa: F401  (installs sys.path + dep stubs; must be first)

import os
import time
import tempfile
import unittest
from datetime import date, datetime
from unittest import mock

import utils


class GenerateRandomStringTests(unittest.TestCase):
    def test_default_length(self):
        self.assertEqual(len(utils.generate_random_string()), 6)

    def test_custom_length_and_charset(self):
        s = utils.generate_random_string(20)
        self.assertEqual(len(s), 20)
        self.assertTrue(s.isalnum())


class CleanupOldFilesTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))

    def _touch(self, name, age_days=0):
        path = os.path.join(self.dir, name)
        open(path, "w").close()
        if age_days:
            t = time.time() - age_days * 86400
            os.utime(path, (t, t))
        return path

    def test_removes_only_old_files(self):
        old = self._touch("old.png", age_days=100)
        new = self._touch("new.png", age_days=0)
        removed = utils.cleanup_old_files(self.dir, retention_days=30)
        self.assertEqual(removed, 1)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(new))

    def test_zero_retention_is_noop(self):
        self._touch("old.png", age_days=100)
        self.assertEqual(utils.cleanup_old_files(self.dir, retention_days=0), 0)

    def test_missing_dir_returns_zero(self):
        self.assertEqual(utils.cleanup_old_files("/no/such/dir", 30), 0)


class AddCustomFiltersQueryTests(unittest.TestCase):
    def test_applies_each_filter(self):
        query = mock.Mock()
        query.filter.return_value = query
        utils.add_custom_filters_query(mock.Mock(), query, {"a": 1, "b": 2})
        self.assertEqual(query.filter.call_count, 2)

    def test_empty_filters_returns_query_unchanged(self):
        query = mock.Mock()
        self.assertIs(utils.add_custom_filters_query(mock.Mock(), query, None), query)
        query.filter.assert_not_called()


class MadridTimeTests(unittest.TestCase):
    def test_now_madrid_is_timezone_aware(self):
        self.assertIsNotNone(utils.now_madrid().tzinfo)

    def test_today_madrid_returns_date(self):
        self.assertIsInstance(utils.today_madrid(), date)


class FetchExamsToReviewTests(unittest.TestCase):
    def test_serializes_exam_rows(self):
        exam = mock.Mock(id=1, persona_id=2, tipo_examen="B",
                         fecha_examen=date(2022, 11, 2))
        exam.persona.nif = "12345678Z"
        exam.persona.fecha_nacimiento = date(2004, 8, 18)
        db = mock.Mock()
        db.get_examenes_a_revisar.return_value = [exam]
        self.assertEqual(utils.fetch_exams_to_review(db), [{
            "exam_id": 1,
            "persona_id": 2,
            "nif": "12345678Z",
            "exam_date_str": "02/11/2022",
            "type": "B",
            "birthdate_str": "18/08/2004",
        }])

    def test_empty_when_no_exams(self):
        db = mock.Mock()
        db.get_examenes_a_revisar.return_value = []
        self.assertEqual(utils.fetch_exams_to_review(db), [])


if __name__ == "__main__":
    unittest.main()
