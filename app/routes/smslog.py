from flask import Blueprint, render_template, request

from ..models import SmsLog
from ..utils import paginate

bp = Blueprint("smslog", __name__)

PER_PAGE = 30


@bp.route("/")
def index():
    logs = SmsLog.query.order_by(SmsLog.created_at.desc(), SmsLog.id.desc()).all()
    logs, page, pages = paginate(logs, request.args.get("page", 1, type=int), PER_PAGE)
    return render_template("smslog/index.html", logs=logs, page=page, pages=pages)
