from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import Car, ConsumptionEntry, ExpenseCategory
from ..security import require_action_code
from ..utils import parse_date

bp = Blueprint("consumption", __name__)


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
@require_action_code
def new():
    cars = Car.query.filter_by(active=True).order_by(Car.code).all()
    categories = ExpenseCategory.query.filter_by(active=True).order_by(ExpenseCategory.name).all()

    if request.method == "POST":
        entry = ConsumptionEntry(
            date=parse_date(request.form.get("date"), date.today()),
            car_id=int(request.form["car_id"]),
            category_id=int(request.form["category_id"]),
            amount=float(request.form["amount"]),
            description=(request.form.get("description") or "").strip() or None,
        )
        db.session.add(entry)
        db.session.commit()
        flash("Taarifa ya matumizi imehifadhiwa.", "success")
        return redirect(url_for("consumption.list_view"))

    return render_template("consumption/form.html", cars=cars, categories=categories, entry=None)


@bp.route("/<int:entry_id>/edit", methods=["GET", "POST"])
@require_action_code
def edit(entry_id):
    entry = ConsumptionEntry.query.get_or_404(entry_id)
    cars = Car.query.filter_by(active=True).order_by(Car.code).all()
    categories = ExpenseCategory.query.filter_by(active=True).order_by(ExpenseCategory.name).all()

    if request.method == "POST":
        entry.date = parse_date(request.form.get("date"), entry.date)
        entry.car_id = int(request.form["car_id"])
        entry.category_id = int(request.form["category_id"])
        entry.amount = float(request.form["amount"])
        entry.description = (request.form.get("description") or "").strip() or None
        db.session.commit()
        flash("Taarifa ya matumizi imesasishwa.", "success")
        return redirect(url_for("consumption.list_view"))

    return render_template("consumption/form.html", cars=cars, categories=categories, entry=entry)


@bp.route("/<int:entry_id>/delete", methods=["POST"])
@require_action_code
def delete(entry_id):
    entry = ConsumptionEntry.query.get_or_404(entry_id)
    db.session.delete(entry)
    db.session.commit()
    flash("Taarifa ya matumizi imefutwa.", "info")
    return redirect(url_for("consumption.list_view"))
