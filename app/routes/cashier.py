from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _

from ..extensions import db
from ..models import CashierCollectionBatch, CashierCollectionEntry, Car
from ..security import get_current_user
from ..utils import parse_date, validate_entry_date

bp = Blueprint("cashier", __name__)


def _current_open_batch():
    """The cashier's own batch still being built for today, creating one on first
    use. A cashier may have already closed today's batch and started a new one
    later the same day -- always the most recent 'open' one, if any."""
    user = get_current_user()
    return (
        CashierCollectionBatch.query.filter_by(created_by_id=user.id, batch_date=date.today(), status="open")
        .order_by(CashierCollectionBatch.id.desc())
        .first()
    )


@bp.route("/")
def index():
    user = get_current_user()
    batch = _current_open_batch()
    cars = Car.query.filter_by(active=True).order_by(Car.code).all()
    history = (
        CashierCollectionBatch.query.filter_by(created_by_id=user.id)
        .order_by(CashierCollectionBatch.batch_date.desc(), CashierCollectionBatch.id.desc())
        .limit(15)
        .all()
    )
    return render_template("cashier/index.html", batch=batch, cars=cars, history=history)


@bp.route("/lines/new", methods=["POST"])
def add_line():
    user = get_current_user()
    car_id = request.form.get("car_id", type=int)
    amount = (request.form.get("amount") or "").strip()
    note = (request.form.get("note") or "").strip() or None
    cdate = parse_date(request.form.get("collection_date"), date.today())

    car = Car.query.filter_by(id=car_id, active=True).first() if car_id else None
    error = None
    if not car:
        error = _("Chagua gari kwenye orodha.")
    elif not amount or float(amount) <= 0:
        error = _("Weka kiasi sahihi.")
    else:
        error = validate_entry_date(cdate, _("Tarehe ya Makusanyo"))

    if error:
        flash(error, "danger")
        return redirect(url_for("cashier.index"))

    batch = _current_open_batch()
    if batch is None:
        batch = CashierCollectionBatch(batch_date=date.today(), created_by_id=user.id)
        db.session.add(batch)
        db.session.flush()

    # Same car + same date already logged in this batch -- add to it instead of
    # creating a second line, so e.g. a driver paying in twice for today shows as
    # one running total per car/date rather than a growing list of tiny rows.
    existing = CashierCollectionEntry.query.filter_by(
        batch_id=batch.id, car_id=car.id, collection_date=cdate
    ).first()
    if existing:
        existing.amount += float(amount)
        if note:
            existing.note = f"{existing.note}; {note}" if existing.note else note
        db.session.commit()
        flash(
            _(
                "Kiasi kimeongezwa kwenye rekodi iliyopo ya gari %(code)s (%(date)s). Jumla sasa: %(total)s",
                code=car.code,
                date=cdate.strftime("%d-%m-%Y"),
                total=f"{existing.amount:,.0f}",
            ),
            "success",
        )
    else:
        db.session.add(
            CashierCollectionEntry(
                batch_id=batch.id, car_id=car.id, amount=float(amount), note=note, collection_date=cdate
            )
        )
        db.session.commit()
        flash(_("Makusanyo ya gari %(code)s yameongezwa.", code=car.code), "success")
    return redirect(url_for("cashier.index"))


@bp.route("/lines/<int:entry_id>/delete", methods=["POST"])
def delete_line(entry_id):
    user = get_current_user()
    entry = CashierCollectionEntry.query.get_or_404(entry_id)
    if entry.batch.created_by_id != user.id or not entry.batch.is_open:
        flash(_("Huwezi kufuta kipengele hiki."), "danger")
    else:
        db.session.delete(entry)
        db.session.commit()
        flash(_("Kimefutwa."), "info")
    return redirect(url_for("cashier.index"))


@bp.route("/close", methods=["POST"])
def close():
    batch = _current_open_batch()
    if batch is None or not batch.lines:
        flash(_("Ongeza angalau gari moja kabla ya kufunga siku."), "danger")
    else:
        batch.status = "submitted"
        batch.submitted_at = datetime.utcnow()
        db.session.commit()
        flash(_("Siku imefungwa. Ofisi itathibitisha baada ya kupokea Trans No."), "success")
    return redirect(url_for("cashier.index"))
