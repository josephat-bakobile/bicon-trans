import calendar
import re
from datetime import date

from sqlalchemy import func

from .extensions import db
from .models import Car, CollectionLine, CollectionTransaction, ConsumptionEntry, Debt, DebtPayment


def next_trans_no():
    """Suggest the next transaction number, based on the highest trailing digits seen so far."""
    max_n = 0
    for (trans_no,) in db.session.query(CollectionTransaction.trans_no).all():
        m = re.search(r"(\d+)$", trans_no or "")
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"TRX-{max_n + 1:05d}"


def parse_date(value, fallback=None):
    if value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    return fallback


def month_bounds(year, month):
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def period_totals(start=None, end=None):
    """Per-car collected/consumed totals for a date range (None/None = all time)."""
    cars = Car.query.order_by(Car.code).all()
    rows = []
    grand_collected = 0.0
    grand_consumed = 0.0
    for car in cars:
        coll_q = (
            db.session.query(func.coalesce(func.sum(CollectionLine.amount), 0.0))
            .join(CollectionTransaction, CollectionLine.transaction_id == CollectionTransaction.id)
            .filter(CollectionLine.car_id == car.id)
        )
        cons_q = db.session.query(func.coalesce(func.sum(ConsumptionEntry.amount), 0.0)).filter(
            ConsumptionEntry.car_id == car.id
        )
        if start and end:
            coll_q = coll_q.filter(CollectionTransaction.date.between(start, end))
            cons_q = cons_q.filter(ConsumptionEntry.date.between(start, end))

        collected = coll_q.scalar() or 0.0
        consumed = cons_q.scalar() or 0.0
        grand_collected += collected
        grand_consumed += consumed
        rows.append(
            {
                "car": car,
                "collected": collected,
                "consumed": consumed,
                "net": collected - consumed,
            }
        )
    return {
        "rows": rows,
        "grand_collected": grand_collected,
        "grand_consumed": grand_consumed,
        "grand_net": grand_collected - grand_consumed,
    }


def car_debt_balance(car_id):
    """Outstanding debt balance (owed - paid) for a single car, all time."""
    owed = (
        db.session.query(func.coalesce(func.sum(Debt.amount), 0.0)).filter(Debt.car_id == car_id).scalar() or 0.0
    )
    paid = (
        db.session.query(func.coalesce(func.sum(DebtPayment.amount), 0.0))
        .filter(DebtPayment.car_id == car_id)
        .scalar()
        or 0.0
    )
    return owed - paid


def debt_balances():
    """Per-car running debt balance (owed - paid), all time."""
    cars = Car.query.order_by(Car.code).all()
    rows = []
    grand_owed = 0.0
    grand_paid = 0.0
    for car in cars:
        owed = (
            db.session.query(func.coalesce(func.sum(Debt.amount), 0.0))
            .filter(Debt.car_id == car.id)
            .scalar()
            or 0.0
        )
        paid = (
            db.session.query(func.coalesce(func.sum(DebtPayment.amount), 0.0))
            .filter(DebtPayment.car_id == car.id)
            .scalar()
            or 0.0
        )
        grand_owed += owed
        grand_paid += paid
        rows.append(
            {
                "car": car,
                "owed": owed,
                "paid": paid,
                "balance": owed - paid,
            }
        )
    return {
        "rows": rows,
        "grand_owed": grand_owed,
        "grand_paid": grand_paid,
        "grand_balance": grand_owed - grand_paid,
    }


def _last_n_months(n):
    today = date.today()
    y, m = today.year, today.month
    seq = []
    for _ in range(n):
        seq.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    seq.reverse()
    return seq


def monthly_trend(months=6):
    """Last N calendar months of collected vs consumed totals, oldest first."""
    points = []
    for y, m in _last_n_months(months):
        start, end = month_bounds(y, m)
        totals = period_totals(start, end)
        points.append(
            {
                "label": f"{calendar.month_abbr[m].upper()} {y % 100:02d}",
                "collected": totals["grand_collected"],
                "consumed": totals["grand_consumed"],
            }
        )
    return points


def car_month_matrix(months=6):
    """Cross-tab of each car's MAKUSANYO contribution across the last N calendar months."""
    seq = _last_n_months(months)
    labels = [f"{calendar.month_abbr[m].upper()} {y % 100:02d}" for y, m in seq]
    cars = Car.query.order_by(Car.code).all()

    rows = []
    col_totals = [0.0] * len(seq)
    grand_total = 0.0
    for car in cars:
        values = []
        for i, (y, m) in enumerate(seq):
            start, end = month_bounds(y, m)
            collected = (
                db.session.query(func.coalesce(func.sum(CollectionLine.amount), 0.0))
                .join(CollectionTransaction, CollectionLine.transaction_id == CollectionTransaction.id)
                .filter(CollectionLine.car_id == car.id, CollectionTransaction.date.between(start, end))
                .scalar()
                or 0.0
            )
            values.append(collected)
            col_totals[i] += collected
        row_total = sum(values)
        grand_total += row_total
        rows.append({"car": car, "amounts": values, "total": row_total})

    return {"labels": labels, "rows": rows, "col_totals": col_totals, "grand_total": grand_total}
