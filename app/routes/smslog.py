from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _

from ..extensions import db
from ..models import SmsLog, SmsTopup
from ..security import get_current_user, require_permission
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
