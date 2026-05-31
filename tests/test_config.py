"""Tests for the environment-variable parsing helpers in config.py."""
import _support  # noqa: F401  (installs sys.path + dep stubs; must be first)

import os
import unittest
from unittest import mock

from config import _env_int, _env_bool, _env_str


class EnvIntTests(unittest.TestCase):
    def test_reads_value(self):
        with mock.patch.dict(os.environ, {"X_INT": "10"}):
            self.assertEqual(_env_int("X_INT", 5), 10)

    def test_default_when_unset(self):
        os.environ.pop("X_MISSING", None)
        self.assertEqual(_env_int("X_MISSING", 5), 5)

    def test_default_when_empty(self):
        with mock.patch.dict(os.environ, {"X_EMPTY": ""}):
            self.assertEqual(_env_int("X_EMPTY", 7), 7)


class EnvBoolTests(unittest.TestCase):
    def test_truthy_words(self):
        for v in ("1", "true", "TRUE", "yes", "on"):
            with mock.patch.dict(os.environ, {"X_B": v}):
                self.assertTrue(_env_bool("X_B"), v)

    def test_falsy_words(self):
        for v in ("0", "false", "no", "off"):
            with mock.patch.dict(os.environ, {"X_B": v}):
                self.assertFalse(_env_bool("X_B"), v)

    def test_default_when_unset(self):
        os.environ.pop("X_B_MISSING", None)
        self.assertTrue(_env_bool("X_B_MISSING", True))
        self.assertFalse(_env_bool("X_B_MISSING", False))


class EnvStrTests(unittest.TestCase):
    def test_reads_value(self):
        with mock.patch.dict(os.environ, {"X_S": "hello"}):
            self.assertEqual(_env_str("X_S", "def"), "hello")

    def test_default_when_unset(self):
        os.environ.pop("X_S_MISSING", None)
        self.assertEqual(_env_str("X_S_MISSING", "def"), "def")


if __name__ == "__main__":
    unittest.main()
