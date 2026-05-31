"""Blueprint: home (personas + exams under review) plus create/detail of personas."""
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, current_app, abort,
)

from domain.enums.carnet_enum import CarnetEnum
from domain.enums.status_enum import StatusEnum
from services.validation import check_nif, check_date_str
from web.views import carnets_obtenidos

bp = Blueprint("personas", __name__)

# exam states still cancellable (the bot is actively watching them)
ESTADOS_ACTIVOS = {StatusEnum.PENDING.value, StatusEnum.REVIEWING.value}


@bp.route("/")
def home():
    db = current_app.config["DB"]
    return render_template(
        "home.html",
        examenes=db.get_examenes_activos(),
        personas=db.get_all_personas(),
    )


@bp.route("/personas/new")
def new_persona():
    return render_template("personas_new.html", form=None)


@bp.route("/personas", methods=["POST"])
def create_persona():
    db = current_app.config["DB"]
    nif = (request.form.get("nif") or "").strip().upper()
    nombre = (request.form.get("nombre") or "").strip()
    fecha_nacimiento = (request.form.get("fecha_nacimiento") or "").strip()

    # reuse the shared validators (NIF/NIE pattern + dd/mm/yyyy)
    errors = [e for e in (
        check_nif(nif),
        None if nombre else "nombre: vacío",
        check_date_str("fecha_nacimiento")(fecha_nacimiento),
    ) if e]
    if not errors and db.get_persona_by_nif(nif):
        errors.append(f"Ya existe una persona con NIF {nif}")

    if errors:
        for e in errors:
            flash(e, "error")
        return render_template("personas_new.html", form=request.form), 400

    persona = db.create_persona(
        nif=nif,
        nombre=nombre,
        fecha_nacimiento=datetime.strptime(fecha_nacimiento, "%d/%m/%Y").date(),
    )
    flash(f"Persona «{nombre}» creada.", "ok")
    return redirect(url_for("personas.detail_persona", persona_id=persona.id))


@bp.route("/personas/<int:persona_id>")
def detail_persona(persona_id):
    db = current_app.config["DB"]
    persona = db.get_persona_by_id(persona_id)
    if persona is None:
        abort(404)
    return render_template(
        "persona_detail.html",
        persona=persona,
        examenes=db.get_examenes_con_estado(persona_id),
        pruebas=db.get_all_pruebas_de_persona(persona_id),
        carnets_obtenidos=carnets_obtenidos(db, persona_id),
        carnets=list(CarnetEnum),
        estados_activos=ESTADOS_ACTIVOS,
    )
