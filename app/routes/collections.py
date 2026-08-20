from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import Car, CollectionLine, CollectionTransaction
from ..security import require_action_code
from ..utils import next_trans_no, parse_date

bp = Blueprint("collections", __name__)


def _extract_lines(form):
    car_ids = form.getlist("car_id[]")
    amounts = form.getlist("amount[]")
    notes = form.getlist("note[]")
    lines = []
    for i, (cid, amt) in enumerate(zip(car_ids, amounts)):
        amt = (amt or "").strip()
        if cid and amt:
            note = notes[i].strip() if i < len(notes) and notes[i] else None
            lines.append({"car_id": int(cid), "amount": float(amt), "note": note})
    return lines


def _values_from_txn(txn):
    if txn is None:
        return {"id": None, "trans_no": next_trans_no(), "date": "", "note": "", "lines": []}
    return {
        "id": txn.id,
        "trans_no": txn.trans_no,
        "date": txn.date.isoformat(),
        "note": txn.note or "",
        "lines": [{"car_id": l.car_id, "amount": l.amount, "note": l.note or ""} for l in txn.lines],
    }


def _values_from_form(form, lines, trans_no, txn_id=None):
    return {
        "id": txn_id,
        "trans_no": trans_no,
        "date": form.get("date", ""),
        "note": form.get("note", ""),
        "lines": lines,
    }


@bp.route("/")
def list_view():
    start = parse_date(request.args.get("start"))
    end = parse_date(request.args.get("end"))
    q = CollectionTransaction.query
    if start:
        q = q.filter(CollectionTransaction.date >= start)
    if end:
        q = q.filter(CollectionTransaction.date <= end)
    transactions = q.order_by(CollectionTransaction.date.desc(), CollectionTransaction.id.desc()).all()
    return render_template(
        "collections/list.html",
        transactions=transactions,
        start=request.args.get("start", ""),
        end=request.args.get("end", ""),
    )


@bp.route("/new", methods=["GET", "POST"])
@require_action_code
def new():
    cars = Car.query.filter_by(active=True).order_by(Car.code).all()
    if request.method == "POST":
        tdate = parse_date(request.form.get("date"), date.today())
        note = (request.form.get("note") or "").strip() or None
        trans_no = (request.form.get("trans_no") or "").strip()
        lines = _extract_lines(request.form)

        error = None
        if not trans_no:
            error = "Weka Trans No."
        elif not lines:
            error = "Ongeza angalau gari moja na kiasi."
        elif CollectionTransaction.query.filter_by(trans_no=trans_no).first():
            error = f"Trans No {trans_no} tayari ipo. Tumia namba nyingine."

        if error:
            flash(error, "danger")
            values = _values_from_form(request.form, lines, trans_no)
            return render_template("collections/form.html", cars=cars, values=values, is_edit=False)

        txn = CollectionTransaction(date=tdate, note=note, trans_no=trans_no)
        db.session.add(txn)
        db.session.flush()
        for line in lines:
            db.session.add(
                CollectionLine(transaction_id=txn.id, car_id=line["car_id"], amount=line["amount"], note=line["note"])
            )
        db.session.commit()
        flash(f"Muamala {txn.trans_no} umehifadhiwa.", "success")
        return redirect(url_for("collections.list_view"))

    values = _values_from_txn(None)
    return render_template("collections/form.html", cars=cars, values=values, is_edit=False)


@bp.route("/<int:txn_id>/edit", methods=["GET", "POST"])
@require_action_code
def edit(txn_id):
    txn = CollectionTransaction.query.get_or_404(txn_id)
    cars = Car.query.filter_by(active=True).order_by(Car.code).all()

    if request.method == "POST":
        tdate = parse_date(request.form.get("date"), txn.date)
        note = (request.form.get("note") or "").strip() or None
        trans_no = (request.form.get("trans_no") or "").strip()
        lines = _extract_lines(request.form)

        error = None
        if not trans_no:
            error = "Weka Trans No."
        elif not lines:
            error = "Ongeza angalau gari moja na kiasi."
        else:
            clash = CollectionTransaction.query.filter(
                CollectionTransaction.trans_no == trans_no, CollectionTransaction.id != txn.id
            ).first()
            if clash:
                error = f"Trans No {trans_no} tayari inatumika kwenye muamala mwingine."

        if error:
            flash(error, "danger")
            values = _values_from_form(request.form, lines, trans_no, txn_id=txn.id)
            return render_template("collections/form.html", cars=cars, values=values, is_edit=True)

        txn.date = tdate
        txn.note = note
        txn.trans_no = trans_no
        CollectionLine.query.filter_by(transaction_id=txn.id).delete()
        for line in lines:
            db.session.add(
                CollectionLine(transaction_id=txn.id, car_id=line["car_id"], amount=line["amount"], note=line["note"])
            )
        db.session.commit()
        flash(f"Muamala {txn.trans_no} umesasishwa.", "success")
        return redirect(url_for("collections.list_view"))

    values = _values_from_txn(txn)
    return render_template("collections/form.html", cars=cars, values=values, is_edit=True)


@bp.route("/<int:txn_id>/delete", methods=["POST"])
@require_action_code
def delete(txn_id):
    txn = CollectionTransaction.query.get_or_404(txn_id)
    trans_no = txn.trans_no
    db.session.delete(txn)
    db.session.commit()
    flash(f"Muamala {trans_no} umefutwa.", "info")
    return redirect(url_for("collections.list_view"))
