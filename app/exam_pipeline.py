"""Domain model for DGT exam components (pruebas) and per-licence pipelines / prerequisite
chains, plus the pure logic to infer implied passes.

Pruebas, carnets and results are modelled as enums (PruebaEnum, CarnetEnum, ResultadoEnum).
Parsing functions RAISE on any text we don't contemplate, so an unexpected DGT label fails
loud (surfaced in Sentry) instead of being silently mis-registered.

`PruebaEnum.TEORICO_COMUN` is GLOBAL: a single shared theory across all carnets. One APTO
anywhere satisfies the theory slot of every carnet (común == teórico-del-B).

NOTE: pipelines/prerequisites are a pragmatic, simplified encoding of the DGT rules and are
trivial to edit. They do not model every conditional exemption.
"""

import unicodedata

from enums.prueba_enum import PruebaEnum
from enums.carnet_enum import CarnetEnum

# Only this prueba is shared across carnets (passing it once counts everywhere).
GLOBAL_PRUEBAS = {PruebaEnum.TEORICO_COMUN}


def _norm(text: str) -> str:
    """Accent-strip, upper-case and collapse whitespace for robust label matching."""
    stripped = "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )
    return " ".join(stripped.upper().split())


# --- DGT "TIPO DE PRUEBA" page label -> PruebaEnum ---
# Keys are normalised via _norm(). ✅ = seen in real DGT pages; others are best-guess.
_TIPO_DE_PRUEBA_MAP = {
    "TEORICO COMUN": PruebaEnum.TEORICO_COMUN,                  # ✅
    "CONTROL DE CONOCIMIENTOS": PruebaEnum.TEORICO_COMUN,       # guess (older label)
    "ESPECIFICO": PruebaEnum.TEORICO_ESPECIFICO,               # ✅ (A1 and C)
    "TEORICO ESPECIFICO": PruebaEnum.TEORICO_ESPECIFICO,       # guess
    "CONTROL DE CONOCIMIENTOS ESPECIFICOS": PruebaEnum.TEORICO_ESPECIFICO,  # guess
    "DESTREZA EN CIRCUITO CERRADO": PruebaEnum.CIRCUITO,        # ✅ (C)
    "MANIOBRAS": PruebaEnum.CIRCUITO,                          # guess (motos/AM)
    "CIRCUITO CERRADO": PruebaEnum.CIRCUITO,                   # guess
    "CIRCULACION": PruebaEnum.CIRCULACION,                     # ✅ (B practical, moto/truck on-road)
    "CIRCULACION EN VIAS ABIERTAS AL TRAFICO": PruebaEnum.CIRCULACION,  # guess
}


def parse_tipo_prueba(raw):
    """Map a DGT 'TIPO DE PRUEBA' label to a PruebaEnum. Raises ValueError if unknown."""
    if isinstance(raw, str):
        member = _TIPO_DE_PRUEBA_MAP.get(_norm(raw))
        if member is not None:
            return member
    raise ValueError(f"Unrecognised DGT tipo de prueba: {raw!r}")


# --- Pipelines: ordered required pruebas per carnet (theory first, then practical) ---
# Keyed by CarnetEnum. `TEORICO_COMUN` is global so listing it just means "theory required".
# Carnets NOT listed here (B96, LCC, M.P. ADR certs, RPV, …) are still valid for polling —
# they just don't drive completion/cancellation logic.
_C, _P = CarnetEnum, PruebaEnum
CARNET_PIPELINES = {
    _C.AM:  [_P.TEORICO_COMUN, _P.TEORICO_ESPECIFICO, _P.CIRCUITO],
    _C.AML: [_P.TEORICO_COMUN, _P.TEORICO_ESPECIFICO, _P.CIRCUITO],
    _C.A1:  [_P.TEORICO_COMUN, _P.TEORICO_ESPECIFICO, _P.CIRCUITO, _P.CIRCULACION],
    _C.A2:  [_P.TEORICO_COMUN, _P.TEORICO_ESPECIFICO, _P.CIRCUITO, _P.CIRCULACION],
    _C.A:   [_P.TEORICO_COMUN, _P.TEORICO_ESPECIFICO, _P.CIRCUITO, _P.CIRCULACION],
    _C.B:   [_P.TEORICO_COMUN, _P.CIRCULACION],
    _C.EB:  [_P.CIRCULACION],
    _C.C1:  [_P.TEORICO_COMUN, _P.TEORICO_ESPECIFICO, _P.CIRCUITO, _P.CIRCULACION],
    _C.C:   [_P.TEORICO_COMUN, _P.TEORICO_ESPECIFICO, _P.CIRCUITO, _P.CIRCULACION],
    _C.EC1: [_P.CIRCUITO, _P.CIRCULACION],
    _C.EC:  [_P.CIRCUITO, _P.CIRCULACION],
    _C.D1:  [_P.TEORICO_COMUN, _P.TEORICO_ESPECIFICO, _P.CIRCUITO, _P.CIRCULACION],
    _C.D:   [_P.TEORICO_COMUN, _P.TEORICO_ESPECIFICO, _P.CIRCUITO, _P.CIRCULACION],
    _C.ED1: [_P.CIRCUITO, _P.CIRCULACION],
    _C.ED:  [_P.CIRCUITO, _P.CIRCULACION],
}

