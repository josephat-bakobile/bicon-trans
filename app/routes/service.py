from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..car_service import predict_for_car, service_predictions
from ..extensions import db
from ..models import Car, CarService, ConsumptionEntry, ExpenseCategory, ShortfallClearance
from ..security import get_current_user, require_permission
from ..sms import can_send, send_and_log
from ..utils import parse_date

bp = Blueprint("service", __name__)


def _validate_service_date(d):
    """Service dates (unlike collections/consumption) may legitimately be far in
    the past -- backfilling a car's baseline/last-known service date -- so this
    only rejects missing values and future dates, not old ones."""
    if d is None:
        return "Tarehe ya huduma si sahihi."
    if d > date.today():
        return f"Tarehe ya huduma haiwezi kuwa baadaye ya leo ({date.today().strftime('%d-%m-%Y')})."
    return None


def _apply_cost(service, car_id, cost, category_id, service_date, description):
    """Keep the linked ConsumptionEntry (if any) in sync with the service form's
    cost field: create/update/remove it so it always mirrors the service entry."""
    if cost > 0:
        if service.consumption_entry_id:
            entry = service.consumption_entry
            entry.date = service_date
            entry.car_id = car_id
            entry.category_id = category_id
            entry.amount = cost
            entry.description = description or "Huduma ya gari"
        else:
            entry = ConsumptionEntry(
                date=service_date,
                car_id=car_id,
                category_id=category_id,
                amount=cost,
                description=description or "Huduma ya gari",
            )
            db.session.add(entry)
            db.session.flush()
            service.consumption_entry_id = entry.id
    elif service.consumption_entry_id:
        entry = service.consumption_entry
        service.consumption_entry_id = None
        db.session.flush()
        db.session.delete(entry)


def _sync_service_clearance(service, car, service_date):
    """Keeps the linked ShortfallClearance in sync with the service's car/date --
    a car doesn't collect on the day it's serviced, so that day is auto-explained
    the same way a driver-allowance day is (see driver_allowance.give_allowance)."""
    note = (
        f"Gari {car.code} lilikuwa kwenye huduma tarehe {service_date.strftime('%d-%m-%Y')}"
        f"{' (' + service.description + ')' if service.description else ''} "
        "- halikutegemewa kukusanya siku hiyo."
    )

    if service.shortfall_clearance_id:
        clearance = service.shortfall_clearance
        if clearance.car_id != car.id or clearance.date != service_date:
            clash = ShortfallClearance.query.filter(
                ShortfallClearance.car_id == car.id,
                ShortfallClearance.date == service_date,
                ShortfallClearance.id != clearance.id,
            ).first()
            if clash:
                service.shortfall_clearance_id = None
                db.session.flush()
                db.session.delete(clearance)
                clearance = clash
                service.shortfall_clearance_id = clearance.id
            else:
                clearance.car_id = car.id
                clearance.date = service_date
        clearance.description = note
        return

    existing = ShortfallClearance.query.filter_by(car_id=car.id, date=service_date).first()
    if existing:
        existing.description = note
        clearance = existing
    else:
        clearance = ShortfallClearance(car_id=car.id, date=service_date, description=note)
        db.session.add(clearance)
        db.session.flush()
    service.shortfall_clearance_id = clearance.id


@bp.route("/")
def index():
    car_id = request.args.get("car_id", type=int)

    predictions = service_predictions()

    q = CarService.query
    if car_id:
        q = q.filter(CarService.car_id == car_id)
    history = q.order_by(CarService.service_date.desc(), CarService.id.desc()).limit(30).all()

    return render_template(
        "service/index.html",
        predictions=predictions,
        history=history,
        cars=Car.query.order_by(Car.code).all(),
        categories=ExpenseCategory.query.filter_by(active=True).order_by(ExpenseCategory.name).all(),
        car_id=car_id,
    )


