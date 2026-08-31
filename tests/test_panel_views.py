"""Tests for the panel's domain helper carnets_obtenidos (pure logic, no Flask, no DB).
Runs on the host: web.views only imports the domain enums + exam_pipeline."""
import _support  # noqa: F401  (installs sys.path + dep stubs; must be first)

import unittest
from unittest import mock

from web.views import STATUS_BADGE_CLASSES, carnets_obtenidos, estado_badge_class
from domain.enums.carnet_enum import CarnetEnum as C
from domain.enums.status_enum import StatusEnum


def _db(aprobadas):
    db = mock.Mock()
    db.get_pruebas_aprobadas.return_value = aprobadas
    return db


class CarnetsObtenidosTests(unittest.TestCase):
    def test_empty_when_nothing_passed(self):
        self.assertEqual(carnets_obtenidos(_db(set()), 1), [])

    def test_b_complete(self):
        # B pipeline = teorico_comun + circulacion
        obtained = carnets_obtenidos(_db({("B", "teorico_comun"), ("B", "circulacion")}), 1)
        self.assertIn(C.B, obtained)

    def test_b_incomplete_when_comun_missing(self):
        self.assertNotIn(C.B, carnets_obtenidos(_db({("B", "circulacion")}), 1))

    def test_teorico_comun_is_global(self):
        # común passed under A1 satisfies B's theory slot
        obtained = carnets_obtenidos(_db({("B", "circulacion"), ("A1", "teorico_comun")}), 1)
        self.assertIn(C.B, obtained)

    def test_returns_carnet_enums(self):
        obtained = carnets_obtenidos(_db({("B", "teorico_comun"), ("B", "circulacion")}), 1)
        self.assertTrue(obtained and all(isinstance(c, C) for c in obtained))


class EstadoBadgeClassTests(unittest.TestCase):
    def test_every_status_has_a_class(self):
        self.assertEqual(set(STATUS_BADGE_CLASSES), set(StatusEnum))

    def test_classes_are_distinct_per_status(self):
        # the whole point: each state must be visually distinguishable
        self.assertEqual(len(set(STATUS_BADGE_CLASSES.values())), len(StatusEnum))

    def test_maps_state_id_to_its_class(self):
        self.assertEqual(estado_badge_class(StatusEnum.FAILED.value), "badge-no")
        self.assertEqual(estado_badge_class(StatusEnum.PENDING.value), "badge-pending")

    def test_unknown_state_id_falls_back_to_neutral_badge(self):
        self.assertEqual(estado_badge_class(999), "")


if __name__ == "__main__":
    unittest.main()
