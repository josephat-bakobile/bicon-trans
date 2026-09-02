import calendar
from datetime import date, timedelta

from .extensions import db
from .models import Car, CarService, DebtPayment, DriverAllowance, ShortfallClearance
from .utils import car_debt_balance

MID_MONTH_START_DAY = 13
# A period this many days overdue without a confirmed DriverAllowance is
# forfeited -- the prediction moves on to the next period instead of showing
# it as ever-more overdue.
OVERDUE_SKIP_DAYS = 3

PERIOD_LABELS = {"kati": "katikati ya mwezi", "mwisho": "mwisho wa mwezi"}
PERIOD_ORDER = {"kati": 0, "mwisho": 1}


def _allowance_cars():
    """Cars currently eligible for a driver allowance: active, has an assigned
    driver, and earns a daily collection target -- ordered the same way the rest
    of the app orders cars, since that order is also the stagger sequence."""
    return (
        Car.query.filter(Car.active.is_(True), Car.driver_id.isnot(None), Car.daily_target > 0)
        .order_by(Car.code)
        .all()
    )


def _next_period(period_year, period_month, period_type):
    if period_type == "kati":
        return period_year, period_month, "mwisho"
    if period_month == 12:
        return period_year + 1, 1, "kati"
    return period_year, period_month + 1, "kati"


def _last_allowance(car_id):
    rows = DriverAllowance.query.filter_by(car_id=car_id).all()
    if not rows:
        return None
    rows.sort(key=lambda r: (r.period_year, r.period_month, PERIOD_ORDER[r.period_type]))
    return rows[-1]


def _service_dates(car_id):
    """Every date this car has a recorded CarService -- it doesn't collect on a
    service day either, so the allowance schedule must never land on one."""
    rows = db.session.query(CarService.service_date).filter(CarService.car_id == car_id).all()
    return {d for (d,) in rows}


def scheduled_date_for(car_id, period_year, period_month, period_type):
    """The staggered day-of-month this car's driver is due their allowance for
    the given period, based on this car's position among currently eligible cars.
    Pushed forward a day at a time past any date this car already has a recorded
    service on, since that day's non-collection is already explained by the
    service, not the allowance."""
    cars = _allowance_cars()
    car_ids = [c.id for c in cars]
    index = car_ids.index(car_id) if car_id in car_ids else 0
    days_in_month = calendar.monthrange(period_year, period_month)[1]

    if period_type == "kati":
        start_day = MID_MONTH_START_DAY
    else:
        start_day = days_in_month - (len(cars) - 1)

    day = max(1, min(days_in_month, start_day + index))
    candidate = date(period_year, period_month, day)

    service_dates = _service_dates(car_id)
    while candidate in service_dates:
        candidate += timedelta(days=1)
    return candidate


def predict_for_car(car, today=None):
    """Next due allowance period for a car, counted forward from its most recent
    DriverAllowance. A car with no history yet defaults to this month's mid-month
    slot. A period left unconfirmed for OVERDUE_SKIP_DAYS days or more is skipped
    forward to the next one (kati -> mwisho -> next month's kati -> ...), so a
    driver who misses a slot doesn't just accumulate an ever-larger overdue count
    against a payment that was never given."""
    today = today or date.today()
    last = _last_allowance(car.id)

    if last is None:
        period_year, period_month, period_type = today.year, today.month, "kati"
    else:
        period_year, period_month, period_type = _next_period(last.period_year, last.period_month, last.period_type)

    while True:
        scheduled_date = scheduled_date_for(car.id, period_year, period_month, period_type)
        days_remaining = (scheduled_date - today).days
        if days_remaining > -OVERDUE_SKIP_DAYS:
            break
        period_year, period_month, period_type = _next_period(period_year, period_month, period_type)

    if days_remaining < 0:
        status = "overdue"
    elif days_remaining == 0:
        status = "due"
    elif days_remaining <= 3:
        status = "due_soon"
    else:
        status = "upcoming"

    return {
        "car": car,
        "last": last,
        "period_year": period_year,
        "period_month": period_month,
        "period_type": period_type,
        "period_label": PERIOD_LABELS[period_type],
        "scheduled_date": scheduled_date,
        "days_remaining": days_remaining,
        "status": status,
        # Total debt outstanding on the car, regardless of repayment type --
        # display-only, so staff see the full picture here even though only
        # 'allowance'-type debt is actually drawn down by give_allowance below.
        "debt_balance": car_debt_balance(car.id),
        "projected_amount": car.daily_target,
    }


