"""Tests for the personas.json schema validation (currently living in main.py).

Imports main, which only works because _support stubs selenium/telegram/sqlalchemy/etc.
The validators themselves are pure (datetime + regex), so no mocks are needed here.
"""
import _support  # noqa: F401  (installs sys.path + dep stubs; must be first)

import unittest
from datetime import date
from unittest import mock

from services import personas_loader as main


class CheckNifTests(unittest.TestCase):
    def test_valid_nif(self):
        self.assertIsNone(main._check_nif("12345678Z"))

    def test_valid_nie(self):
        self.assertIsNone(main._check_nif("X1234567L"))

    def test_lowercase_is_normalised(self):
        self.assertIsNone(main._check_nif("  x1234567l  "))

    def test_too_short_is_rejected(self):
        self.assertIsNotNone(main._check_nif("1234567Z"))

    def test_non_string_is_rejected(self):
        self.assertIsNotNone(main._check_nif(12345678))


class CheckDateStrTests(unittest.TestCase):
    def setUp(self):
        self.check = main._check_date_str("fecha")

    def test_valid_date(self):
        self.assertIsNone(self.check("02/11/2022"))

    def test_wrong_format(self):
        self.assertIsNotNone(self.check("2022-11-02"))

    def test_not_a_string(self):
        self.assertIsNotNone(self.check(20221102))


class CheckExamDateFieldTests(unittest.TestCase):
    def test_single_string(self):
        self.assertIsNone(main._check_exam_date_field("02/11/2022"))

    def test_list_of_dates(self):
        self.assertIsNone(main._check_exam_date_field(["01/01/2020", "02/01/2020"]))

    def test_range_dict(self):
        self.assertIsNone(main._check_exam_date_field({"start": "01/01/2020", "end": "03/01/2020"}))

    def test_range_start_after_end_is_rejected(self):
        self.assertIsNotNone(main._check_exam_date_field({"start": "03/01/2020", "end": "01/01/2020"}))

    def test_range_missing_key_is_rejected(self):
        self.assertIsNotNone(main._check_exam_date_field({"start": "01/01/2020"}))

    def test_bad_type_is_rejected(self):
        self.assertIsNotNone(main._check_exam_date_field(123))


class DatesFromFieldTests(unittest.TestCase):
    def test_single_string(self):
        self.assertEqual(main._dates_from_field("02/11/2022"), [date(2022, 11, 2)])

    def test_list(self):
        self.assertEqual(
            main._dates_from_field(["01/01/2020", "03/01/2020"]),
            [date(2020, 1, 1), date(2020, 1, 3)],
        )

    def test_range_is_inclusive(self):
        result = main._dates_from_field({"start": "01/01/2020", "end": "03/01/2020"})
        self.assertEqual(result, [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3)])


class ValidatePersonEntryTests(unittest.TestCase):
    def setUp(self):
        self.logger = mock.Mock()
        self.valid = {
            "nif": "12345678Z",
            "nombre": "Ada",
            "carnet": "B",
            "fecha_nacimiento": "18/08/2004",
            "fecha_examen": "02/11/2022",
        }

    def test_valid_entry(self):
        self.assertTrue(main._validate_person_entry(self.valid, 0, self.logger))

    def test_missing_key_is_skipped(self):
        entry = {k: v for k, v in self.valid.items() if k != "carnet"}
        self.assertFalse(main._validate_person_entry(entry, 0, self.logger))
        self.logger.error.assert_called()

    def test_unknown_carnet_is_skipped(self):
        entry = dict(self.valid, carnet="ZZ")
        self.assertFalse(main._validate_person_entry(entry, 0, self.logger))

    def test_bad_nif_is_skipped(self):
        entry = dict(self.valid, nif="nope")
        self.assertFalse(main._validate_person_entry(entry, 0, self.logger))

    def test_non_dict_is_skipped(self):
        self.assertFalse(main._validate_person_entry(["not", "a", "dict"], 0, self.logger))


if __name__ == "__main__":
    unittest.main()
