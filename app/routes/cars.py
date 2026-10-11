from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _

from ..extensions import db
from ..models import Car, CarCollectionPause, Driver
from ..security import get_current_user
from ..utils import active_pause_for_car, parse_date, validate_service_date

bp = Blueprint("cars", __name__)


def _assignable_driver_options(cars):
    """(car, options, open_pause) rows for the cars list -- options being the
    drivers each car's dropdown should offer: every unassigned active driver,
    plus the car's own current driver (so it stays selected even though it's
    technically "taken"); open_pause (see active_pause_for_car) drives whether
    the row shows the pause form or the resume form."""
    unassigned = Driver.query.filter_by(active=True, car=None).order_by(Driver.name).all()
    rows = []
    for car in cars:
        options = list(unassigned)
        if car.driver and car.driver not in options:
            options.append(car.driver)
        options.sort(key=lambda d: d.name)
        rows.append((car, options, active_pause_for_car(car)))
    return rows


def _assign_driver(car, driver_id):
    """None on success, else a Swahili error message. Enforces one driver -> at
    most one car by refusing to steal a driver who's already assigned elsewhere."""
    if not driver_id:
        car.driver_id = None
        return None
    driver = Driver.query.get(driver_id)
    if driver is None:
        return _("Dereva huyo hayupo.")
    if driver.car is not None and driver.car.id != car.id:
        return _("Dereva %(name)s tayari anaendesha gari %(code)s.", name=driver.name, code=driver.car.code)
    car.driver_id = driver.id
    return None


@bp.route("/")
def list_view():
    cars = Car.query.order_by(Car.code).all()
    unassigned_drivers = Driver.query.filter_by(active=True, car=None).order_by(Driver.name).all()
    return render_template(
        "cars/list.html",
        car_rows=_assignable_driver_options(cars),
        unassigned_drivers=unassigned_drivers,
        today=date.today().isoformat(),
    )


@bp.route("/new", methods=["POST"])
def new():
    code = (request.form.get("code") or "").strip().upper()
    name = (request.form.get("name") or "").strip() or None
    driver_id = request.form.get("driver_id", type=int)
    daily_target = float(request.form.get("daily_target") or 0)
    if not code:
        flash(_("Namba ya gari (code) inahitajika."), "danger")
    elif Car.query.filter_by(code=code).first():
        flash(_("Gari %(code)s tayari lipo.", code=code), "danger")
    else:
        car = Car(code=code, name=name, daily_target=daily_target)
        error = _assign_driver(car, driver_id)
        if error:
            flash(error, "danger")
        else:
            db.session.add(car)
            db.session.commit()
            flash(_("Gari %(code)s limeongezwa.", code=code), "success")
    return redirect(url_for("cars.list_view"))


@bp.route("/<int:car_id>/toggle", methods=["POST"])
def toggle(car_id):
    car = Car.query.get_or_404(car_id)
    car.active = not car.active
    db.session.commit()
    return redirect(url_for("cars.list_view"))


@bp.route("/<int:car_id>/target", methods=["POST"])
def update_target(car_id):
    car = Car.query.get_or_404(car_id)
    car.daily_target = float(request.form.get("daily_target") or 0)
    db.session.commit()
    flash(_("Kiasi cha lengo la siku la %(code)s kimesasishwa.", code=car.code), "success")
    return redirect(url_for("cars.list_view"))


@bp.route("/<int:car_id>/driver", methods=["POST"])
def update_driver(car_id):
    car = Car.query.get_or_404(car_id)
    driver_id = request.form.get("driver_id", type=int)
    error = _assign_driver(car, driver_id)
    if error:
        flash(error, "danger")
    else:
        db.session.commit()
        flash(_("Dereva wa %(code)s amesasishwa.", code=car.code), "success")
    return redirect(url_for("cars.list_view"))


@bp.route("/<int:car_id>/pause", methods=["POST"])
def pause(car_id):
    """Opens a CarCollectionPause so this car stops generating collection
    shortfalls from start_date onward, until resume() closes it -- e.g. the car
    is broken down or off the road for a stretch and isn't expected to collect
    toward its daily_target in the meantime. Always requires a reason."""
    car = Car.query.get_or_404(car_id)
    reason = (request.form.get("reason") or "").strip()
    start_date = parse_date(request.form.get("start_date")) or date.today()
    if active_pause_for_car(car):
        flash(_("Gari %(code)s tayari limesimamishwa kukusanya.", code=car.code), "danger")
    elif not reason:
        flash(_("Sababu ya kusimamisha gari kukusanya inahitajika."), "danger")
    else:
        error = validate_service_date(start_date, _("Tarehe ya kusimamisha"))
        if error:
            flash(error, "danger")
        else:
            db.session.add(
                CarCollectionPause(
                    car_id=car.id,
                    start_date=start_date,
                    reason=reason,
                    created_by_id=get_current_user().id,
                )
            )
            db.session.commit()
            flash(
                _(
                    "Gari %(code)s limesimamishwa kukusanya kuanzia %(date)s.",
                    code=car.code,
                    date=start_date.strftime("%d-%m-%Y"),
                ),
                "success",
            )
    return redirect(url_for("cars.list_view"))


@bp.route("/<int:car_id>/resume", methods=["POST"])
def resume(car_id):
    """Closes this car's open CarCollectionPause as of end_date, so collection
    shortfalls resume being tracked from the next day onward."""
    car = Car.query.get_or_404(car_id)
    open_pause = active_pause_for_car(car)
    if not open_pause:
        flash(_("Gari %(code)s halijasimamishwa kukusanya.", code=car.code), "danger")
        return redirect(url_for("cars.list_view"))

    end_date = parse_date(request.form.get("end_date")) or date.today()
    resume_reason = (request.form.get("resume_reason") or "").strip() or None
    error = validate_service_date(end_date, _("Tarehe ya kuanza tena"))
    if error:
        flash(error, "danger")
    elif end_date < open_pause.start_date:
        flash(_("Tarehe ya kuanza tena haiwezi kuwa kabla ya tarehe ya kusimamisha."), "danger")
    else:
        open_pause.end_date = end_date
        open_pause.resume_reason = resume_reason
        open_pause.resumed_by_id = get_current_user().id
        open_pause.resumed_at = datetime.utcnow()
        db.session.commit()
        flash(
            _(
                "Gari %(code)s limeanza kukusanya tena kuanzia %(date)s.",
                code=car.code,
                date=end_date.strftime("%d-%m-%Y"),
            ),
            "success",
        )
    return redirect(url_for("cars.list_view"))
