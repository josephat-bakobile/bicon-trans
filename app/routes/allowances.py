from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _

from ..driver_allowance import allowance_predictions, give_allowance, predict_for_car, reverse_allowance
from ..models import Car, DriverAllowance

bp = Blueprint("allowances", __name__)


@bp.route("/")
def index():
    predictions = allowance_predictions()
    history = (
        DriverAllowance.query.order_by(DriverAllowance.date.desc(), DriverAllowance.id.desc()).limit(30).all()
    )
    return render_template("allowances/index.html", predictions=predictions, history=history)


@bp.route("/confirm", methods=["POST"])
def confirm():
    car_id = request.form.get("car_id", type=int)
    period_year = request.form.get("period_year", type=int)
    period_month = request.form.get("period_month", type=int)
    period_type = request.form.get("period_type")
    car = Car.query.get_or_404(car_id)

    prediction = predict_for_car(car)
    matches = (
        prediction["period_year"] == period_year
        and prediction["period_month"] == period_month
        and prediction["period_type"] == period_type
    )
    if not matches:
        flash(_("Utabiri wa posho ya %(code)s umebadilika, tafadhali onyesha upya ukurasa.", code=car.code), "danger")
        return redirect(url_for("allowances.index"))
    if prediction["status"] not in ("due", "overdue"):
        flash(_("Siku ya posho ya %(code)s bado haijafika.", code=car.code), "danger")
        return redirect(url_for("allowances.index"))

    give_allowance(car, period_year, period_month, period_type, date.today())
    flash(_("Posho ya dereva wa %(code)s imehifadhiwa.", code=car.code), "success")
    return redirect(url_for("allowances.index"))


@bp.route("/<int:allowance_id>/delete", methods=["POST"])
def delete(allowance_id):
    allowance = DriverAllowance.query.get_or_404(allowance_id)
    car_code = allowance.car.code
    reverse_allowance(allowance)
    flash(_("Posho ya %(code)s imefutwa.", code=car_code), "info")
    return redirect(url_for("allowances.index"))
