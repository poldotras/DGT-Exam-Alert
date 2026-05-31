"""Tests for the seeding helpers in main.py (seed_statuses, seed_people) with a mock DB."""
import _support  # noqa: F401  (installs sys.path + dep stubs; must be first)

import json
import os
import tempfile
import unittest
from unittest import mock

from services import bootstrap, personas_loader
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


class SeedPeopleTests(unittest.TestCase):
    def _write_json(self, payload):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh)
        self.addCleanup(os.remove, path)
        return path

    def _db_for_new_person(self):
        db = mock.Mock()
        db.get_persona_by_nif.return_value = None  # person doesn't exist yet
        db.create_persona.return_value = mock.Mock(id=10, nombre="Ada")
        db.get_examenes_by_persona_id.return_value = []  # no existing exams
        return db

    def test_valid_entry_creates_person_and_exam(self):
        path = self._write_json([{
            "nif": "12345678Z", "nombre": "Ada", "carnet": "B",
            "fecha_nacimiento": "18/08/2004", "fecha_examen": "02/11/2022",
        }])
        db = self._db_for_new_person()
        personas_loader.seed_people(db, mock.Mock(), json_path=path)
        db.create_persona.assert_called_once()
        db.create_examen.assert_called_once()

    def test_invalid_entry_is_skipped(self):
        path = self._write_json([{
            "nif": "12345678Z", "nombre": "Ada", "carnet": "ZZ",  # invalid carnet
            "fecha_nacimiento": "18/08/2004", "fecha_examen": "02/11/2022",
        }])
        db = self._db_for_new_person()
        personas_loader.seed_people(db, mock.Mock(), json_path=path)
        db.create_persona.assert_not_called()
        db.create_examen.assert_not_called()

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            personas_loader.seed_people(mock.Mock(), mock.Mock(), json_path="/no/such/file.json")


if __name__ == "__main__":
    unittest.main()
