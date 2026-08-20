from .extensions import db
from .models import CollectionLine, CollectionTransaction, ConsumptionEntry
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
    q = (
        db.session.query(CollectionLine, CollectionTransaction)
        .join(CollectionTransaction, CollectionLine.transaction_id == CollectionTransaction.id)
        .filter(CollectionTransaction.date.between(start, end))
    )
    if car_id:
        q = q.filter(CollectionLine.car_id == car_id)
    q = q.order_by(CollectionTransaction.date.asc(), CollectionTransaction.id.asc())

    rows = []
    total = 0.0
    for line, txn in q.all():
        rows.append(
            {
                "date": txn.date,
                "trans_no": txn.trans_no,
                "car": line.car.code,
                "amount": line.amount,
                "note": line.note or txn.note or "",
            }
        )
        total += line.amount
    return rows, total


def consumption_rows(start, end, car_id=None, category_id=None):
    q = ConsumptionEntry.query.filter(ConsumptionEntry.date.between(start, end))
    if car_id:
        q = q.filter(ConsumptionEntry.car_id == car_id)
    if category_id:
        q = q.filter(ConsumptionEntry.category_id == category_id)
    q = q.order_by(ConsumptionEntry.date.asc(), ConsumptionEntry.id.asc())

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
