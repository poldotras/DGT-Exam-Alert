"""Panel view helpers that reuse the bot's domain logic."""
from domain.enums.carnet_enum import CarnetEnum
from domain.enums.prueba_enum import PruebaEnum
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
