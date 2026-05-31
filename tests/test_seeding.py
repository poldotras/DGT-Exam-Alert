"""Tests for the status seeding helper in services/bootstrap.py (with a mock DB).

(personas/exams are managed via the web panel now — there is no personas.json seeder.)
"""
import _support  # noqa: F401  (installs sys.path + dep stubs; must be first)

import unittest
from unittest import mock

from services import bootstrap
from domain.enums.status_enum import STATUS_DB_NAMES


class SeedStatusesTests(unittest.TestCase):
    def test_creates_all_missing_statuses(self):
        db = mock.Mock()
        db.get_estados.return_value = []  # none exist yet
        bootstrap.seed_statuses(db, mock.Mock())
        self.assertEqual(db.create_estado.call_count, len(STATUS_DB_NAMES))

    def test_is_idempotent_when_all_present(self):
        db = mock.Mock()
        db.get_estados.return_value = [mock.Mock(nombre=name) for _, name in STATUS_DB_NAMES]
        bootstrap.seed_statuses(db, mock.Mock())
        db.create_estado.assert_not_called()


if __name__ == "__main__":
    unittest.main()
