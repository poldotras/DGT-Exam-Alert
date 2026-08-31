"""Panel view helpers that reuse the bot's domain logic."""
from domain.enums.carnet_enum import CarnetEnum
from domain.enums.prueba_enum import PruebaEnum
from domain.enums.status_enum import StatusEnum
from domain.exam_pipeline import CARNET_PIPELINES, is_carnet_complete


def carnets_obtenidos(db, persona_id):
    """Return the list of CarnetEnum a persona has fully completed, per recorded pruebas.

    Inferred passes are already persisted as APTO by the bot, so the recorded 'aprobadas'
    set is enough — no need to re-infer here. Mirrors the bot's _reconcile_completed_carnets.
    """
    aprobadas = {
        (CarnetEnum(c), PruebaEnum(p))
        for (c, p) in db.get_pruebas_aprobadas(persona_id)
    }
    return [carnet for carnet in CARNET_PIPELINES if is_carnet_complete(carnet, aprobadas)]


# Badge CSS class per exam status, so the panel colours «Pendiente», «Suspendido», etc.
# differently instead of showing every state in the same grey pill.
STATUS_BADGE_CLASSES = {
    StatusEnum.PENDING: "badge-pending",
    StatusEnum.REVIEWING: "badge-reviewing",
    StatusEnum.REVIEWED_EXPIRED: "badge-expired",
    StatusEnum.APPROVED: "badge-ok",
    StatusEnum.FAILED: "badge-no",
    StatusEnum.CANCELLED: "badge-cancelled",
}


def estado_badge_class(estado_id):
    """CSS modifier for an exam state id. Unknown ids fall back to the neutral badge."""
    try:
        return STATUS_BADGE_CLASSES[StatusEnum(estado_id)]
    except ValueError:
        return ""


def rango_fechas(desde, hasta):
    """Label for a grouped row: «02/02/2026», or «02/02/2026 → 09/02/2026» for a range."""
    if desde is None:
        return "—"
    if hasta is None or hasta == desde:
        return desde.strftime("%d/%m/%Y")
    return f"{desde.strftime('%d/%m/%Y')} → {hasta.strftime('%d/%m/%Y')}"


def _agrupar_consecutivos(filas, clave, fecha):
    """Collapse rows into runs of consecutive days.

    A run is a maximal list of rows that share `clave(fila)` and whose `fecha(fila)` are
    consecutive calendar days (a repeated date doesn't break the run). Rows without a date
    are never grouped: each one is its own run. Returns the runs ordered by their first
    date (dateless ones last), so a long day-by-day listing collapses into a few rows.
    """
    grupos = {}
    sueltas = []
    for fila in filas:
        if fecha(fila) is None:
            sueltas.append([fila])
        else:
            grupos.setdefault(clave(fila), []).append(fila)

    runs = []
    for mismas in grupos.values():
        mismas.sort(key=fecha)
        run = [mismas[0]]
        for fila in mismas[1:]:
            if (fecha(fila) - fecha(run[-1])).days <= 1:
                run.append(fila)
            else:
                runs.append(run)
                run = [fila]
        runs.append(run)

    runs.sort(key=lambda run: (fecha(run[0]), fecha(run[-1])))
    return runs + sueltas


class Rango:
    """One row of a listing: a run of consecutive dates shown as «desde → hasta».

    Reads like the first row it groups (`tipo_examen`, `estado`, `persona`… are proxied),
    so the templates can keep using the same field names, plus the range itself.
    """

    def __init__(self, filas, fecha):
        self.filas = filas
        self.desde = fecha(filas[0])
        self.hasta = fecha(filas[-1])

    def __getattr__(self, name):  # proxy the shared fields to the first row
        return getattr(self.filas[0], name)

    @property
    def ids(self):
        return [fila.id for fila in self.filas]

    @property
    def dias(self):
        """Number of days covered, 1 for a single-date row."""
        if self.desde is None:
            return 1
        return (self.hasta - self.desde).days + 1


def agrupar_examenes(examenes, por_persona=False):
    """Group exams into date ranges sharing carnet + state (and persona on the home board).

    A person watching «B» from 02/02 to 09/02 shows one row 02/02 → 09/02 while every day
    is pending; as the bot advances some days the run splits into one row per state.
    """
    def clave(e):
        return (e.persona_id if por_persona else None, e.tipo_examen, e.estado_id)

    def fecha(e):
        return e.fecha_examen

    return [Rango(run, fecha) for run in _agrupar_consecutivos(examenes, clave, fecha)]


def agrupar_pruebas(pruebas):
    """Same grouping for the prueba history: same carnet, prueba and resultado on
    consecutive days become a single row. Inferred pruebas (fecha NULL) stay one per row.
    """
    def clave(p):
        return (p.carnet, p.prueba, p.resultado)

    def fecha(p):
        return p.fecha

    return [Rango(run, fecha) for run in _agrupar_consecutivos(pruebas, clave, fecha)]
