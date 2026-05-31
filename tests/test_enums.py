"""Tests for the enum parsing/validation helpers."""
import _support  # noqa: F401  (installs sys.path + dep stubs; must be first)

import unittest

from enums.carnet_enum import CarnetEnum
from enums.resultado_enum import ResultadoEnum
from enums.status_enum import StatusEnum, STATUS_DB_NAMES


class CarnetEnumTests(unittest.TestCase):
    def test_is_valid(self):
        self.assertTrue(CarnetEnum.is_valid("B"))
        self.assertTrue(CarnetEnum.is_valid("EB"))
        self.assertFalse(CarnetEnum.is_valid("ZZ"))
        self.assertFalse(CarnetEnum.is_valid("b"))  # case-sensitive on purpose

    def test_from_dgt_known(self):
        self.assertEqual(CarnetEnum.from_dgt("B"), CarnetEnum.B)

    def test_from_dgt_unknown_raises(self):
        with self.assertRaises(ValueError):
            CarnetEnum.from_dgt("ZZ")


class ResultadoEnumTests(unittest.TestCase):
    def test_apto_and_no_apto(self):
        self.assertEqual(ResultadoEnum.from_dgt("APTO"), ResultadoEnum.APTO)
        self.assertEqual(ResultadoEnum.from_dgt("NO APTO"), ResultadoEnum.NO_APTO)

    def test_normalises_case_and_whitespace(self):
        self.assertEqual(ResultadoEnum.from_dgt("  apto  "), ResultadoEnum.APTO)
        self.assertEqual(ResultadoEnum.from_dgt("no   apto"), ResultadoEnum.NO_APTO)

    def test_unknown_raises(self):
        with self.assertRaises(ValueError):
            ResultadoEnum.from_dgt("QUIZAS")


class StatusDbNamesTests(unittest.TestCase):
    def test_covers_every_status_in_enum_order(self):
        self.assertEqual(len(STATUS_DB_NAMES), len(list(StatusEnum)))
        # APPEND-ONLY contract: row position lines up with the enum's auto-increment value
        for expected_value, (member, _name) in enumerate(STATUS_DB_NAMES, start=1):
            self.assertEqual(member.value, expected_value)


if __name__ == "__main__":
    unittest.main()
