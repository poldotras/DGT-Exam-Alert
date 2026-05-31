"""Tests for the reusable input validators in services/validation.py (used by the panel)."""
import _support  # noqa: F401  (installs sys.path + dep stubs; must be first)

import unittest
from datetime import date

from services import validation


class CheckNifTests(unittest.TestCase):
    def test_valid_nif(self):
        self.assertIsNone(validation.check_nif("12345678Z"))

    def test_valid_nie(self):
        self.assertIsNone(validation.check_nif("X1234567L"))

    def test_lowercase_is_normalised(self):
        self.assertIsNone(validation.check_nif("  x1234567l  "))

    def test_too_short_is_rejected(self):
        self.assertIsNotNone(validation.check_nif("1234567Z"))

    def test_non_string_is_rejected(self):
        self.assertIsNotNone(validation.check_nif(12345678))


class CheckDateStrTests(unittest.TestCase):
    def setUp(self):
        self.check = validation.check_date_str("fecha")

    def test_valid_date(self):
        self.assertIsNone(self.check("02/11/2022"))

    def test_wrong_format(self):
        self.assertIsNotNone(self.check("2022-11-02"))

    def test_not_a_string(self):
        self.assertIsNotNone(self.check(20221102))


class CheckExamDateFieldTests(unittest.TestCase):
    def test_single_string(self):
        self.assertIsNone(validation.check_exam_date_field("02/11/2022"))

    def test_list_of_dates(self):
        self.assertIsNone(validation.check_exam_date_field(["01/01/2020", "02/01/2020"]))

    def test_range_dict(self):
        self.assertIsNone(validation.check_exam_date_field({"start": "01/01/2020", "end": "03/01/2020"}))

    def test_range_start_after_end_is_rejected(self):
        self.assertIsNotNone(validation.check_exam_date_field({"start": "03/01/2020", "end": "01/01/2020"}))

    def test_range_missing_key_is_rejected(self):
        self.assertIsNotNone(validation.check_exam_date_field({"start": "01/01/2020"}))

    def test_bad_type_is_rejected(self):
        self.assertIsNotNone(validation.check_exam_date_field(123))


class DatesFromFieldTests(unittest.TestCase):
    def test_single_string(self):
        self.assertEqual(validation.dates_from_field("02/11/2022"), [date(2022, 11, 2)])

    def test_list(self):
        self.assertEqual(
            validation.dates_from_field(["01/01/2020", "03/01/2020"]),
            [date(2020, 1, 1), date(2020, 1, 3)],
        )

    def test_range_is_inclusive(self):
        result = validation.dates_from_field({"start": "01/01/2020", "end": "03/01/2020"})
        self.assertEqual(result, [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3)])


if __name__ == "__main__":
    unittest.main()
