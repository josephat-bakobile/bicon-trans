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
    Driver,
    ExpenseCategory,
    ShortfallClearance,
)


TRANSACTION_EDIT_WINDOW_DAYS = 7
MAX_BACKDATE_DAYS = 7
LAUNCH_DATE = date(2026, 8, 16)


def transaction_locked(txn_date):
    """Collection transactions older than the edit window can no longer be changed."""
    return (date.today() - txn_date).days > TRANSACTION_EDIT_WINDOW_DAYS


def paginate(items, page, per_page=20):
    """Slice items for the given 1-indexed page, clamped to the valid range."""
    total_pages = max(1, -(-len(items) // per_page))
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    return items[start : start + per_page], page, total_pages


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


def shortfall_totals(start=None, end=None):
    """Sum of shortfall amounts since LAUNCH_DATE, split into open (Wazi) and
    explained (Imefafanuliwa) buckets."""
    rows = shortfall_report(start or LAUNCH_DATE, end or date.today())
    open_total = sum(r["shortfall"] for r in rows if not r["clearance"])
    cleared_total = sum(r["shortfall"] for r in rows if r["clearance"])
    return {"open_total": open_total, "cleared_total": cleared_total}


def car_achievement_rates(start, end):
    """Per-car % of days in range the collected amount met/exceeded daily_target."""
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

    total_days = (end - start).days + 1
    rows = []
    for car in cars:
        days_hit = 0
        d = start
        while d <= end:
            if collected_map.get((car.id, d), 0.0) >= car.daily_target:
                days_hit += 1
            d += timedelta(days=1)
        rate = (days_hit / total_days * 100) if total_days else 0.0
        rows.append({"car": car, "days_hit": days_hit, "days_total": total_days, "rate": rate})
    rows.sort(key=lambda r: r["rate"], reverse=True)
    return rows


def shortfall_streaks(start=None, end=None):
    """Current run of consecutive days (ending at `end`, default today) each car has
    had an unresolved open shortfall, back to `start` (default LAUNCH_DATE). Cars with
    no active streak are omitted."""
    end = end or date.today()
    lookback_start = start or LAUNCH_DATE
    cars = Car.query.filter(Car.daily_target > 0).order_by(Car.code).all()
    if not cars:
        return []
    car_ids = [c.id for c in cars]

    collected_rows = (
        db.session.query(CollectionLine.collection_date, CollectionLine.car_id, func.sum(CollectionLine.amount))
        .filter(CollectionLine.car_id.in_(car_ids), CollectionLine.collection_date.between(lookback_start, end))
        .group_by(CollectionLine.collection_date, CollectionLine.car_id)
        .all()
    )
    collected_map = {(car_id, d): total for d, car_id, total in collected_rows}

    cleared_dates = {
        (c.car_id, c.date)
        for c in ShortfallClearance.query.filter(
            ShortfallClearance.car_id.in_(car_ids), ShortfallClearance.date.between(lookback_start, end)
        ).all()
    }

    rows = []
    for car in cars:
        streak = 0
        d = end
        while d >= lookback_start:
            collected = collected_map.get((car.id, d), 0.0)
            is_open_shortfall = collected < car.daily_target and (car.id, d) not in cleared_dates
            if not is_open_shortfall:
                break
            streak += 1
            d -= timedelta(days=1)
        if streak > 0:
            rows.append({"car": car, "streak_days": streak})
    rows.sort(key=lambda r: r["streak_days"], reverse=True)
    return rows


def driver_totals(start=None, end=None):
    """Per-driver (current car assignment) collected/consumed/net and open-shortfall
    totals. Each driver operates at most one car, so this is one row per car with
    an assigned driver -- reflects the current assignment, not historical."""
    cars = Car.query.filter(Car.driver_id.isnot(None)).join(Car.driver).order_by(Driver.name).all()
    if not cars:
        return {"rows": [], "grand_collected": 0.0, "grand_consumed": 0.0, "grand_net": 0.0, "grand_shortfall_open": 0.0}

    shortfall_rows = shortfall_report(start or LAUNCH_DATE, end or date.today())
    open_shortfall_by_car = {}
    for r in shortfall_rows:
        if not r["clearance"]:
            open_shortfall_by_car[r["car"].id] = open_shortfall_by_car.get(r["car"].id, 0.0) + r["shortfall"]

    rows = []
    grand_collected = grand_consumed = grand_shortfall_open = 0.0
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
        shortfall_open = open_shortfall_by_car.get(car.id, 0.0)

        rows.append(
            {
                "driver": car.driver.name,
                "cars": car.code,
                "collected": collected,
                "consumed": consumed,
                "net": collected - consumed,
                "shortfall_open": shortfall_open,
            }
        )
        grand_collected += collected
        grand_consumed += consumed
        grand_shortfall_open += shortfall_open

    return {
        "rows": rows,
        "grand_collected": grand_collected,
        "grand_consumed": grand_consumed,
        "grand_net": grand_collected - grand_consumed,
        "grand_shortfall_open": grand_shortfall_open,
    }


def category_totals(start=None, end=None):
    """Total consumption per expense category (default all time), largest first."""
    categories = ExpenseCategory.query.order_by(ExpenseCategory.name).all()
    rows = []
    grand_total = 0.0
    for cat in categories:
        q = db.session.query(func.coalesce(func.sum(ConsumptionEntry.amount), 0.0)).filter(
            ConsumptionEntry.category_id == cat.id
        )
        if start and end:
            q = q.filter(ConsumptionEntry.date.between(start, end))
        total = q.scalar() or 0.0
        if total:
            rows.append({"category": cat, "total": total})
            grand_total += total
    rows.sort(key=lambda r: r["total"], reverse=True)
    return {"rows": rows, "grand_total": grand_total}


def debt_monthly_trend(start, end):
    """Debt owed vs paid per calendar month overlapping [start, end], oldest first."""
    points = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        m_start, m_end = month_bounds(y, m)
        bucket_start = max(m_start, start)
        bucket_end = min(m_end, end)
        owed = (
            db.session.query(func.coalesce(func.sum(Debt.amount), 0.0))
            .filter(Debt.date.between(bucket_start, bucket_end))
            .scalar()
            or 0.0
        )
        paid = (
            db.session.query(func.coalesce(func.sum(DebtPayment.amount), 0.0))
            .filter(DebtPayment.date.between(bucket_start, bucket_end))
            .scalar()
            or 0.0
        )
        points.append(
            {
                "label": f"{calendar.month_abbr[m].upper()} {y % 100:02d}",
                "owed": owed,
                "paid": paid,
                "net": owed - paid,
            }
        )
        m += 1
        if m == 13:
            m = 1
            y += 1
    return points
