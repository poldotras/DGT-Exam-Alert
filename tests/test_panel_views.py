"""Tests for the panel's domain helper carnets_obtenidos (pure logic, no Flask, no DB).
Runs on the host: web.views only imports the domain enums + exam_pipeline."""
import _support  # noqa: F401  (installs sys.path + dep stubs; must be first)

import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock

from web.views import (
    STATUS_BADGE_CLASSES, agrupar_examenes, agrupar_pruebas, carnets_obtenidos,
    estado_badge_class, rango_fechas,
)
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


def _examen(dia, estado_id=1, tipo="B", persona_id=1, mes=2):
    return SimpleNamespace(
        id=dia, persona_id=persona_id, tipo_examen=tipo, estado_id=estado_id,
        fecha_examen=date(2026, mes, dia), estado=SimpleNamespace(nombre=f"E{estado_id}"))


class AgruparExamenesTests(unittest.TestCase):
    def test_consecutive_days_in_the_same_state_collapse_into_one_row(self):
        grupos = agrupar_examenes([_examen(d) for d in range(2, 10)])
        self.assertEqual(len(grupos), 1)
        self.assertEqual((grupos[0].desde, grupos[0].hasta), (date(2026, 2, 2), date(2026, 2, 9)))
        self.assertEqual(grupos[0].dias, 8)

    def test_state_change_splits_the_range(self):
        # 2-4 revisado/caducado, 5 revisando, 6-9 pendiente -> 3 rows instead of 8
        examenes = (
            [_examen(d, estado_id=3) for d in (2, 3, 4)]
            + [_examen(5, estado_id=2)]
            + [_examen(d, estado_id=1) for d in (6, 7, 8, 9)]
        )
        grupos = agrupar_examenes(examenes)
        self.assertEqual(
            [(g.desde.day, g.hasta.day, g.estado_id) for g in grupos],
            [(2, 4, 3), (5, 5, 2), (6, 9, 1)],
        )

    def test_gap_in_the_dates_splits_the_range(self):
        grupos = agrupar_examenes([_examen(d) for d in (2, 3, 7, 8)])
        self.assertEqual([(g.desde.day, g.hasta.day) for g in grupos], [(2, 3), (7, 8)])

    def test_different_carnets_never_share_a_row(self):
        grupos = agrupar_examenes([_examen(2, tipo="B"), _examen(3, tipo="A1")])
        self.assertEqual(len(grupos), 2)

    def test_different_personas_never_share_a_row_on_the_home_board(self):
        examenes = [_examen(2, persona_id=1), _examen(3, persona_id=2)]
        self.assertEqual(len(agrupar_examenes(examenes, por_persona=True)), 2)

    def test_row_keeps_every_id_of_the_range_so_cancelling_covers_it(self):
        grupos = agrupar_examenes([_examen(d) for d in (2, 3, 4)])
        self.assertEqual(grupos[0].ids, [2, 3, 4])

    def test_row_proxies_the_shared_fields_of_its_exams(self):
        grupo = agrupar_examenes([_examen(d, estado_id=5, tipo="A2") for d in (2, 3)])[0]
        self.assertEqual((grupo.tipo_examen, grupo.estado_id, grupo.estado.nombre), ("A2", 5, "E5"))

    def test_rows_come_out_in_chronological_order(self):
        examenes = [_examen(9, estado_id=1), _examen(2, estado_id=3), _examen(3, estado_id=3)]
        grupos = agrupar_examenes(examenes)
        self.assertEqual([g.desde.day for g in grupos], [2, 9])

    def test_month_boundary_is_still_consecutive(self):
        grupos = agrupar_examenes([_examen(28, mes=2), _examen(1, mes=3)])
        self.assertEqual(len(grupos), 1)

    def test_empty_listing(self):
        self.assertEqual(agrupar_examenes([]), [])


class AgruparPruebasTests(unittest.TestCase):
    def _prueba(self, dia, resultado="APTO", prueba="circulacion"):
        return SimpleNamespace(
            id=dia, carnet="B", prueba=prueba, resultado=resultado,
            fecha=date(2026, 2, dia) if dia else None)

    def test_same_result_on_consecutive_days_collapses(self):
        grupos = agrupar_pruebas([self._prueba(d, "NO APTO") for d in (2, 3, 4)])
        self.assertEqual(len(grupos), 1)
        self.assertEqual(len(grupos[0].filas), 3)

    def test_different_results_stay_apart(self):
        grupos = agrupar_pruebas([self._prueba(2, "NO APTO"), self._prueba(3, "APTO")])
        self.assertEqual(len(grupos), 2)

    def test_inferred_pruebas_without_date_are_never_grouped(self):
        grupos = agrupar_pruebas([self._prueba(0), self._prueba(0)])
        self.assertEqual(len(grupos), 2)
        self.assertIsNone(grupos[0].desde)

    def test_dateless_pruebas_go_last(self):
        grupos = agrupar_pruebas([self._prueba(0), self._prueba(2)])
        self.assertEqual([g.desde for g in grupos], [date(2026, 2, 2), None])


class RangoFechasTests(unittest.TestCase):
    def test_single_day(self):
        self.assertEqual(rango_fechas(date(2026, 2, 2), date(2026, 2, 2)), "02/02/2026")

    def test_range(self):
        self.assertEqual(
            rango_fechas(date(2026, 2, 2), date(2026, 2, 9)), "02/02/2026 → 09/02/2026")

    def test_no_date(self):
        self.assertEqual(rango_fechas(None, None), "—")


if __name__ == "__main__":
    unittest.main()
