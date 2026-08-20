from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import Car
from ..security import require_action_code

bp = Blueprint("cars", __name__)


@bp.route("/")
def list_view():
    cars = Car.query.order_by(Car.code).all()
    return render_template("cars/list.html", cars=cars)


@bp.route("/new", methods=["POST"])
@require_action_code
def new():
    code = (request.form.get("code") or "").strip().upper()
    name = (request.form.get("name") or "").strip() or None
    if not code:
        flash("Namba ya gari (code) inahitajika.", "danger")
    elif Car.query.filter_by(code=code).first():
        flash(f"Gari {code} tayari lipo.", "danger")
    else:
        db.session.add(Car(code=code, name=name))
        db.session.commit()
        flash(f"Gari {code} limeongezwa.", "success")
    return redirect(url_for("cars.list_view"))


@bp.route("/<int:car_id>/toggle", methods=["POST"])
@require_action_code
def toggle(car_id):
    car = Car.query.get_or_404(car_id)
    car.active = not car.active
    db.session.commit()
    return redirect(url_for("cars.list_view"))
