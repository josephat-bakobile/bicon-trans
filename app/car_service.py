from datetime import date, timedelta

from .models import Car, CarService, ExpenseCategory, ShortfallClearance
from .utils import active_pause_for_car

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


def _last_qualifying_service(car_id):
    """Most recent CarService that counts as a real physical service day: either
    a staff-logged ticket (shop_id is None) booked under an is_service category,
    or a shop ticket (shop_id set) that's been fully paid (status "confirmed")
    under an is_service payment_category -- a vendor ticket still being
    negotiated/paid isn't yet a confirmed service day, so it doesn't count until
    then (mirrors routes.service.add_payment's shortfall-clearance sync)."""
    staff = (
        CarService.query.join(ExpenseCategory, CarService.category_id == ExpenseCategory.id)
        .filter(CarService.car_id == car_id, CarService.shop_id.is_(None), ExpenseCategory.is_service.is_(True))
        .order_by(CarService.service_date.desc(), CarService.id.desc())
        .first()
    )
    vendor = (
        CarService.query.join(ExpenseCategory, CarService.payment_category_id == ExpenseCategory.id)
        .filter(
            CarService.car_id == car_id,
            CarService.shop_id.isnot(None),
            CarService.status == "confirmed",
            ExpenseCategory.is_service.is_(True),
        )
        .order_by(CarService.service_date.desc(), CarService.id.desc())
        .first()
    )
    candidates = [c for c in (staff, vendor) if c is not None]
    if not candidates:
        return None
    return max(candidates, key=lambda c: (c.service_date, c.id))


def predict_for_car(car, today=None):
    """Next service due date for a car, counted forward from its most recent
    qualifying CarService entry -- either a staff-logged ticket booked under an
    is_service category (e.g. SERVICE, not MATUMIZI), or a shop/vendor ticket
    fully paid under an is_service payment category. A shop ticket still open/
    unpaid doesn't count yet (a shop billing one part isn't necessarily a full
    physical service day until it's actually settled), and neither do staff
    tickets for incidental costs that aren't a real service -- none of those
    should reset this clock. Only days the car worked normally count toward
    the interval -- each excused (uncollected/partial + cleared) day in between
    pushes the due date one calendar day later."""
    today = today or date.today()
    last = _last_qualifying_service(car.id)
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
    a baseline service yet sort last. A car currently paused (skipped) from
    collection is left out entirely -- it isn't expected to work, so it has no
    service due date to track -- and reappears, showing its last service, once
    resumed."""
    cars = cars if cars is not None else Car.query.filter_by(active=True).order_by(Car.code).all()
    cars = [c for c in cars if not active_pause_for_car(c)]
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
