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
