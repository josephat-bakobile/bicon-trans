from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import Car, Driver

bp = Blueprint("cars", __name__)


def _assignable_driver_options(cars):
    """(car, options) pairs -- options being the drivers each car's dropdown
    should offer: every unassigned active driver, plus the car's own current
    driver (so it stays selected even though it's technically "taken")."""
    unassigned = Driver.query.filter_by(active=True, car=None).order_by(Driver.name).all()
    rows = []
    for car in cars:
        options = list(unassigned)
        if car.driver and car.driver not in options:
            options.append(car.driver)
        options.sort(key=lambda d: d.name)
        rows.append((car, options))
    return rows


def _assign_driver(car, driver_id):
    """None on success, else a Swahili error message. Enforces one driver -> at
    most one car by refusing to steal a driver who's already assigned elsewhere."""
    if not driver_id:
        car.driver_id = None
        return None
    driver = Driver.query.get(driver_id)
    if driver is None:
        return "Dereva huyo hayupo."
    if driver.car is not None and driver.car.id != car.id:
        return f"Dereva {driver.name} tayari anaendesha gari {driver.car.code}."
    car.driver_id = driver.id
    return None


@bp.route("/")
def list_view():
    cars = Car.query.order_by(Car.code).all()
    unassigned_drivers = Driver.query.filter_by(active=True, car=None).order_by(Driver.name).all()
    return render_template(
        "cars/list.html",
        car_rows=_assignable_driver_options(cars),
        unassigned_drivers=unassigned_drivers,
    )


@bp.route("/new", methods=["POST"])
def new():
    code = (request.form.get("code") or "").strip().upper()
    name = (request.form.get("name") or "").strip() or None
    driver_id = request.form.get("driver_id", type=int)
    daily_target = float(request.form.get("daily_target") or 0)
    if not code:
        flash("Namba ya gari (code) inahitajika.", "danger")
    elif Car.query.filter_by(code=code).first():
        flash(f"Gari {code} tayari lipo.", "danger")
    else:
        car = Car(code=code, name=name, daily_target=daily_target)
        error = _assign_driver(car, driver_id)
        if error:
            flash(error, "danger")
        else:
            db.session.add(car)
            db.session.commit()
            flash(f"Gari {code} limeongezwa.", "success")
    return redirect(url_for("cars.list_view"))


@bp.route("/<int:car_id>/toggle", methods=["POST"])
def toggle(car_id):
    car = Car.query.get_or_404(car_id)
    car.active = not car.active
    db.session.commit()
    return redirect(url_for("cars.list_view"))


@bp.route("/<int:car_id>/target", methods=["POST"])
def update_target(car_id):
    car = Car.query.get_or_404(car_id)
    car.daily_target = float(request.form.get("daily_target") or 0)
    db.session.commit()
    flash(f"Kiasi cha lengo la siku la {car.code} kimesasishwa.", "success")
    return redirect(url_for("cars.list_view"))


@bp.route("/<int:car_id>/driver", methods=["POST"])
def update_driver(car_id):
    car = Car.query.get_or_404(car_id)
    driver_id = request.form.get("driver_id", type=int)
    error = _assign_driver(car, driver_id)
    if error:
        flash(error, "danger")
    else:
        db.session.commit()
        flash(f"Dereva wa {car.code} amesasishwa.", "success")
    return redirect(url_for("cars.list_view"))
