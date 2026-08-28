from datetime import date, timedelta

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _

from ..export_excel import (
    build_collections_excel,
    build_consumption_excel,
    build_service_items_excel,
    build_shortfalls_excel,
    build_summary_excel,
)
from ..export_pdf import (
    build_collections_pdf,
    build_consumption_pdf,
    build_service_items_pdf,
    build_shortfalls_pdf,
    build_summary_pdf,
)
from ..extensions import db
from ..models import Car, ExpenseCategory, ServiceItemCategory, ShortfallClearance
from ..report_data import (
    collections_rows,
    consumption_rows,
    service_category_totals,
    service_item_price_history,
    service_item_rows,
    summary_rows,
)
from ..security import get_current_user, require_permission
from ..sms import can_send, send_and_log
from ..utils import (
    LAUNCH_DATE,
    car_achievement_rates,
    category_totals,
    debt_monthly_trend,
    driver_totals,
    paginate,
    parse_date,
    period_totals,
    shortfall_report,
    shortfall_streaks,
)

PER_PAGE = 20

bp = Blueprint("reports", __name__)


def _range():
    start = parse_date(request.args.get("start"), LAUNCH_DATE)
    end = parse_date(request.args.get("end"), date.today())
    return start, end


@bp.route("/")
def index():
    start, end = _range()
    car_id = request.args.get("car_id", type=int)
    category_id = request.args.get("category_id", type=int)

    s_rows, s_totals = summary_rows(start, end)
    c_rows, c_total = collections_rows(start, end, car_id)
    m_rows, m_total = consumption_rows(start, end, car_id, category_id)

    return render_template(
        "reports/index.html",
        start=start,
        end=end,
        car_id=car_id,
        category_id=category_id,
        cars=Car.query.order_by(Car.code).all(),
        categories=ExpenseCategory.query.order_by(ExpenseCategory.name).all(),
        summary_rows=s_rows,
        summary_totals=s_totals,
        collection_rows=c_rows,
        collection_total=c_total,
        consumption_rows=m_rows,
        consumption_total=m_total,
    )


@bp.route("/summary.xlsx")
def summary_xlsx():
    start, end = _range()
    rows, totals = summary_rows(start, end)
    buf = build_summary_excel(rows, totals, start, end)
    return _send(buf, f"muhtasari_{start}_{end}.xlsx", "xlsx")


@bp.route("/summary.pdf")
def summary_pdf():
    start, end = _range()
    rows, totals = summary_rows(start, end)
    buf = build_summary_pdf(rows, totals, start, end)
    return _send(buf, f"muhtasari_{start}_{end}.pdf", "pdf")


@bp.route("/collections.xlsx")
def collections_xlsx():
    start, end = _range()
    car_id = request.args.get("car_id", type=int)
    rows, total = collections_rows(start, end, car_id)
    buf = build_collections_excel(rows, total, start, end)
    return _send(buf, f"makusanyo_{start}_{end}.xlsx", "xlsx")


@bp.route("/collections.pdf")
def collections_pdf():
    start, end = _range()
    car_id = request.args.get("car_id", type=int)
    rows, total = collections_rows(start, end, car_id)
    buf = build_collections_pdf(rows, total, start, end)
    return _send(buf, f"makusanyo_{start}_{end}.pdf", "pdf")


@bp.route("/consumption.xlsx")
def consumption_xlsx():
    start, end = _range()
    car_id = request.args.get("car_id", type=int)
    category_id = request.args.get("category_id", type=int)
    rows, total = consumption_rows(start, end, car_id, category_id)
    buf = build_consumption_excel(rows, total, start, end)
    return _send(buf, f"matumizi_{start}_{end}.xlsx", "xlsx")


@bp.route("/consumption.pdf")
def consumption_pdf():
    start, end = _range()
    car_id = request.args.get("car_id", type=int)
    category_id = request.args.get("category_id", type=int)
    rows, total = consumption_rows(start, end, car_id, category_id)
    buf = build_consumption_pdf(rows, total, start, end)
    return _send(buf, f"matumizi_{start}_{end}.pdf", "pdf")


def _service_filters():
    car_id = request.args.get("car_id", type=int)
    category_id = request.args.get("category_id", type=int)
    status = request.args.get("status") or None
    return car_id, category_id, status


@bp.route("/service")
def service_index():
    start, end = _range()
    car_id, category_id, status = _service_filters()

    rows, total = service_item_rows(start, end, car_id, category_id, status)
    cat_totals = service_category_totals(rows)
    price_history = service_item_price_history(rows)

    return render_template(
        "reports/service.html",
        start=start,
        end=end,
        car_id=car_id,
        category_id=category_id,
        status=status,
        cars=Car.query.order_by(Car.code).all(),
        item_categories=ServiceItemCategory.query.order_by(ServiceItemCategory.name).all(),
        rows=rows,
        total=total,
        category_totals=cat_totals,
        price_history=price_history,
    )


@bp.route("/service.xlsx")
def service_xlsx():
    start, end = _range()
    car_id, category_id, status = _service_filters()
    rows, total = service_item_rows(start, end, car_id, category_id, status)
    cat_totals = service_category_totals(rows)
    buf = build_service_items_excel(rows, total, cat_totals, start, end)
    return _send(buf, f"vipuri_huduma_{start}_{end}.xlsx", "xlsx")


