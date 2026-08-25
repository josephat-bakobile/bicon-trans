from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _

from ..extensions import db
from ..models import Car, CarDocument, DocumentType
from ..renewals import compute_expire_date, renewal_predictions
from ..utils import parse_date

bp = Blueprint("renewals", __name__)


def _validate_start_date(d):
    if d is None:
        return _("Tarehe ya kuanza si sahihi.")
    if d > date.today():
        return _(
            "Tarehe ya kuanza haiwezi kuwa baadaye ya leo (%(today)s).",
            today=date.today().strftime("%d-%m-%Y"),
        )
    return None


@bp.route("/")
def index():
    car_id = request.args.get("car_id", type=int)

    predictions = renewal_predictions()

    q = CarDocument.query
    if car_id:
        q = q.filter(CarDocument.car_id == car_id)
    history = q.order_by(CarDocument.start_date.desc(), CarDocument.id.desc()).limit(30).all()

    return render_template(
        "renewals/index.html",
        predictions=predictions,
        history=history,
        cars=Car.query.order_by(Car.code).all(),
        document_types=DocumentType.query.filter_by(active=True).order_by(DocumentType.name).all(),
        car_id=car_id,
    )


@bp.route("/new", methods=["POST"])
def new():
    start_date = parse_date(request.form.get("start_date"), date.today())
    error = _validate_start_date(start_date)
    car_id = request.form.get("car_id", type=int)
    document_type_id = request.form.get("document_type_id", type=int)
    note = (request.form.get("note") or "").strip() or None

    if error:
        flash(error, "danger")
    elif not car_id or not document_type_id:
        flash(_("Chagua gari na aina ya nyaraka."), "danger")
    else:
        db.session.add(
            CarDocument(
                car_id=car_id,
                document_type_id=document_type_id,
                start_date=start_date,
                expire_date=compute_expire_date(start_date),
                note=note,
            )
        )
        db.session.commit()
        flash(_("Upya wa nyaraka umehifadhiwa."), "success")

    return redirect(url_for("renewals.index"))


@bp.route("/<int:document_id>/delete", methods=["POST"])
def delete(document_id):
    document = CarDocument.query.get_or_404(document_id)
    db.session.delete(document)
    db.session.commit()
    flash(_("Rekodi ya nyaraka imefutwa."), "info")
    return redirect(url_for("renewals.index"))


@bp.route("/types/new", methods=["POST"])
def new_type():
    name = (request.form.get("name") or "").strip().upper()
    if not name:
        flash(_("Jina la aina ya nyaraka linahitajika."), "danger")
    elif DocumentType.query.filter_by(name=name).first():
        flash(_("Aina %(name)s tayari ipo.", name=name), "danger")
    else:
        db.session.add(DocumentType(name=name))
        db.session.commit()
        flash(_("Aina %(name)s imeongezwa.", name=name), "success")
    return redirect(url_for("renewals.index"))


@bp.route("/types/<int:type_id>/toggle", methods=["POST"])
def toggle_type(type_id):
    doc_type = DocumentType.query.get_or_404(type_id)
    doc_type.active = not doc_type.active
    db.session.commit()
    return redirect(url_for("renewals.index"))
