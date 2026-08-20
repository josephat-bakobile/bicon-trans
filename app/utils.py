import calendar
import re
from datetime import date, timedelta

from sqlalchemy import func

from .extensions import db
from .models import (
    Car,
    CollectionLine,
    CollectionTransaction,
    ConsumptionEntry,
    Debt,
    DebtPayment,
    ShortfallClearance,
)


TRANSACTION_EDIT_WINDOW_DAYS = 7
MAX_BACKDATE_DAYS = 7


def transaction_locked(txn_date):
    """Collection transactions older than the edit window can no longer be changed."""
    return (date.today() - txn_date).days > TRANSACTION_EDIT_WINDOW_DAYS


def min_entry_date():
    return date.today() - timedelta(days=MAX_BACKDATE_DAYS)


def validate_entry_date(d, label="Tarehe"):
    """None if d is a valid date for new/edited data entry (today or within the last
    MAX_BACKDATE_DAYS days), otherwise a Swahili error message explaining why not."""
    today = date.today()
    if d > today:
        return f"{label} haiwezi kuwa baadaye ya leo ({today.strftime('%d-%m-%Y')})."
    if d < min_entry_date():
        return f"{label} haiwezi kuwa zaidi ya siku {MAX_BACKDATE_DAYS} zilizopita."
    return None


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
        coll_q = db.session.query(func.coalesce(func.sum(CollectionLine.amount), 0.0)).filter(
            CollectionLine.car_id == car.id
        )
        cons_q = db.session.query(func.coalesce(func.sum(ConsumptionEntry.amount), 0.0)).filter(
            ConsumptionEntry.car_id == car.id
        )
        if start and end:
            coll_q = coll_q.filter(CollectionLine.collection_date.between(start, end))
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
                .filter(CollectionLine.car_id == car.id, CollectionLine.collection_date.between(start, end))
                .scalar()
                or 0.0
            )
            values.append(collected)
            col_totals[i] += collected
        row_total = sum(values)
        grand_total += row_total
        rows.append({"car": car, "amounts": values, "total": row_total})

    return {"labels": labels, "rows": rows, "col_totals": col_totals, "grand_total": grand_total}


def shortfall_report(start, end):
    """Every (car, date) in range where a car with a daily_target either collected
    nothing or collected less than that target, whether or not it's been explained."""
    cars = Car.query.filter(Car.daily_target > 0).order_by(Car.code).all()
    if not cars:
        return []
    car_ids = [c.id for c in cars]

    collected_rows = (
        db.session.query(CollectionLine.collection_date, CollectionLine.car_id, func.sum(CollectionLine.amount))
        .filter(CollectionLine.car_id.in_(car_ids), CollectionLine.collection_date.between(start, end))
        .group_by(CollectionLine.collection_date, CollectionLine.car_id)
        .all()
    )
    collected_map = {(car_id, d): total for d, car_id, total in collected_rows}

    clearances = ShortfallClearance.query.filter(
        ShortfallClearance.car_id.in_(car_ids), ShortfallClearance.date.between(start, end)
    ).all()
    clearance_map = {(c.car_id, c.date): c for c in clearances}

    rows = []
    d = start
    while d <= end:
        for car in cars:
            collected = collected_map.get((car.id, d), 0.0)
            if collected < car.daily_target:
                clearance = clearance_map.get((car.id, d))
                rows.append(
                    {
                        "date": d,
                        "car": car,
                        "target": car.daily_target,
                        "collected": collected,
                        "shortfall": car.daily_target - collected,
                        "clearance": clearance,
                    }
                )
        d += timedelta(days=1)
    rows.sort(key=lambda r: (r["date"], r["car"].code))
    return rows
