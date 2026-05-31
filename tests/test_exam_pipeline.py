"""Characterization tests for the pure domain logic in exam_pipeline.

This module has no I/O (it only imports the enums), so it runs without selenium /
telegram / sqlalchemy installed. Run from the repo root with app/ on the path:

    python3 -m unittest discover -s tests -v

These tests pin the CURRENT behaviour before the restructuring refactor is reapplied,
so they double as a safety net: after popping the refactor (where exam_pipeline moves to
domain/exam_pipeline.py) the same assertions must still hold — only the import line below
changes to `from domain.exam_pipeline import ...`.
"""
import _support  # noqa: F401  (installs sys.path + dep stubs; must be first)

import unittest

from domain.exam_pipeline import (
    parse_tipo_prueba,
    pipeline_for,
    prerequisites_for,
    infer_implied_passes,
    is_carnet_complete,
)
from domain.enums.carnet_enum import CarnetEnum as C
from domain.enums.prueba_enum import PruebaEnum as P


class ParseTipoPruebaTests(unittest.TestCase):
    def test_known_labels(self):
        self.assertEqual(parse_tipo_prueba("TEORICO COMUN"), P.TEORICO_COMUN)
        self.assertEqual(parse_tipo_prueba("ESPECIFICO"), P.TEORICO_ESPECIFICO)
        self.assertEqual(parse_tipo_prueba("DESTREZA EN CIRCUITO CERRADO"), P.CIRCUITO)
        self.assertEqual(parse_tipo_prueba("CIRCULACION"), P.CIRCULACION)

    def test_normalises_accents_case_and_whitespace(self):
        # _norm strips accents, upper-cases and collapses inner whitespace
        self.assertEqual(parse_tipo_prueba("  Teórico   Común "), P.TEORICO_COMUN)
        self.assertEqual(parse_tipo_prueba("circulación"), P.CIRCULACION)

    def test_unknown_label_raises(self):
        with self.assertRaises(ValueError):
            parse_tipo_prueba("MANIOBRA INVENTADA")

    def test_non_string_raises(self):
        with self.assertRaises(ValueError):
            parse_tipo_prueba(None)


class PipelineForTests(unittest.TestCase):
    def test_b_pipeline_is_theory_then_road(self):
        self.assertEqual(pipeline_for(C.B), [P.TEORICO_COMUN, P.CIRCULACION])

    def test_carnet_without_pipeline_returns_none(self):
        self.assertIsNone(pipeline_for(C.B96))


class PrerequisitesForTests(unittest.TestCase):
    def test_transitive_closure_motorcycle(self):
        # A requires A2 which requires A1
        self.assertEqual(set(prerequisites_for(C.A)), {C.A2, C.A1})

    def test_transitive_closure_trailer(self):
        # C+E requires C which requires B
        self.assertEqual(set(prerequisites_for(C.EC)), {C.C, C.B})

    def test_no_prerequisites(self):
        self.assertEqual(prerequisites_for(C.B), [])
        self.assertEqual(prerequisites_for(C.AM), [])


class InferImpliedPassesTests(unittest.TestCase):
    def test_empty_input_yields_nothing(self):
        self.assertEqual(infer_implied_passes(set()), set())

    def test_earlier_in_pipeline_is_implied(self):
        # passing the later CIRCULACION of B implies the earlier TEORICO_COMUN of B
        implied = infer_implied_passes({(C.B, P.CIRCULACION)})
        self.assertIn((C.B, P.TEORICO_COMUN), implied)

    def test_prerequisite_carnet_becomes_fully_implied(self):
        # any real pass of A2 implies the whole A1 prerequisite pipeline
        implied = infer_implied_passes({(C.A2, P.CIRCULACION)})
        for prueba in pipeline_for(C.A1):
            self.assertIn((C.A1, prueba), implied)

    def test_does_not_mutate_input(self):
        aprobadas = {(C.B, P.CIRCULACION)}
        infer_implied_passes(aprobadas)
        self.assertEqual(aprobadas, {(C.B, P.CIRCULACION)})


class IsCarnetCompleteTests(unittest.TestCase):
    def test_complete_with_real_passes(self):
        aprobadas = {(C.B, P.TEORICO_COMUN), (C.B, P.CIRCULACION)}
        self.assertTrue(is_carnet_complete(C.B, aprobadas))

    def test_incomplete_when_comun_missing_everywhere(self):
        self.assertFalse(is_carnet_complete(C.B, {(C.B, P.CIRCULACION)}))

    def test_teorico_comun_is_global(self):
        # TEORICO_COMUN passed under A1 satisfies B's theory slot
        aprobadas = {(C.B, P.CIRCULACION), (C.A1, P.TEORICO_COMUN)}
        self.assertTrue(is_carnet_complete(C.B, aprobadas))

    def test_carnet_without_pipeline_is_never_complete(self):
        self.assertFalse(is_carnet_complete(C.B96, set()))


if __name__ == "__main__":
    unittest.main()
