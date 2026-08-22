from datetime import date, timedelta

from .models import Car, CarDocument, DocumentType

URGENT_DAYS = 7
DUE_SOON_DAYS = 30


def compute_expire_date(start_date):
    """A renewal period runs exactly one year: expires the day before its
    anniversary (e.g. start 22-08-2026 -> expire 21-08-2027)."""
    try:
        anniversary = start_date.replace(year=start_date.year + 1)
    except ValueError:
        # start_date is Feb 29 on a leap year and next year isn't one.
        anniversary = start_date.replace(year=start_date.year + 1, day=28)
    return anniversary - timedelta(days=1)


def remaining_label(days_remaining):
    """Human Swahili label for the time left, coarsest unit first."""
    if days_remaining < 0:
        return f"Imepitiliza siku {abs(days_remaining)}"
    if days_remaining == 0:
        return "Inaisha leo"

    months, rem = divmod(days_remaining, 30)
    weeks, rem_days = divmod(rem, 7)

    parts = []
    if months:
        parts.append(f"miezi {months}" if months > 1 else "mwezi 1")
    if weeks:
        parts.append(f"wiki {weeks}")
    if rem_days and not months:
        parts.append(f"siku {rem_days}")
    if not parts:
        parts.append(f"siku {days_remaining}")
    return ", ".join(parts) + " zimebaki"


def _status(days_remaining):
    if days_remaining < 0:
        return "expired"
    if days_remaining <= URGENT_DAYS:
        return "urgent"
    if days_remaining <= DUE_SOON_DAYS:
        return "due_soon"
    return "ok"


def latest_document(car_id, document_type_id):
    return (
        CarDocument.query.filter_by(car_id=car_id, document_type_id=document_type_id)
        .order_by(CarDocument.start_date.desc(), CarDocument.id.desc())
        .first()
    )


def renewal_predictions(cars=None, document_types=None, today=None):
    """One row per (active car, active document type), most urgent first.
    Types never renewed for a car sort last."""
    today = today or date.today()
    cars = cars if cars is not None else Car.query.filter_by(active=True).order_by(Car.code).all()
    document_types = (
        document_types
        if document_types is not None
        else DocumentType.query.filter_by(active=True).order_by(DocumentType.name).all()
    )

    rows = []
    for car in cars:
        for doc_type in document_types:
            last = latest_document(car.id, doc_type.id)
            if last is None:
                rows.append(
                    {
                        "car": car,
                        "document_type": doc_type,
                        "document": None,
                        "days_remaining": None,
                        "status": "no_baseline",
                        "label": "Haijawahi kufanyiwa upya",
                    }
                )
                continue
            days_remaining = (last.expire_date - today).days
            rows.append(
                {
                    "car": car,
                    "document_type": doc_type,
                    "document": last,
                    "days_remaining": days_remaining,
                    "status": _status(days_remaining),
                    "label": remaining_label(days_remaining),
                }
            )

    rows.sort(key=lambda r: (r["days_remaining"] is None, r["days_remaining"]))
    return rows


def dashboard_alerts(today=None):
    """Rows needing urgent dashboard attention: already expired or expiring
    within URGENT_DAYS with no newer renewal on file."""
    return [r for r in renewal_predictions(today=today) if r["status"] in ("expired", "urgent")]
