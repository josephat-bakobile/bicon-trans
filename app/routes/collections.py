from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _

from ..extensions import db
from ..models import CashierCollectionBatch, Car, CollectionLine, CollectionTransaction
from ..security import get_current_user, require_permission
from ..sms import can_send, send_and_log, send_debt_payment_sms
from ..utils import (
    apply_collection_debt_repayment,
    car_debt_balance,
    next_trans_no,
    parse_date,
    remove_collection_debt_payments,
    transaction_locked,
    validate_entry_date,
)

bp = Blueprint("collections", __name__)


def _send_debt_payment_sms(debt_payments):
    """Sends one debt-payment SMS per car, summing amounts across every line
    that repaid that car's debt in this transaction (a transaction can carry
    multiple lines for the same car -- see create_transaction docstring)."""
    totals = {}
    for car, amount in debt_payments:
        prev_car, prev_amount = totals.get(car.id, (car, 0))
        totals[car.id] = (prev_car, prev_amount + amount)
    for car, amount in totals.values():
        send_debt_payment_sms(car, amount, car_debt_balance(car.id), get_current_user())


def _validate_dates(tdate, lines):
    error = validate_entry_date(tdate, _("Tarehe ya Muamala"))
    if error:
        return error
    for line in lines:
        error = validate_entry_date(line["collection_date"], _("Tarehe ya Makusanyo"))
        if error:
            return error
    return None


def _extract_lines(form, fallback_date):
    car_ids = form.getlist("car_id[]")
    amounts = form.getlist("amount[]")
    notes = form.getlist("note[]")
    collection_dates = form.getlist("collection_date[]")
    lines = []
    for i, (cid, amt) in enumerate(zip(car_ids, amounts)):
        amt = (amt or "").strip()
        if cid and amt:
            note = notes[i].strip() if i < len(notes) and notes[i] else None
            cdate = collection_dates[i].strip() if i < len(collection_dates) and collection_dates[i] else None
            lines.append(
                {
                    "car_id": int(cid),
                    "amount": float(amt),
                    "note": note,
                    "collection_date": parse_date(cdate, fallback_date),
                }
            )
    return lines


def _values_from_txn(txn):
    if txn is None:
        return {"id": None, "trans_no": next_trans_no(), "date": "", "note": "", "lines": []}
    sorted_lines = sorted(txn.lines, key=lambda l: (l.car.code, l.collection_date))
    return {
        "id": txn.id,
        "trans_no": txn.trans_no,
        "date": txn.transaction_date.isoformat(),
        "note": txn.note or "",
        "lines": [
            {
                "car_id": l.car_id,
                "amount": l.amount,
                "note": l.note or "",
                "collection_date": l.collection_date.isoformat(),
            }
            for l in sorted_lines
        ],
    }


def _values_from_form(form, lines, trans_no, txn_id=None):
    code_map = {c.id: c.code for c in Car.query.all()}
    sorted_lines = sorted(lines, key=lambda l: (code_map.get(l["car_id"], ""), l["collection_date"]))
    display_lines = [
        {**l, "collection_date": l["collection_date"].isoformat() if l["collection_date"] else ""}
        for l in sorted_lines
    ]
    return {
        "id": txn_id,
        "trans_no": trans_no,
        "date": form.get("date", ""),
        "note": form.get("note", ""),
        "lines": display_lines,
    }