def allowance_predictions(cars=None, today=None):
    """Prediction rows for every eligible car, most urgent (due/overdue) first."""
    cars = cars if cars is not None else _allowance_cars()
    rows = [predict_for_car(c, today=today) for c in cars]
    rows.sort(key=lambda r: r["scheduled_date"])
    return rows


def give_allowance(car, period_year, period_month, period_type, given_date):
    """Confirms a driver allowance for a car/period: records the DriverAllowance,
    redirects it into a DebtPayment first if the car owes a debt, and auto-clears
    that day's shortfall (the driver keeps the collection instead of depositing it,
    so the day always shows short unless explained)."""
    amount = car.daily_target
    # Only debts flagged 'allowance' are drawn down here -- a 'collection'-type
    # debt is repaid through the driver's daily collections instead (see
    # utils.apply_collection_debt_repayment), so it must not also come out of
    # the allowance.
    debt_balance = car_debt_balance(car.id, return_type="allowance", as_of=given_date)
    applied_to_debt = min(amount, debt_balance) if debt_balance > 0 else 0.0
    cash_amount = amount - applied_to_debt
    driver_name = car.driver.name if car.driver else "-"
    period_label = PERIOD_LABELS[period_type]

    allowance = DriverAllowance(
        car_id=car.id,
        period_year=period_year,
        period_month=period_month,
        period_type=period_type,
        date=given_date,
        amount=amount,
        applied_to_debt=applied_to_debt,
    )
    db.session.add(allowance)

    if applied_to_debt > 0:
        payment = DebtPayment(
            date=given_date,
            car_id=car.id,
            amount=applied_to_debt,
            return_type="allowance",
            description=f"Malipo ya deni kutoka posho ya dereva {driver_name} ({period_label})",
        )
        db.session.add(payment)
        db.session.flush()
        allowance.debt_payment_id = payment.id

    if applied_to_debt > 0 and cash_amount > 0:
        description = (
            f"Posho ya dereva {driver_name} ({period_label}) - {amount:,.0f}: "
            f"{applied_to_debt:,.0f} imelipa deni la gari, {cash_amount:,.0f} amechukua dereva bila kuweka akaunti."
        )
    elif applied_to_debt > 0:
        description = (
            f"Posho ya dereva {driver_name} ({period_label}) - {amount:,.0f} yote imetumika kulipa deni la gari."
        )
    else:
        description = (
            f"Posho ya dereva {driver_name} ({period_label}) - {amount:,.0f} amechukua dereva bila kuweka akaunti."
        )
    allowance.note = description

    clearance = ShortfallClearance.query.filter_by(car_id=car.id, date=given_date).first()
    if clearance:
        clearance.description = description
    else:
        db.session.add(ShortfallClearance(car_id=car.id, date=given_date, description=description))

    db.session.commit()
    return allowance


def reverse_allowance(allowance):
    """Undo a confirmed allowance: removes the linked debt payment (if any) and
    the shortfall clearance it created for that day, then deletes the record."""
    debt_payment = allowance.debt_payment
    clearance = ShortfallClearance.query.filter_by(car_id=allowance.car_id, date=allowance.date).first()

    allowance.debt_payment_id = None
    db.session.delete(allowance)
    db.session.flush()

    if debt_payment:
        db.session.delete(debt_payment)
    if clearance:
        db.session.delete(clearance)
    db.session.commit()
