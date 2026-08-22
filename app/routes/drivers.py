from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import Car, Driver

bp = Blueprint("drivers", __name__)


@bp.route("/")
def list_view():
    drivers = Driver.query.order_by(Driver.name).all()
    unassigned_cars = Car.query.filter_by(driver_id=None, active=True).order_by(Car.code).all()
    return render_template("drivers/list.html", drivers=drivers, unassigned_cars=unassigned_cars)


def _assign_car(driver, car_id):
    """None on success, else a Swahili error message."""
    new_car = Car.query.get(car_id) if car_id else None
    if car_id and new_car is None:
        return "Gari hilo halipo."
    if new_car is not None and new_car.driver_id is not None and new_car.driver_id != driver.id:
        return f"Gari {new_car.code} tayari lina dereva mwingine."

    if driver.car is not None and (new_car is None or driver.car.id != new_car.id):
        driver.car.driver_id = None
    if new_car is not None:
        new_car.driver_id = driver.id
    return None


@bp.route("/new", methods=["POST"])
def new():
    name = (request.form.get("name") or "").strip()
    phone = (request.form.get("phone") or "").strip() or None
    car_id = request.form.get("car_id", type=int)

    if not name:
        flash("Jina la dereva linahitajika.", "danger")
        return redirect(url_for("drivers.list_view"))

    if car_id:
        car = Car.query.get(car_id)
        if car is None:
            flash("Gari hilo halipo.", "danger")
            return redirect(url_for("drivers.list_view"))
        if car.driver_id is not None:
            flash(f"Gari {car.code} tayari lina dereva mwingine.", "danger")
            return redirect(url_for("drivers.list_view"))

    driver = Driver(name=name, phone=phone)
    db.session.add(driver)
    db.session.flush()
    if car_id:
        Car.query.get(car_id).driver_id = driver.id
    db.session.commit()
    flash(f"Dereva {name} ameongezwa.", "success")
    return redirect(url_for("drivers.list_view"))


@bp.route("/<int:driver_id>/edit", methods=["POST"])
def edit(driver_id):
    driver = Driver.query.get_or_404(driver_id)
    name = (request.form.get("name") or "").strip()
    phone = (request.form.get("phone") or "").strip() or None
    car_id = request.form.get("car_id", type=int)

    if not name:
        flash("Jina la dereva linahitajika.", "danger")
        return redirect(url_for("drivers.list_view"))

    error = _assign_car(driver, car_id)
    if error:
        flash(error, "danger")
        return redirect(url_for("drivers.list_view"))

    driver.name = name
    driver.phone = phone
    db.session.commit()
    flash(f"Dereva {driver.name} amesasishwa.", "success")
    return redirect(url_for("drivers.list_view"))


@bp.route("/<int:driver_id>/toggle", methods=["POST"])
def toggle(driver_id):
    driver = Driver.query.get_or_404(driver_id)
    driver.active = not driver.active
    if not driver.active and driver.car is not None:
        driver.car.driver_id = None
    db.session.commit()
    return redirect(url_for("drivers.list_view"))


@bp.route("/<int:driver_id>/sms-toggle", methods=["POST"])
def toggle_sms(driver_id):
    driver = Driver.query.get_or_404(driver_id)
    driver.sms_enabled = not driver.sms_enabled
    db.session.commit()
    return redirect(url_for("drivers.list_view"))
