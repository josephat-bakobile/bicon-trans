from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _

from ..extensions import db
from ..models import CarService, CarServiceItem, ServiceItemCategory
from ..security import get_current_shop, require_shop_login, validate_password_strength

bp = Blueprint("shop_portal", __name__)


@bp.route("/password", methods=["GET", "POST"])
@require_shop_login
def change_password():
    """Self-service password change for a logged-in shop (third-party) account."""
    shop = get_current_shop()

    if request.method == "POST":
        current_password = request.form.get("current_password") or ""
        new_password = request.form.get("new_password") or ""
        confirm_password = request.form.get("confirm_password") or ""

        if not shop.check_password(current_password):
            flash(_("Nenosiri la sasa si sahihi."), "danger")
        elif new_password != confirm_password:
            flash(_("Nenosiri jipya na uthibitisho wake havifanani."), "danger")
        else:
            error = validate_password_strength(new_password)
            if error:
                flash(error, "danger")
            else:
                shop.set_password(new_password)
                db.session.commit()
                flash(_("Nenosiri lako limebadilishwa."), "success")
                return redirect(url_for("shop_portal.index"))

    return render_template("shop/password.html")


def _own_ticket_or_404(service_id):
    shop = get_current_shop()
    return CarService.query.filter_by(id=service_id, shop_id=shop.id).first_or_404()


@bp.route("/")
@require_shop_login
def index():
    shop = get_current_shop()
    tickets = (
        CarService.query.filter_by(shop_id=shop.id)
        .order_by(CarService.service_date.desc(), CarService.id.desc())
        .all()
    )
    active_count = sum(1 for t in tickets if t.is_open or t.is_submitted)
    unpaid_total = sum(t.balance_due for t in tickets if t.is_submitted)
    return render_template(
        "shop/index.html",
        tickets=tickets,
        active_count=active_count,
        unpaid_total=unpaid_total,
    )


@bp.route("/<int:service_id>")
@require_shop_login
def ticket_detail(service_id):
    ticket = _own_ticket_or_404(service_id)
    return render_template(
        "shop/ticket.html",
        service=ticket,
        item_categories=ServiceItemCategory.query.filter_by(active=True).order_by(ServiceItemCategory.name).all(),
    )


@bp.route("/<int:service_id>/items/new", methods=["POST"])
@require_shop_login
def add_item(service_id):
    ticket = _own_ticket_or_404(service_id)
    if not ticket.is_open:
        flash(_("Tiketi imewasilishwa -- huwezi kuongeza kipengele."), "danger")
        return redirect(url_for("shop_portal.ticket_detail", service_id=ticket.id))

    category_id = request.form.get("category_id", type=int)
    new_category_name = (request.form.get("new_category_name") or "").strip().upper()
    name = (request.form.get("name") or "").strip()
    quantity = float(request.form.get("quantity") or 1)
    unit_cost = float(request.form.get("unit_cost") or 0)
    note = (request.form.get("note") or "").strip() or None

    if new_category_name:
        # Not every part/charge category will have been registered by the
        # office ahead of time -- a shop can add one on the fly here (reused,
        # not duplicated, if another shop already typed the same name).
        category = ServiceItemCategory.query.filter_by(name=new_category_name).first()
        if category is None:
            category = ServiceItemCategory(name=new_category_name)
            db.session.add(category)
            db.session.flush()
        category_id = category.id

    if not name:
        flash(_("Weka jina la kipengele (kipuri/gharama)."), "danger")
    elif not category_id:
        flash(_("Chagua aina ya kipengele, au andika aina mpya."), "danger")
    elif quantity <= 0:
        flash(_("Idadi lazima iwe zaidi ya sifuri."), "danger")
    elif unit_cost < 0:
        flash(_("Bei ya kitengo si sahihi."), "danger")
    else:
        db.session.add(
            CarServiceItem(
                service_id=ticket.id,
                category_id=category_id,
                name=name,
                quantity=quantity,
                unit_cost=unit_cost,
                cost=quantity * unit_cost,
                note=note,
            )
        )
        db.session.commit()
        flash(_("Kipengele '%(name)s' kimeongezwa.", name=name), "success")

    return redirect(url_for("shop_portal.ticket_detail", service_id=ticket.id))


@bp.route("/<int:service_id>/items/<int:item_id>/delete", methods=["POST"])
@require_shop_login
def delete_item(service_id, item_id):
    ticket = _own_ticket_or_404(service_id)
    item = CarServiceItem.query.filter_by(id=item_id, service_id=ticket.id).first_or_404()
    if not ticket.is_open:
        flash(_("Tiketi imewasilishwa -- huwezi kufuta kipengele."), "danger")
    else:
        db.session.delete(item)
        db.session.commit()
        flash(_("Kipengele kimefutwa."), "info")
    return redirect(url_for("shop_portal.ticket_detail", service_id=ticket.id))


@bp.route("/<int:service_id>/submit", methods=["POST"])
@require_shop_login
def submit(service_id):
    ticket = _own_ticket_or_404(service_id)
    if not ticket.is_open:
        flash(_("Tiketi hii tayari imewasilishwa."), "danger")
    elif not ticket.items:
        flash(_("Ongeza angalau kipengele kimoja kabla ya kuwasilisha."), "danger")
    else:
        ticket.status = "submitted"
        db.session.commit()
        flash(_("Tiketi imewasilishwa. Ofisi itakulipa hivi karibuni."), "success")
    return redirect(url_for("shop_portal.ticket_detail", service_id=ticket.id))
