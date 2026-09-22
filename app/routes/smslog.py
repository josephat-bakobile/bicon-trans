from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _

from ..extensions import db
from ..models import Driver, SmsLog, SmsTopup
from ..security import get_current_user, require_permission
from ..sms import send_manual_sms
from ..utils import paginate, parse_date, sms_balance, validate_entry_date

bp = Blueprint("smslog", __name__)

PER_PAGE = 30


@bp.route("/")
def index():
    logs = SmsLog.query.order_by(SmsLog.created_at.desc(), SmsLog.id.desc()).all()
    logs, page, pages = paginate(logs, request.args.get("page", 1, type=int), PER_PAGE)
    topups = SmsTopup.query.order_by(SmsTopup.date.desc(), SmsTopup.id.desc()).limit(10).all()
    return render_template(
        "smslog/index.html", logs=logs, page=page, pages=pages, topups=topups, balance=sms_balance()
    )


@bp.route("/balance")
def balance():
    recent_topups = SmsTopup.query.order_by(SmsTopup.date.desc(), SmsTopup.id.desc()).limit(10).all()
    return render_template("smslog/balance.html", sms=sms_balance(), recent_sms_topups=recent_topups)


@bp.route("/compose")
def compose():
    drivers = Driver.query.filter_by(active=True).order_by(Driver.name).all()
    return render_template("smslog/compose.html", drivers=drivers, balance=sms_balance())


@bp.route("/compose/send", methods=["POST"])
@require_permission("sms")
def send_bulk():
    driver_ids = request.form.getlist("driver_ids", type=int)
    message = (request.form.get("message") or "").strip()

    if not driver_ids:
        flash(_("Chagua angalau dereva mmoja."), "danger")
        return redirect(url_for("smslog.compose"))
    if not message:
        flash(_("Andika ujumbe kwanza."), "danger")
        return redirect(url_for("smslog.compose"))

    drivers = Driver.query.filter(Driver.id.in_(driver_ids)).all()
    sent = 0
    failures = []
    for driver in drivers:
        ok, reason = send_manual_sms(driver, message, get_current_user())
        if ok:
            sent += 1
        else:
            failures.append(f"{driver.name}: {reason}")

    if sent:
        flash(_("SMS zimetumwa kwa madereva %(count)s.", count=sent), "success")
    if failures:
        flash(_("Imeshindwa kutuma kwa: %(list)s", list="; ".join(failures)), "danger")
    return redirect(url_for("smslog.compose"))


@bp.route("/topup", methods=["POST"])
@require_permission("sms")
def add_topup():
    next_url = request.form.get("next") or url_for("smslog.index")
    topup_date = parse_date(request.form.get("date"), date.today())
    amount = request.form.get("amount", type=int)
    note = (request.form.get("note") or "").strip() or None

    error = validate_entry_date(topup_date, _("Tarehe ya SMS"))
    if not error and (not amount or amount <= 0):
        error = _("Idadi ya SMS lazima iwe namba chanya.")

    if error:
        flash(error, "danger")
    else:
        db.session.add(
            SmsTopup(date=topup_date, amount=amount, note=note, added_by_id=get_current_user().id)
        )
        db.session.commit()
        flash(_("SMS %(amount)s zimeongezwa.", amount=f"{amount:,}"), "success")
    return redirect(next_url)
