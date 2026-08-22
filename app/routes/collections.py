from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import Car, CollectionLine, CollectionTransaction
from ..utils import next_trans_no, parse_date, transaction_locked, validate_entry_date

bp = Blueprint("collections", __name__)


def _validate_dates(tdate, lines):
    error = validate_entry_date(tdate, "Tarehe ya Muamala")
    if error:
        return error
    for line in lines:
        error = validate_entry_date(line["collection_date"], "Tarehe ya Makusanyo")
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
            error = "Weka Trans No."
        elif not lines:
            error = "Ongeza angalau gari moja na kiasi."
        elif CollectionTransaction.query.filter_by(trans_no=trans_no).first():
            error = f"Trans No {trans_no} tayari ipo. Tumia namba nyingine."
        else:
            error = _validate_dates(tdate, lines)

        if error:
            flash(error, "danger")
            values = _values_from_form(request.form, lines, trans_no)
            return render_template("collections/form.html", cars=cars, values=values, is_edit=False)

        txn = CollectionTransaction(transaction_date=tdate, note=note, trans_no=trans_no)
        db.session.add(txn)
        db.session.flush()
        for line in lines:
            db.session.add(
                CollectionLine(
                    transaction_id=txn.id,
                    car_id=line["car_id"],
                    amount=line["amount"],
                    note=line["note"],
                    collection_date=line["collection_date"],
                )
            )
        db.session.commit()
        flash(f"Muamala {txn.trans_no} umehifadhiwa.", "success")
        return redirect(url_for("collections.list_view"))

    values = _values_from_txn(None)
    return render_template("collections/form.html", cars=cars, values=values, is_edit=False)


@bp.route("/<int:txn_id>/edit", methods=["GET", "POST"])
def edit(txn_id):
    txn = CollectionTransaction.query.get_or_404(txn_id)
    cars = Car.query.filter_by(active=True).order_by(Car.code).all()

    if transaction_locked(txn.transaction_date):
        flash(
            f"Muamala {txn.trans_no} umefungwa kwa kuhaririwa "
            f"(zaidi ya wiki 1 tangu {txn.transaction_date.strftime('%d-%m-%Y')}).",
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
            error = "Weka Trans No."
        elif not lines:
            error = "Ongeza angalau gari moja na kiasi."
        else:
            clash = CollectionTransaction.query.filter(
                CollectionTransaction.trans_no == trans_no, CollectionTransaction.id != txn.id
            ).first()
            if clash:
                error = f"Trans No {trans_no} tayari inatumika kwenye muamala mwingine."
            else:
                error = _validate_dates(tdate, lines)

        if error:
            flash(error, "danger")
            values = _values_from_form(request.form, lines, trans_no, txn_id=txn.id)
            return render_template("collections/form.html", cars=cars, values=values, is_edit=True)

        txn.transaction_date = tdate
        txn.note = note
        txn.trans_no = trans_no
        CollectionLine.query.filter_by(transaction_id=txn.id).delete()
        for line in lines:
            db.session.add(
                CollectionLine(
                    transaction_id=txn.id,
                    car_id=line["car_id"],
                    amount=line["amount"],
                    note=line["note"],
                    collection_date=line["collection_date"],
                )
            )
        db.session.commit()
        flash(f"Muamala {txn.trans_no} umesasishwa.", "success")
        return redirect(url_for("collections.list_view"))

    values = _values_from_txn(txn)
    return render_template("collections/form.html", cars=cars, values=values, is_edit=True)


@bp.route("/<int:txn_id>/delete", methods=["POST"])
def delete(txn_id):
    txn = CollectionTransaction.query.get_or_404(txn_id)

    if transaction_locked(txn.transaction_date):
        flash(
            f"Muamala {txn.trans_no} umefungwa kwa kufutwa "
            f"(zaidi ya wiki 1 tangu {txn.transaction_date.strftime('%d-%m-%Y')}).",
            "danger",
        )
        return redirect(url_for("collections.list_view"))

    trans_no = txn.trans_no
    db.session.delete(txn)
    db.session.commit()
    flash(f"Muamala {trans_no} umefutwa.", "info")
    return redirect(url_for("collections.list_view"))
