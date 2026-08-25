from datetime import date

from flask import Blueprint, render_template

from ..car_service import service_predictions, shop_dashboard
from ..models import CollectionTransaction, ConsumptionEntry
from ..renewals import dashboard_alerts
from ..utils import car_month_matrix, debt_balances, month_bounds, monthly_trend, period_totals, shortfall_totals

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    today = date.today()
    month_start, month_end = month_bounds(today.year, today.month)

    month_totals = period_totals(month_start, month_end)
    all_time_totals = period_totals()
    balances = debt_balances()
    shortfalls = shortfall_totals()
    trend = monthly_trend(6)
    contribution_matrix = car_month_matrix(6)
    service_alerts = [p for p in service_predictions() if p["status"] in ("overdue", "due_soon")]
    renewal_alerts = dashboard_alerts()
    shop_summary = shop_dashboard()

    recent_transactions = (
        CollectionTransaction.query.order_by(
            CollectionTransaction.transaction_date.desc(), CollectionTransaction.id.desc()
        )
        .limit(8)
        .all()
    )
    recent_consumption = (
        ConsumptionEntry.query.order_by(ConsumptionEntry.date.desc(), ConsumptionEntry.id.desc())
        .limit(8)
        .all()
    )

    return render_template(
        "dashboard.html",
        month_totals=month_totals,
        all_time_totals=all_time_totals,
        balances=balances,
        shortfalls=shortfalls,
        trend=trend,
        recent_transactions=recent_transactions,
        recent_consumption=recent_consumption,
        contribution_matrix=contribution_matrix,
        service_alerts=service_alerts,
        renewal_alerts=renewal_alerts,
        shop_summary=shop_summary,
        today=today,
    )
