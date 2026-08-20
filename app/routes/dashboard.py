from datetime import date

from flask import Blueprint, render_template

from ..models import CollectionTransaction, ConsumptionEntry
from ..utils import car_month_matrix, debt_balances, month_bounds, monthly_trend, period_totals

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    today = date.today()
    month_start, month_end = month_bounds(today.year, today.month)

    month_totals = period_totals(month_start, month_end)
    all_time_totals = period_totals()
    balances = debt_balances()
    trend = monthly_trend(6)
    contribution_matrix = car_month_matrix(6)

    recent_transactions = (
        CollectionTransaction.query.order_by(
            CollectionTransaction.date.desc(), CollectionTransaction.id.desc()
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
        trend=trend,
        recent_transactions=recent_transactions,
        recent_consumption=recent_consumption,
        contribution_matrix=contribution_matrix,
        today=today,
    )