@bp.route("/service.pdf")
def service_pdf():
    start, end = _range()
    car_id, category_id, status = _service_filters()
    rows, total = service_item_rows(start, end, car_id, category_id, status)
    cat_totals = service_category_totals(rows)
    buf = build_service_items_pdf(rows, total, cat_totals, start, end)
    return _send(buf, f"vipuri_huduma_{start}_{end}.pdf", "pdf")


@bp.route("/analytics")
def analytics():
    start, end = _range()
    car_totals = period_totals(start, end)
    achievement_rates = car_achievement_rates(start, end)
    achievement_by_car = {r["car"].id: r for r in achievement_rates}
    streaks = shortfall_streaks(start, end)
    driver_summary = driver_totals(start, end)
    category_summary = category_totals(start, end)
    debt_trend = debt_monthly_trend(start, end)

    return render_template(
        "reports/analytics.html",
        start=start,
        end=end,
        car_totals=car_totals,
        achievement_by_car=achievement_by_car,
        streaks=streaks,
        driver_summary=driver_summary,
        category_summary=category_summary,
        debt_trend=debt_trend,
    )


@bp.route("/streak-sms/<int:car_id>", methods=["POST"])
@require_permission("sms")
def send_streak_sms(car_id):
    start = parse_date(request.form.get("start"), LAUNCH_DATE)
    end = parse_date(request.form.get("end"), date.today())
    car = Car.query.get_or_404(car_id)

    streak_row = next((s for s in shortfall_streaks(start, end) if s["car"].id == car_id), None)
    if streak_row is None:
        flash(_("Gari %(code)s halina tatizo la siku mfululizo kwa sasa.", code=car.code), "danger")
        return redirect(url_for("reports.analytics", start=start.isoformat(), end=end.isoformat()))

    ok, reason = can_send(car)
    if not ok:
        flash(reason, "danger")
        return redirect(url_for("reports.analytics", start=start.isoformat(), end=end.isoformat()))

    streak_start = end - timedelta(days=streak_row["streak_days"] - 1)
    message = _(
        "Habari %(name)s, hujafikia lengo la siku kutoka %(start)s hadi %(end)s. "
        "Kama sio sahihi, tutaharifu.",
        name=car.driver.name,
        start=streak_start.strftime("%d-%m-%Y"),
        end=end.strftime("%d-%m-%Y"),
    )
    sent, error = send_and_log(car, "streak", message, get_current_user())
    if sent:
        flash(_("SMS ya tatizo imetumwa kwa dereva wa %(code)s.", code=car.code), "success")
    else:
        flash(error, "danger")
    return redirect(url_for("reports.analytics", start=start.isoformat(), end=end.isoformat()))


@bp.route("/shortfalls")
def shortfalls():
    start, end = _range()
    rows = shortfall_report(start, end)
    open_rows = [r for r in rows if not r["clearance"]]
    cleared_rows = [r for r in rows if r["clearance"]]

    open_rows, open_page, open_pages = paginate(open_rows, request.args.get("open_page", 1, type=int), PER_PAGE)
    cleared_rows, cleared_page, cleared_pages = paginate(
        cleared_rows, request.args.get("cleared_page", 1, type=int), PER_PAGE
    )

    return render_template(
        "reports/shortfalls.html",
        start=start,
        end=end,
        open_rows=open_rows,
        open_page=open_page,
        open_pages=open_pages,
        cleared_rows=cleared_rows,
        cleared_page=cleared_page,
        cleared_pages=cleared_pages,
    )


@bp.route("/shortfalls/clear", methods=["POST"])
def clear_shortfall():
    start = request.form.get("start", "")
    end = request.form.get("end", "")
    car_id = int(request.form["car_id"])
    shortfall_date = parse_date(request.form.get("date"))
    description = (request.form.get("description") or "").strip()

    if not description:
        flash(_("Weka maelezo ya upungufu kabla ya kufafanua."), "danger")
    elif not shortfall_date:
        flash(_("Tarehe si sahihi."), "danger")
    else:
        existing = ShortfallClearance.query.filter_by(car_id=car_id, date=shortfall_date).first()
        if existing:
            existing.description = description
        else:
            db.session.add(ShortfallClearance(car_id=car_id, date=shortfall_date, description=description))
        db.session.commit()
        flash(_("Upungufu umefafanuliwa."), "success")

    return redirect(url_for("reports.shortfalls", start=start, end=end))


@bp.route("/shortfalls.xlsx")
def shortfalls_xlsx():
    start, end = _range()
    rows = shortfall_report(start, end)
    buf = build_shortfalls_excel(rows, start, end)
    return _send(buf, f"upungufu_{start}_{end}.xlsx", "xlsx")


@bp.route("/shortfalls.pdf")
def shortfalls_pdf():
    start, end = _range()
    rows = shortfall_report(start, end)
    buf = build_shortfalls_pdf(rows, start, end)
    return _send(buf, f"upungufu_{start}_{end}.pdf", "pdf")


_MIME = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


def _send(buf, filename, kind):
    return Response(
        buf.read(),
        mimetype=_MIME[kind],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
