from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _

from ..extensions import db
from ..models import Car, CarService, ConsumptionEntry, Debt, ExpenseCategory, ShopServicePayment
from ..utils import parse_date, validate_entry_date

bp = Blueprint("consumption", __name__)


def _locked_source_message(entry):
    """None if entry is a plain, freely editable/deletable ConsumptionEntry.
    Otherwise a Swahili message explaining where it actually needs to be
    changed -- it's a 1:1 mirror of a Debt/CarService/ShopServicePayment (see
    those models' consumption_entry_id), so editing or deleting it here would
    desync it from the record that owns it."""
    if Debt.query.filter_by(consumption_entry_id=entry.id).first():
        return _("Taarifa hii inatokana na deni -- ibadilishe au ifute kutoka ukurasa wa Madeni.")
    if CarService.query.filter_by(consumption_entry_id=entry.id).first():
        return _("Taarifa hii inatokana na tiketi ya huduma -- ibadilishe au ifute kutoka ukurasa wa Huduma.")
    if ShopServicePayment.query.filter_by(consumption_entry_id=entry.id).first():
        return _("Taarifa hii inatokana na malipo ya huduma -- ibadilishe au ifute kutoka ukurasa wa Huduma.")
    return None


@bp.route("/")
def list_view():
    start = parse_date(request.args.get("start"))
    end = parse_date(request.args.get("end"))
    car_id = request.args.get("car_id", type=int)
    category_id = request.args.get("category_id", type=int)

    q = ConsumptionEntry.query
    if start:
        q = q.filter(ConsumptionEntry.date >= start)
    if end:
        q = q.filter(ConsumptionEntry.date <= end)
    if car_id:
        q = q.filter(ConsumptionEntry.car_id == car_id)
    if category_id:
        q = q.filter(ConsumptionEntry.category_id == category_id)
    entries = q.order_by(ConsumptionEntry.date.desc(), ConsumptionEntry.id.desc()).all()

    return render_template(
        "consumption/list.html",
        entries=entries,
        cars=Car.query.order_by(Car.code).all(),
        categories=ExpenseCategory.query.order_by(ExpenseCategory.name).all(),
        start=request.args.get("start", ""),
        end=request.args.get("end", ""),
        car_id=car_id,
        category_id=category_id,
    )


@bp.route("/new", methods=["GET", "POST"])
def new():
    cars = Car.query.filter_by(active=True).order_by(Car.code).all()
    categories = ExpenseCategory.query.filter_by(active=True).order_by(ExpenseCategory.name).all()

    if request.method == "POST":
        entry_date = parse_date(request.form.get("date"), date.today())
        error = validate_entry_date(entry_date)
        if error:
            flash(error, "danger")
            return render_template("consumption/form.html", cars=cars, categories=categories, entry=None)

        entry = ConsumptionEntry(
            date=entry_date,
            car_id=int(request.form["car_id"]),
            category_id=int(request.form["category_id"]),
            amount=float(request.form["amount"]),
            description=(request.form.get("description") or "").strip() or None,
        )
        db.session.add(entry)
        db.session.commit()
        flash(_("Taarifa ya matumizi imehifadhiwa."), "success")
        return redirect(url_for("consumption.list_view"))

    return render_template("consumption/form.html", cars=cars, categories=categories, entry=None)


@bp.route("/<int:entry_id>/edit", methods=["GET", "POST"])
def edit(entry_id):
    entry = ConsumptionEntry.query.get_or_404(entry_id)
    cars = Car.query.filter_by(active=True).order_by(Car.code).all()
    categories = ExpenseCategory.query.filter_by(active=True).order_by(ExpenseCategory.name).all()

    locked_message = _locked_source_message(entry)
    if locked_message:
        flash(locked_message, "danger")
        return redirect(url_for("consumption.list_view"))

    if request.method == "POST":
        new_date = parse_date(request.form.get("date"), entry.date)
        error = validate_entry_date(new_date)
        if error:
            flash(error, "danger")
            return render_template("consumption/form.html", cars=cars, categories=categories, entry=entry)

        entry.date = new_date
        entry.car_id = int(request.form["car_id"])
        entry.category_id = int(request.form["category_id"])
        entry.amount = float(request.form["amount"])
        entry.description = (request.form.get("description") or "").strip() or None
        db.session.commit()
        flash(_("Taarifa ya matumizi imesasishwa."), "success")
        return redirect(url_for("consumption.list_view"))

    return render_template("consumption/form.html", cars=cars, categories=categories, entry=entry)


@bp.route("/<int:entry_id>/delete", methods=["POST"])
def delete(entry_id):
    entry = ConsumptionEntry.query.get_or_404(entry_id)

    locked_message = _locked_source_message(entry)
    if locked_message:
        flash(locked_message, "danger")
        return redirect(url_for("consumption.list_view"))

    db.session.delete(entry)
    db.session.commit()
    flash(_("Taarifa ya matumizi imefutwa."), "info")
    return redirect(url_for("consumption.list_view"))
