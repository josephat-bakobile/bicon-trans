from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _

from ..extensions import db
from ..models import Car, Debt, DebtPayment
from ..utils import DEBT_COLLECTION_EXTRA, car_debt_balance, debt_balances, parse_date, validate_entry_date

bp = Blueprint("debts", __name__)


@bp.route("/")
def index():
    balances = debt_balances()
    debts = Debt.query.order_by(Debt.date.desc(), Debt.id.desc()).limit(20).all()
    payments = DebtPayment.query.order_by(DebtPayment.date.desc(), DebtPayment.id.desc()).limit(20).all()
    cars = Car.query.filter_by(active=True).order_by(Car.code).all()
    return render_template(
        "debts/index.html",
        balances=balances,
        debts=debts,
        payments=payments,
        cars=cars,
        debt_collection_extra=DEBT_COLLECTION_EXTRA,
    )


@bp.route("/new", methods=["POST"])
def new_debt():
    debt_date = parse_date(request.form.get("date"), date.today())
    error = validate_entry_date(debt_date)
    if error:
        flash(error, "danger")
        return redirect(url_for("debts.index"))

    return_type = request.form.get("return_type") or "collection"
    if return_type not in Debt.RETURN_TYPES:
        return_type = "collection"
    start_date = parse_date(request.form.get("start_date"), debt_date)

    db.session.add(
        Debt(
            date=debt_date,
            car_id=int(request.form["car_id"]),
            amount=float(request.form["amount"]),
            description=(request.form.get("description") or "").strip() or None,
            return_type=return_type,
            start_date=start_date,
        )
    )
    db.session.commit()
    flash(_("Deni limehifadhiwa."), "success")
    return redirect(url_for("debts.index"))


@bp.route("/<int:debt_id>/delete", methods=["POST"])
def delete_debt(debt_id):
    d = Debt.query.get_or_404(debt_id)
    db.session.delete(d)
    db.session.commit()
    flash(_("Deni limefutwa."), "info")
    return redirect(url_for("debts.index"))


@bp.route("/payments/new", methods=["POST"])
def new_payment():
    car_id = int(request.form["car_id"])
    amount = float(request.form["amount"])
    car = Car.query.get_or_404(car_id)
    balance = car_debt_balance(car_id)

    if amount > balance:
        flash(
            _(
                "Kiasi %(amount)s ni kikubwa kuliko deni la %(code)s lililobaki (%(balance)s). "
                "Hakuna kilichohifadhiwa.",
                amount=f"{amount:,.0f}",
                code=car.code,
                balance=f"{balance:,.0f}",
            ),
            "danger",
        )
        return redirect(url_for("debts.index"))

    payment_date = parse_date(request.form.get("date"), date.today())
    error = validate_entry_date(payment_date)
    if error:
        flash(error, "danger")
        return redirect(url_for("debts.index"))

    db.session.add(
        DebtPayment(
            date=payment_date,
            car_id=car_id,
            amount=amount,
            description=(request.form.get("description") or "").strip() or None,
        )
    )
    db.session.commit()
    flash(_("Malipo ya deni yamehifadhiwa."), "success")
    return redirect(url_for("debts.index"))


@bp.route("/payments/<int:payment_id>/delete", methods=["POST"])
def delete_payment(payment_id):
    p = DebtPayment.query.get_or_404(payment_id)
    db.session.delete(p)
    db.session.commit()
    flash(_("Malipo yamefutwa."), "info")
    return redirect(url_for("debts.index"))
