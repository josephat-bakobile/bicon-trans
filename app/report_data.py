import calendar

from sqlalchemy import func

from .extensions import db
from .models import (
    Car,
    CarService,
    CarServiceItem,
    CollectionLine,
    CollectionTransaction,
    ConsumptionEntry,
    ExpenseCategory,
)
from .utils import month_bounds, period_totals


def summary_rows(start, end):
    totals = period_totals(start, end)
    rows = []
    for r in totals["rows"]:
        rows.append(
            {
                "car": r["car"].code,
                "car_id": r["car"].id,
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


def service_item_rows(start, end, car_id=None, category_id=None, status=None):
    """One row per part/charge (CarServiceItem) whose ticket's service_date falls
    in range -- the "what was replaced, on which car, when, at what price" view."""
    q = (
        db.session.query(CarServiceItem, CarService)
        .join(CarService, CarServiceItem.service_id == CarService.id)
        .join(Car, CarService.car_id == Car.id)
        .filter(CarService.service_date.between(start, end))
    )
    if car_id:
        q = q.filter(CarService.car_id == car_id)
    if category_id:
        q = q.filter(CarServiceItem.category_id == category_id)
    if status:
        q = q.filter(CarService.status == status)
    q = q.order_by(CarService.service_date.desc(), Car.code.asc(), CarServiceItem.id.asc())

    rows = []
    total = 0.0
    for item, ticket in q.all():
        rows.append(
            {
                "date": ticket.service_date,
                "car": ticket.car.code,
                "ticket_id": ticket.id,
                "status": ticket.status,
                "source": ticket.shop.name if ticket.shop_id else "Ndani",
                "category": item.category.name,
                "name": item.name,
                "quantity": item.quantity,
                "unit_cost": item.unit_cost,
                "cost": item.cost,
                "note": item.note or "",
            }
        )
        total += item.cost
    return rows, total


def service_category_totals(rows):
    """Spend + count per item category, most expensive first -- shows which kind
    of part/charge (oil, brakes, mechanical, labour...) costs the most overall."""
    totals = {}
    for r in rows:
        entry = totals.setdefault(r["category"], {"category": r["category"], "count": 0, "total": 0.0})
        entry["count"] += 1
        entry["total"] += r["cost"]
    return sorted(totals.values(), key=lambda e: e["total"], reverse=True)


def service_item_price_history(rows):
    """Groups rows by item name (case-insensitive) so a recurring part's price can
    be tracked over time -- min/avg/max/last unit cost, and where/when it was last
    bought. Flags an item as `price_rising` when its last price exceeds its
    average of previous purchases, a quick signal to check for overcharging."""
    groups = {}
    for r in sorted(rows, key=lambda r: r["date"]):
        key = r["name"].strip().lower()
        entry = groups.setdefault(
            key,
            {
                "name": r["name"],
                "category": r["category"],
                "count": 0,
                "unit_costs": [],
                "last_unit_cost": None,
                "last_date": None,
                "last_car": None,
            },
        )
        entry["count"] += 1
        entry["unit_costs"].append(r["unit_cost"])
        entry["last_unit_cost"] = r["unit_cost"]
        entry["last_date"] = r["date"]
        entry["last_car"] = r["car"]

    result = []
    for entry in groups.values():
        costs = entry["unit_costs"]
        prior = costs[:-1]
        result.append(
            {
                "name": entry["name"],
                "category": entry["category"],
                "count": entry["count"],
                "min_unit_cost": min(costs),
                "max_unit_cost": max(costs),
                "avg_unit_cost": sum(costs) / len(costs),
                "last_unit_cost": entry["last_unit_cost"],
                "last_date": entry["last_date"],
                "last_car": entry["last_car"],
                "price_rising": bool(prior) and entry["last_unit_cost"] > (sum(prior) / len(prior)),
            }
        )
    return sorted(result, key=lambda e: e["count"], reverse=True)


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


def pnl_rows(start, end):
    """Profit & Loss, one row per calendar month overlapping [start, end], oldest
    first. Revenue is Collections (money handed over by drivers); expenses are
    Consumption entries split by each category's pnl_group (COGS/OpEx/Other --
    see ExpenseCategory.pnl_group). running_net accumulates net profit within a
    calendar year (resets each January) for a year-to-date figure. swing_pct/
    swing_flag flag a month whose net profit moved more than 30% from the prior
    month -- a possible data error or a real event worth a second look either
    way. has_inferred_category flags a month with spend booked under a category
    that hasn't been manually classified yet (see categories.set_pnl_group)."""
    rows = []
    prev_net = None
    running_net = 0.0
    running_year = None
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        m_start, m_end = month_bounds(y, m)
        bucket_start = max(m_start, start)
        bucket_end = min(m_end, end)

        revenue = (
            db.session.query(func.coalesce(func.sum(CollectionLine.amount), 0.0))
            .filter(CollectionLine.collection_date.between(bucket_start, bucket_end))
            .scalar()
            or 0.0
        )

        group_totals = dict(
            db.session.query(ExpenseCategory.pnl_group, func.coalesce(func.sum(ConsumptionEntry.amount), 0.0))
            .join(ConsumptionEntry, ConsumptionEntry.category_id == ExpenseCategory.id)
            .filter(ConsumptionEntry.date.between(bucket_start, bucket_end))
            .group_by(ExpenseCategory.pnl_group)
            .all()
        )
        cogs = group_totals.get("cogs", 0.0)
        opex = group_totals.get("opex", 0.0)
        other = group_totals.get("other", 0.0)

        has_inferred = (
            db.session.query(ConsumptionEntry.id)
            .join(ExpenseCategory, ConsumptionEntry.category_id == ExpenseCategory.id)
            .filter(
                ConsumptionEntry.date.between(bucket_start, bucket_end),
                ExpenseCategory.pnl_group_inferred.is_(True),
            )
            .first()
            is not None
        )

        gross_profit = revenue - cogs
        operating_profit = gross_profit - opex
        net_profit = operating_profit - other
        gross_margin = (gross_profit / revenue * 100) if revenue else 0.0
        net_margin = (net_profit / revenue * 100) if revenue else 0.0

        if running_year != y:
            running_year = y
            running_net = 0.0
        running_net += net_profit

        swing_pct = None
        if prev_net not in (None, 0):
            swing_pct = (net_profit - prev_net) / abs(prev_net) * 100
        prev_net = net_profit

        rows.append(
            {
                "year": y,
                "month": m,
                "label": f"{calendar.month_abbr[m].upper()} {y}",
                "period_start": bucket_start,
                "period_end": bucket_end,
                "revenue": revenue,
                "cogs": cogs,
                "gross_profit": gross_profit,
                "opex": opex,
                "operating_profit": operating_profit,
                "other": other,
                "net_profit": net_profit,
                "gross_margin": gross_margin,
                "net_margin": net_margin,
                "running_net": running_net,
                "swing_pct": swing_pct,
                "swing_flag": swing_pct is not None and abs(swing_pct) > 30,
                "has_inferred_category": has_inferred,
            }
        )

        m += 1
        if m == 13:
            m = 1
            y += 1
    return rows


def pnl_totals(rows):
    """Grand totals across every row returned by pnl_rows, plus overall margins."""
    revenue = sum(r["revenue"] for r in rows)
    cogs = sum(r["cogs"] for r in rows)
    opex = sum(r["opex"] for r in rows)
    other = sum(r["other"] for r in rows)
    gross_profit = revenue - cogs
    operating_profit = gross_profit - opex
    net_profit = operating_profit - other
    return {
        "revenue": revenue,
        "cogs": cogs,
        "gross_profit": gross_profit,
        "opex": opex,
        "operating_profit": operating_profit,
        "other": other,
        "net_profit": net_profit,
        "gross_margin": (gross_profit / revenue * 100) if revenue else 0.0,
        "net_margin": (net_profit / revenue * 100) if revenue else 0.0,
    }