def create_transaction(tdate, note, trans_no, lines, cars):
    """Creates a CollectionTransaction + one CollectionLine per line dict, running
    debt auto-repayment on each exactly as a direct office entry does (see
    new()). Shared with routes.collections.confirm_batch so a cashier batch,
    once confirmed, is created through the identical path -- and therefore
    behaves identically in reports/reconciliation/debts -- as a transaction the
    office types in directly. Caller must have already validated trans_no/lines/
    dates and must commit(); returns (txn, debt_payments) where debt_payments is
    a list of (car, amount) tuples for send_debt_payment_sms."""
    txn = CollectionTransaction(transaction_date=tdate, note=note, trans_no=trans_no)
    db.session.add(txn)
    db.session.flush()
    car_map = {c.id: c for c in cars}
    debt_payments = []
    for line in lines:
        cl = CollectionLine(
            transaction_id=txn.id,
            car_id=line["car_id"],
            amount=line["amount"],
            note=line["note"],
            collection_date=line["collection_date"],
        )
        db.session.add(cl)
        db.session.flush()
        car = car_map.get(line["car_id"])
        if car:
            payment = apply_collection_debt_repayment(car, line["collection_date"], line["amount"], cl.id, tdate)
            if payment:
                debt_payments.append((car, payment.amount))
    return txn, debt_payments


@bp.route("/")
def list_view():
    start = parse_date(request.args.get("start"))
    end = parse_date(request.args.get("end"))
    q = CollectionTransaction.query
    if start:
        q = q.filter(CollectionTransaction.transaction_date >= start)
    if end:
        q = q.filter(CollectionTransaction.transaction_date <= end)
    transactions = q.order_by(CollectionTransaction.transaction_date.desc(), CollectionTransaction.id.desc()).all()
    return render_template(
        "collections/list.html",
        transactions=transactions,
        start=request.args.get("start", ""),
        end=request.args.get("end", ""),
    )


@bp.route("/new", methods=["GET", "POST"])
def new():
    cars = Car.query.filter_by(active=True).order_by(Car.code).all()
    if request.method == "POST":
        tdate = parse_date(request.form.get("date"), date.today())
        note = (request.form.get("note") or "").strip() or None
        trans_no = (request.form.get("trans_no") or "").strip()
        lines = _extract_lines(request.form, tdate)

        error = None
        if not trans_no:
            error = _("Weka Trans No.")
        elif not lines:
            error = _("Ongeza angalau gari moja na kiasi.")
        elif CollectionTransaction.query.filter_by(trans_no=trans_no).first():
            error = _("Trans No %(trans_no)s tayari ipo. Tumia namba nyingine.", trans_no=trans_no)
        else:
            error = _validate_dates(tdate, lines)

        if error:
            flash(error, "danger")
            values = _values_from_form(request.form, lines, trans_no)
            return render_template("collections/form.html", cars=cars, values=values, is_edit=False)

        txn, debt_payments = create_transaction(tdate, note, trans_no, lines, cars)
        db.session.commit()
        flash(_("Muamala %(trans_no)s umehifadhiwa.", trans_no=txn.trans_no), "success")
        _send_debt_payment_sms(debt_payments)
        return redirect(url_for("collections.list_view"))

    values = _values_from_txn(None)
    return render_template("collections/form.html", cars=cars, values=values, is_edit=False)


@bp.route("/pending")
def pending_batches():
    batches = (
        CashierCollectionBatch.query.filter_by(status="submitted")
        .order_by(CashierCollectionBatch.submitted_at.desc(), CashierCollectionBatch.id.desc())
        .all()
    )
    return render_template("collections/pending.html", batches=batches)


def _values_from_batch(batch):
    sorted_lines = sorted(batch.lines, key=lambda l: (l.car.code, l.collection_date))
    return {
        "id": None,
        "trans_no": next_trans_no(),
        "date": batch.batch_date.isoformat(),
        "note": batch.note or "",
        "lines": [
            {
                "car_id": l.car_id,
                "amount": l.amount,
                "note": l.note or "",
                "collection_date": l.collection_date.isoformat(),
            }
            for l in sorted_lines
        ],
    }


