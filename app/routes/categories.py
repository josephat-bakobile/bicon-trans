from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import ExpenseCategory

bp = Blueprint("categories", __name__)


@bp.route("/")
def list_view():
    categories = ExpenseCategory.query.order_by(ExpenseCategory.name).all()
    return render_template("categories/list.html", categories=categories)


@bp.route("/new", methods=["POST"])
def new():
    name = (request.form.get("name") or "").strip().upper()
    if not name:
        flash("Jina la aina ya matumizi linahitajika.", "danger")
    elif ExpenseCategory.query.filter_by(name=name).first():
        flash(f"Aina {name} tayari ipo.", "danger")
    else:
        db.session.add(ExpenseCategory(name=name))
        db.session.commit()
        flash(f"Aina {name} imeongezwa.", "success")
    return redirect(url_for("categories.list_view"))


@bp.route("/<int:category_id>/toggle", methods=["POST"])
def toggle(category_id):
    category = ExpenseCategory.query.get_or_404(category_id)
    category.active = not category.active
    db.session.commit()
    return redirect(url_for("categories.list_view"))
