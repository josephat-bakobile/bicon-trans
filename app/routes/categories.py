from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _

from ..extensions import db
from ..models import ExpenseCategory, ServiceItemCategory

bp = Blueprint("categories", __name__)


@bp.route("/")
def list_view():
    categories = ExpenseCategory.query.order_by(ExpenseCategory.name).all()
    item_categories = ServiceItemCategory.query.order_by(ServiceItemCategory.name).all()
    return render_template("categories/list.html", categories=categories, item_categories=item_categories)


@bp.route("/new", methods=["POST"])
def new():
    name = (request.form.get("name") or "").strip().upper()
    if not name:
        flash(_("Jina la aina ya matumizi linahitajika."), "danger")
    elif ExpenseCategory.query.filter_by(name=name).first():
        flash(_("Aina %(name)s tayari ipo.", name=name), "danger")
    else:
        db.session.add(ExpenseCategory(name=name))
        db.session.commit()
        flash(_("Aina %(name)s imeongezwa.", name=name), "success")
    return redirect(url_for("categories.list_view"))


@bp.route("/<int:category_id>/toggle", methods=["POST"])
def toggle(category_id):
    category = ExpenseCategory.query.get_or_404(category_id)
    category.active = not category.active
    db.session.commit()
    return redirect(url_for("categories.list_view"))


@bp.route("/<int:category_id>/toggle_service", methods=["POST"])
def toggle_service(category_id):
    category = ExpenseCategory.query.get_or_404(category_id)
    category.is_service = not category.is_service
    db.session.commit()
    return redirect(url_for("categories.list_view"))


@bp.route("/items/new", methods=["POST"])
def new_item_category():
    name = (request.form.get("name") or "").strip().upper()
    if not name:
        flash(_("Jina la aina ya kipuri/kipengele linahitajika."), "danger")
    elif ServiceItemCategory.query.filter_by(name=name).first():
        flash(_("Aina %(name)s tayari ipo.", name=name), "danger")
    else:
        db.session.add(ServiceItemCategory(name=name))
        db.session.commit()
        flash(_("Aina %(name)s imeongezwa.", name=name), "success")
    return redirect(url_for("categories.list_view"))


@bp.route("/items/<int:category_id>/toggle", methods=["POST"])
def toggle_item_category(category_id):
    category = ServiceItemCategory.query.get_or_404(category_id)
    category.active = not category.active
    db.session.commit()
    return redirect(url_for("categories.list_view"))


@bp.route("/items/<int:category_id>/edit", methods=["POST"])
def edit_item_category(category_id):
    category = ServiceItemCategory.query.get_or_404(category_id)
    name = (request.form.get("name") or "").strip().upper()
    if not name:
        flash(_("Jina la aina ya kipuri/kipengele linahitajika."), "danger")
    elif ServiceItemCategory.query.filter(ServiceItemCategory.name == name, ServiceItemCategory.id != category.id).first():
        flash(_("Aina %(name)s tayari ipo.", name=name), "danger")
    else:
        category.name = name
        db.session.commit()
        flash(_("Aina imesasishwa kuwa %(name)s.", name=name), "success")
    return redirect(url_for("categories.list_view"))