@bp.route("/new", methods=["POST"])
def new():
    service_date = parse_date(request.form.get("service_date"), date.today())
    error = _validate_service_date(service_date)
    car_id = int(request.form["car_id"])
    description = (request.form.get("description") or "").strip() or None
    cost = float(request.form.get("cost") or 0)
    category_id = request.form.get("category_id", type=int)

    if error:
        flash(error, "danger")
    elif cost > 0 and not category_id:
        flash("Chagua aina ya matumizi kwa gharama ya huduma.", "danger")
    else:
        car = Car.query.get_or_404(car_id)
        service = CarService(car_id=car_id, service_date=service_date, description=description)
        db.session.add(service)
        db.session.flush()
        _apply_cost(service, car_id, cost, category_id, service_date, description)
        _sync_service_clearance(service, car, service_date)
        db.session.commit()
        flash("Huduma ya gari imehifadhiwa.", "success")

    return redirect(url_for("service.index"))


@bp.route("/<int:service_id>/edit", methods=["GET", "POST"])
def edit(service_id):
    service = CarService.query.get_or_404(service_id)
    cars = Car.query.order_by(Car.code).all()
    categories = ExpenseCategory.query.filter_by(active=True).order_by(ExpenseCategory.name).all()

    if request.method == "POST":
        service_date = parse_date(request.form.get("service_date"), service.service_date)
        error = _validate_service_date(service_date)
        car_id = int(request.form["car_id"])
        description = (request.form.get("description") or "").strip() or None
        cost = float(request.form.get("cost") or 0)
        category_id = request.form.get("category_id", type=int)

        if error:
            flash(error, "danger")
            return render_template("service/edit.html", service=service, cars=cars, categories=categories)
        if cost > 0 and not category_id:
            flash("Chagua aina ya matumizi kwa gharama ya huduma.", "danger")
            return render_template("service/edit.html", service=service, cars=cars, categories=categories)

        car = Car.query.get_or_404(car_id)
        service.service_date = service_date
        service.car_id = car_id
        service.description = description
        _apply_cost(service, car_id, cost, category_id, service_date, description)
        _sync_service_clearance(service, car, service_date)
        db.session.commit()
        flash("Huduma ya gari imesasishwa.", "success")
        return redirect(url_for("service.index"))

    return render_template("service/edit.html", service=service, cars=cars, categories=categories)


@bp.route("/<int:service_id>/delete", methods=["POST"])
def delete(service_id):
    service = CarService.query.get_or_404(service_id)
    linked = service.consumption_entry
    clearance = service.shortfall_clearance
    db.session.delete(service)
    if linked:
        db.session.delete(linked)
    if clearance:
        db.session.delete(clearance)
    db.session.commit()
    flash("Huduma ya gari imefutwa.", "info")
    return redirect(url_for("service.index"))


@bp.route("/car/<int:car_id>/interval", methods=["POST"])
def update_interval(car_id):
    car = Car.query.get_or_404(car_id)
    car.service_interval_days = int(request.form.get("service_interval_days") or 20)
    db.session.commit()
    flash(f"Muda wa huduma wa {car.code} umesasishwa.", "success")
    return redirect(url_for("service.index"))


@bp.route("/car/<int:car_id>/sms", methods=["POST"])
@require_permission("sms")
def send_service_sms(car_id):
    car = Car.query.get_or_404(car_id)
    prediction = predict_for_car(car)
    next_url = request.form.get("next") or url_for("service.index")

    if prediction["status"] not in ("overdue", "due_soon"):
        flash(f"Gari {car.code} halihitaji huduma kwa sasa.", "danger")
        return redirect(next_url)

    ok, reason = can_send(car)
    if not ok:
        flash(reason, "danger")
        return redirect(next_url)

    if prediction["status"] == "overdue":
        timing = f"lilipaswa kufanyiwa huduma tarehe {prediction['due_date'].strftime('%d-%m-%Y')} (limechelewa)"
    else:
        timing = f"linahitaji huduma tarehe {prediction['due_date'].strftime('%d-%m-%Y')} (siku {prediction['days_remaining']} zijazo)"
    message = (
        f"Habari {car.driver.name}, gari {car.code} {timing}. "
        f"Tafadhali panga huduma haraka. - BICON TRANS"
    )
    sent, error = send_and_log(car, "service", message, get_current_user())
    if sent:
        flash(f"SMS ya huduma imetumwa kwa dereva wa {car.code}.", "success")
    else:
        flash(error, "danger")
    return redirect(next_url)