# --- Direct prerequisite carnets (transitive closure computed below) ---
_CARNET_PREREQS_DIRECT = {
    _C.AM: [], _C.AML: [], _C.A1: [], _C.A2: [_C.A1], _C.A: [_C.A2],
    _C.B: [], _C.EB: [_C.B],
    _C.C1: [_C.B], _C.C: [_C.B], _C.EC1: [_C.C1], _C.EC: [_C.C],
    _C.D1: [_C.B], _C.D: [_C.B], _C.ED1: [_C.D1], _C.ED: [_C.D],
}


def pipeline_for(carnet):
    """Return the ordered list of required PruebaEnum for a carnet, or None if it has none."""
    return CARNET_PIPELINES.get(carnet)


def prerequisites_for(carnet):
    """Transitive closure of prerequisite carnets (e.g. A -> [A2, A1])."""
    result, stack = [], list(_CARNET_PREREQS_DIRECT.get(carnet, []))
    while stack:
        p = stack.pop()
        if p not in result:
            result.append(p)
            stack.extend(_CARNET_PREREQS_DIRECT.get(p, []))
    return result


# ---------------------------------------------------------------------------
# Pure inference logic. Inputs/outputs are sets of (CarnetEnum, PruebaEnum) so this
# is fully unit-testable without a DB or browser.
# ---------------------------------------------------------------------------

def _comun_passed(aprobadas):
    """True if TEORICO_COMUN is APTO under ANY carnet (it is global)."""
    return any(prueba == PruebaEnum.TEORICO_COMUN for (_carnet, prueba) in aprobadas)


def infer_implied_passes(aprobadas):
    """Given the set of really-passed (CarnetEnum, PruebaEnum) tuples, return the set of
    ADDITIONAL (CarnetEnum, PruebaEnum) that are logically implied APTO:

      - earlier-in-pipeline passes (passed a later prueba ⟹ earlier ones passed)
      - prerequisite carnets fully complete (any pass of X ⟹ prereqs complete)

    Pure function: does not mutate `aprobadas`.
    """
    aprobadas = set(aprobadas)
    implied = set()
    comun_ok = _comun_passed(aprobadas)

    carnets_touched = {carnet for (carnet, _prueba) in aprobadas}

    for carnet in carnets_touched:
        pipeline = CARNET_PIPELINES.get(carnet)
        if not pipeline:
            continue

        # 1) earlier-in-pipeline: highest index among this carnet's passes
        passed_idx = [
            pipeline.index(prueba)
            for (c, prueba) in aprobadas
            if c == carnet and prueba in pipeline
        ]
        if comun_ok and PruebaEnum.TEORICO_COMUN in pipeline:
            passed_idx.append(pipeline.index(PruebaEnum.TEORICO_COMUN))
        if passed_idx:
            max_idx = max(passed_idx)
            for earlier in pipeline[:max_idx]:
                entry = (carnet, earlier)
                if entry not in aprobadas:
                    implied.add(entry)

        # 2) prerequisite carnets fully complete
        for prereq in prerequisites_for(carnet):
            for prueba in CARNET_PIPELINES.get(prereq, []):
                entry = (prereq, prueba)
                if entry not in aprobadas:
                    implied.add(entry)

    return implied


def is_carnet_complete(carnet, aprobadas):
    """True if every prueba in the carnet pipeline is APTO (real or inferred).
    `aprobadas` is a set of (CarnetEnum, PruebaEnum). TEORICO_COMUN is satisfied globally.
    """
    pipeline = pipeline_for(carnet)
    if not pipeline:
        return False
    comun_ok = _comun_passed(aprobadas)
    for prueba in pipeline:
        if prueba == PruebaEnum.TEORICO_COMUN:
            if not comun_ok:
                return False
        elif (carnet, prueba) not in aprobadas:
            return False
    return True