@bp.route("/pending/<int:batch_id>/return", methods=["POST"])
def return_batch(batch_id):
    """Sends a submitted batch back to 'open' so the cashier can fix a mistake
    (wrong amount/car/date) and re-submit -- used when the office spots a
    problem while reviewing it on the pending list, before it's confirmed into
    a real transaction."""
    batch = CashierCollectionBatch.query.filter_by(id=batch_id, status="submitted").first_or_404()
    batch.status = "open"
    batch.submitted_at = None
    db.session.commit()
    flash(
        _(
            "Makusanyo ya %(date)s yamerudishwa kwa mhasibu kwa marekebisho.",
            date=batch.batch_date.strftime("%d-%m-%Y"),
        ),
        "info",
    )
    return redirect(url_for("collections.pending_batches"))


@bp.route("/ongoing")
def ongoing_batches():
    """Read-only view for the office of batches a cashier is still building
    (status 'open', not yet closed/submitted) -- lets admin see cash logged so
    far without being able to act on it, since it isn't ready for review yet."""
    batches = (
        CashierCollectionBatch.query.filter_by(status="open")
        .order_by(CashierCollectionBatch.batch_date.desc(), CashierCollectionBatch.id.desc())
        .all()
    )
    return render_template("collections/ongoing.html", batches=batches)


@bp.route("/pending/<int:batch_id>/confirm", methods=["GET", "POST"])
def confirm_batch(batch_id):
    batch = CashierCollectionBatch.query.filter_by(id=batch_id, status="submitted").first_or_404()
    cars = Car.query.filter_by(active=True).order_by(Car.code).all()

    if request.method == "POST":
        tdate = parse_date(request.form.get("date"), batch.batch_date)
        note = (request.form.get("note") or "").strip() or None
        trans_no = (request.form.get("trans_no") or "").strip()
        lines = _extract_lines(request.form, tdate)

        error = None
        if not trans_no:
            error = _("Weka Trans No.")
        elif not lines:
            error = _("Ongeza angalau gari moja na kiasi.")
        elif CollectionTransaction.query.filter_by(trans_no=trans_no).first():
            error = _("Trans No %(trans_no)s tayari ipo. Tumia namba nyingine.", trans_no=trans_no)
        else:
            error = _validate_dates(tdate, lines)

        if error:
            flash(error, "danger")
            values = _values_from_form(request.form, lines, trans_no)
            return render_template(
                "collections/form.html", cars=cars, values=values, is_edit=False, confirm_batch=batch
            )

        txn, debt_payments = create_transaction(tdate, note, trans_no, lines, cars)
        batch.status = "confirmed"
        batch.confirmed_at = datetime.utcnow()
        batch.confirmed_by_id = get_current_user().id
        batch.transaction_id = txn.id
        db.session.commit()
        flash(_("Muamala %(trans_no)s umethibitishwa kutoka kwa mhasibu.", trans_no=txn.trans_no), "success")
        _send_debt_payment_sms(debt_payments)
        return redirect(url_for("collections.pending_batches"))

    values = _values_from_batch(batch)
    return render_template("collections/form.html", cars=cars, values=values, is_edit=False, confirm_batch=batch)


