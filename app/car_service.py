from datetime import date, timedelta

from .models import Car, CarService, ShortfallClearance

DUE_SOON_DAYS = 3


def _excused_dates(car_id, after_date):
    """Dates after `after_date` where this car either didn't collect at all
    (amount 0) or only collected partially, and the shortfall was cleared/
    explained. These don't count toward the service interval."""
    rows = ShortfallClearance.query.filter(
        ShortfallClearance.car_id == car_id,
        ShortfallClearance.date > after_date,
    ).all()
    return {r.date for r in rows}


def predict_for_car(car, today=None):
    """Next service due date for a car, counted forward from its most recent
    staff-logged CarService entry (shop-submitted parts tickets are excluded --
    a shop billing one part isn't necessarily a full physical service day, so it
    shouldn't reset this clock). Only days the car worked normally count toward
    the interval -- each excused (uncollected/partial + cleared) day in between
    pushes the due date one calendar day later."""
    today = today or date.today()
    last = (
        CarService.query.filter_by(car_id=car.id, shop_id=None)
        .order_by(CarService.service_date.desc(), CarService.id.desc())
        .first()
    )
    if last is None:
        return {
            "car": car,
            "last_service": None,
            "due_date": None,
            "days_remaining": None,
            "excused_days": 0,
            "status": "no_baseline",
        }

    interval = car.service_interval_days or 20
    excused = _excused_dates(car.id, last.service_date)

    d = last.service_date
    counted = 0
    excused_count = 0
    while counted < interval:
        d += timedelta(days=1)
        if d in excused:
            excused_count += 1
        else:
            counted += 1
    due_date = d

    days_remaining = (due_date - today).days
    if days_remaining < 0:
        status = "overdue"
    elif days_remaining <= DUE_SOON_DAYS:
        status = "due_soon"
    else:
        status = "ok"

    return {
        "car": car,
        "last_service": last,
        "due_date": due_date,
        "days_remaining": days_remaining,
        "excused_days": excused_count,
        "status": status,
    }


def service_predictions(cars=None):
    """Prediction rows for every (active) car, most urgent first; cars without
    a baseline service yet sort last."""
    cars = cars if cars is not None else Car.query.filter_by(active=True).order_by(Car.code).all()
    rows = [predict_for_car(c, today=None) for c in cars]
    rows.sort(key=lambda r: (r["days_remaining"] is None, r["days_remaining"]))
    return rows


def shop_dashboard():
    """Simple at-a-glance vendor summary: how many shop tickets are still active
    (open or awaiting payment) and how much is currently owed across all of them,
    broken down per shop so the office can see who to pay next. Shared by the
    main Dashboard and the Huduma/service ticket list."""
    shop_tickets = CarService.query.filter(CarService.shop_id.isnot(None)).all()
    active = [t for t in shop_tickets if t.is_open or t.is_submitted or t.is_approved]
    unpaid_total = sum(t.balance_due for t in shop_tickets if t.is_submitted or t.is_approved)

    by_shop = {}
    for t in active:
        row = by_shop.setdefault(t.shop_id, {"shop": t.shop, "active": 0, "unpaid": 0.0})
        row["active"] += 1
        if t.is_submitted or t.is_approved:
            row["unpaid"] += t.balance_due

    return {
        "active_count": len(active),
        "unpaid_total": unpaid_total,
        "by_shop": sorted(by_shop.values(), key=lambda r: r["unpaid"], reverse=True),
    }
