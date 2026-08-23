from .extensions import db
from .models import Car, CollectionLine, CollectionTransaction, ConsumptionEntry
from .utils import period_totals


def summary_rows(start, end):
    totals = period_totals(start, end)
    rows = []
    for r in totals["rows"]:
        rows.append(
            {
                "car": r["car"].code,
                "collected": r["collected"],
                "consumed": r["consumed"],
                "net": r["net"],
            }
        )
    return rows, totals


def collections_rows(start, end, car_id=None):
    """One row per car contribution, keyed off collection_date (the day the amount
    counts toward), not the transaction's bank date."""
    q = (
        db.session.query(CollectionLine, CollectionTransaction)
        .join(CollectionTransaction, CollectionLine.transaction_id == CollectionTransaction.id)
        .join(Car, CollectionLine.car_id == Car.id)
        .filter(CollectionLine.collection_date.between(start, end))
    )
    if car_id:
        q = q.filter(CollectionLine.car_id == car_id)
    q = q.order_by(CollectionLine.collection_date.desc(), Car.code.asc(), CollectionTransaction.id.asc())

    rows = []
    total = 0.0
    for line, txn in q.all():
        rows.append(
            {
                "date": line.collection_date,
                "trans_date": txn.transaction_date,
                "trans_no": txn.trans_no,
                "car": line.car.code,
                "amount": line.amount,
                "note": line.note or txn.note or "",
            }
        )
        total += line.amount
    return rows, total


def reconciliation_rows(start, end):
    """Transaction-level view (no car breakdown) for matching against the bank
    agent's own records — keyed off transaction_date, the bank/handover date."""
    txns = (
        CollectionTransaction.query.filter(CollectionTransaction.transaction_date.between(start, end))
        .order_by(CollectionTransaction.transaction_date.asc(), CollectionTransaction.id.asc())
        .all()
    )
    rows = []
    total = 0.0
    for txn in txns:
        rows.append(
            {
                "transaction_date": txn.transaction_date,
                "trans_no": txn.trans_no,
                "total": txn.total,
                "note": txn.note or "",
            }
        )
        total += txn.total
    return rows, total


def consumption_rows(start, end, car_id=None, category_id=None):
    q = ConsumptionEntry.query.join(Car, ConsumptionEntry.car_id == Car.id).filter(
        ConsumptionEntry.date.between(start, end)
    )
    if car_id:
        q = q.filter(ConsumptionEntry.car_id == car_id)
    if category_id:
        q = q.filter(ConsumptionEntry.category_id == category_id)
    q = q.order_by(ConsumptionEntry.date.asc(), Car.code.asc(), ConsumptionEntry.id.asc())

    rows = []
    total = 0.0
    for e in q.all():
        rows.append(
            {
                "date": e.date,
                "car": e.car.code,
                "category": e.category.name,
                "amount": e.amount,
                "description": e.description or "",
            }
        )
        total += e.amount
    return rows, total