@bp.route("/<int:txn_id>/edit", methods=["GET", "POST"])
def edit(txn_id):
    txn = CollectionTransaction.query.get_or_404(txn_id)
    cars = Car.query.filter_by(active=True).order_by(Car.code).all()

    if transaction_locked(txn.transaction_date):
        flash(
            _(
                "Muamala %(trans_no)s umefungwa kwa kuhaririwa (zaidi ya wiki 1 tangu %(date)s).",
                trans_no=txn.trans_no,
                date=txn.transaction_date.strftime("%d-%m-%Y"),
            ),
            "danger",
        )
        return redirect(url_for("collections.list_view"))

    if request.method == "POST":
        tdate = parse_date(request.form.get("date"), txn.transaction_date)
        note = (request.form.get("note") or "").strip() or None
        trans_no = (request.form.get("trans_no") or "").strip()
        lines = _extract_lines(request.form, tdate)

        error = None
        if not trans_no:
            error = _("Weka Trans No.")
        elif not lines:
            error = _("Ongeza angalau gari moja na kiasi.")
        else:
            clash = CollectionTransaction.query.filter(
                CollectionTransaction.trans_no == trans_no, CollectionTransaction.id != txn.id
            ).first()
            if clash:
                error = _("Trans No %(trans_no)s tayari inatumika kwenye muamala mwingine.", trans_no=trans_no)
            else:
                error = _validate_dates(tdate, lines)

        if error:
            flash(error, "danger")
            values = _values_from_form(request.form, lines, trans_no, txn_id=txn.id)
            return render_template("collections/form.html", cars=cars, values=values, is_edit=True)

        txn.transaction_date = tdate
        txn.note = note
        txn.trans_no = trans_no
        old_line_ids = [l.id for l in txn.lines]
        remove_collection_debt_payments(old_line_ids)
        CollectionLine.query.filter_by(transaction_id=txn.id).delete()
        car_map = {c.id: c for c in cars}
        debt_payments = []
        for line in lines:
            cl = CollectionLine(
                transaction_id=txn.id,
                car_id=line["car_id"],
                amount=line["amount"],
                note=line["note"],
                collection_date=line["collection_date"],
            )
            db.session.add(cl)
            db.session.flush()
            car = car_map.get(line["car_id"])
            if car:
                payment = apply_collection_debt_repayment(car, line["collection_date"], line["amount"], cl.id, tdate)
                if payment:
                    debt_payments.append((car, payment.amount))
        db.session.commit()
        flash(_("Muamala %(trans_no)s umesasishwa.", trans_no=txn.trans_no), "success")
        _send_debt_payment_sms(debt_payments)
        return redirect(url_for("collections.list_view"))

    values = _values_from_txn(txn)
    return render_template("collections/form.html", cars=cars, values=values, is_edit=True)


@bp.route("/<int:txn_id>/delete", methods=["POST"])
def delete(txn_id):
    txn = CollectionTransaction.query.get_or_404(txn_id)

    if transaction_locked(txn.transaction_date):
        flash(
            _(
                "Muamala %(trans_no)s umefungwa kwa kufutwa (zaidi ya wiki 1 tangu %(date)s).",
                trans_no=txn.trans_no,
                date=txn.transaction_date.strftime("%d-%m-%Y"),
            ),
            "danger",
        )
        return redirect(url_for("collections.list_view"))

    trans_no = txn.trans_no
    remove_collection_debt_payments([l.id for l in txn.lines])
    db.session.delete(txn)
    db.session.commit()
    flash(_("Muamala %(trans_no)s umefutwa.", trans_no=trans_no), "info")
    return redirect(url_for("collections.list_view"))


@bp.route("/<int:txn_id>/sms/<int:car_id>", methods=["POST"])
@require_permission("sms")
def send_collection_sms(txn_id, car_id):
    txn = CollectionTransaction.query.get_or_404(txn_id)
    car = Car.query.get_or_404(car_id)
    line = next((l for l in txn.lines if l.car_id == car_id), None)

    if line is None:
        flash(_("Gari %(code)s halipo kwenye muamala %(trans_no)s.", code=car.code, trans_no=txn.trans_no), "danger")
        return redirect(url_for("collections.list_view"))

    ok, reason = can_send(car)
    if not ok:
        flash(reason, "danger")
        return redirect(url_for("collections.list_view"))

    message = (
        f"Habari {car.driver.name}, tumepokea makusanyo ya TSh {line.amount:,.0f} "
        f"tarehe {line.collection_date.strftime('%d-%m-%Y')}. Asante."
    )
    sent, error = send_and_log(car, "collection", message, get_current_user())
    if sent:
        flash(_("SMS ya makusanyo imetumwa kwa dereva wa %(code)s.", code=car.code), "success")
    else:
        flash(error, "danger")
    return redirect(url_for("collections.list_view"))
