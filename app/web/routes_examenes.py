"""Blueprint: add one or more exams (a carnet to review) to a persona, and cancel an
exam's review.

Adding accepts a single date or a start..end range, reusing the shared validators in
services/validation.py (check_exam_date_field / dates_from_field). Cancelling takes the
ids of a whole grouped date range, since that is what a listing row shows.
"""
from flask import (
    Blueprint, request, redirect, url_for, flash, current_app, abort,
)

from domain.enums.carnet_enum import CarnetEnum
from services.validation import check_exam_date_field, dates_from_field

bp = Blueprint("examenes", __name__)


@bp.route("/personas/<int:persona_id>/examenes", methods=["POST"])
def create_examen(persona_id):
    db = current_app.config["DB"]
    if db.get_persona_by_id(persona_id) is None:
        abort(404)

    carnet = (request.form.get("carnet") or "").strip()
    desde = (request.form.get("fecha_examen") or "").strip()
    hasta = (request.form.get("fecha_fin") or "").strip()

    # one date, or a {start, end} range when "hasta" is filled
    date_field = {"start": desde, "end": hasta} if hasta else desde

    errors = []
    if not CarnetEnum.is_valid(carnet):
        errors.append(f"Carnet inválido: {carnet!r}")
    date_err = check_exam_date_field(date_field)
    if date_err:
        errors.append(date_err)

    if errors:
        for e in errors:
            flash(e, "error")
        return redirect(url_for("personas.detail_persona", persona_id=persona_id))

    # dedupe against the carnet's existing exam dates
    existing = {
        e.fecha_examen
        for e in db.get_examenes_by_persona_id(persona_id, {"tipo_examen": carnet})
    }
    nuevas = [f for f in dates_from_field(date_field) if f not in existing]
    for fecha in nuevas:
        db.create_examen(persona_id=persona_id, fecha_examen=fecha, tipo_examen=carnet)

    if nuevas:
        flash(f"{len(nuevas)} examen(es) de {carnet} añadido(s) a revisar.", "ok")
    else:
        flash("No se añadió nada: esas fechas ya estaban registradas.", "error")
    return redirect(url_for("personas.detail_persona", persona_id=persona_id))


@bp.route("/examenes/cancelar", methods=["POST"])
def cancelar_examenes():
    """Cancel the reviews posted as `examen_id` (set them to CANCELLED). A listing row is a
    date range, so it sends every id in the range. Returns to the previous page.
    """
    db = current_app.config["DB"]
    try:
        ids = [int(v) for v in request.form.getlist("examen_id")]
    except ValueError:
        abort(400)
    if not ids:
        abort(400)

    canceladas = db.cancelar_examenes(ids)
    flash(f"{canceladas} revisión(es) cancelada(s).", "ok")
    return redirect(request.referrer or url_for("personas.home"))
