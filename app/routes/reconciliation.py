from datetime import date

from flask import Blueprint, Response, render_template, request

from ..export_excel import build_reconciliation_excel
from ..export_pdf import build_reconciliation_pdf
from ..report_data import reconciliation_rows
from ..utils import parse_date

bp = Blueprint("reconciliation", __name__)


def _range():
    today = date.today()
    start = parse_date(request.args.get("start"), today.replace(day=1))
    end = parse_date(request.args.get("end"), today)
    return start, end


@bp.route("/")
def index():
    start, end = _range()
    rows, total = reconciliation_rows(start, end)
    return render_template("reconciliation/index.html", start=start, end=end, rows=rows, total=total)


@bp.route("/export.xlsx")
def export_xlsx():
    start, end = _range()
    rows, total = reconciliation_rows(start, end)
    buf = build_reconciliation_excel(rows, total, start, end)
    return Response(
        buf.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="upatanisho_{start}_{end}.xlsx"'},
    )


@bp.route("/export.pdf")
def export_pdf():
    start, end = _range()
    rows, total = reconciliation_rows(start, end)
    buf = build_reconciliation_pdf(rows, total, start, end)
    return Response(
        buf.read(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="upatanisho_{start}_{end}.pdf"'},
    )
