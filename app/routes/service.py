from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _

from ..car_service import predict_for_car, service_predictions, shop_dashboard
from ..extensions import db
from ..models import (
    Car,
    CarService,
    CarServiceItem,
    ConsumptionEntry,
    ExpenseCategory,
    ServiceItemCategory,
    Shop,
    ShopServicePayment,
    ShortfallClearance,
)
from ..security import get_current_user, require_permission
from ..sms import can_send, send_and_log
from ..utils import parse_date, validate_service_date

bp = Blueprint("service", __name__)


def _apply_cost(service, car_id, cost, category_id, service_date, description):
    """Keep the linked ConsumptionEntry (if any) in sync with the ticket's total
    cost: create/update/remove it so it always mirrors the confirmed ticket."""
    if cost > 0:
        if service.consumption_entry_id:
            entry = service.consumption_entry
            entry.date = service_date
            entry.car_id = car_id
            entry.category_id = category_id
            entry.amount = cost
            entry.description = description or "Huduma ya gari"
        else:
            entry = ConsumptionEntry(
                date=service_date,
                car_id=car_id,
                category_id=category_id,
                amount=cost,
                description=description or "Huduma ya gari",
            )
            db.session.add(entry)
            db.session.flush()
            service.consumption_entry_id = entry.id
    elif service.consumption_entry_id:
        entry = service.consumption_entry
        service.consumption_entry_id = None
        db.session.flush()
        db.session.delete(entry)


def _sync_service_clearance(service, car, service_date):
    """Keeps the linked ShortfallClearance in sync with the service's car/date --
    a car doesn't collect on the day it's serviced, so that day is auto-explained
    the same way a driver-allowance day is (see driver_allowance.give_allowance)."""
    note = (
        f"Gari {car.code} lilikuwa kwenye huduma tarehe {service_date.strftime('%d-%m-%Y')}"
        f"{' (' + service.description + ')' if service.description else ''} "
        "- halikutegemewa kukusanya siku hiyo."
    )

    if service.shortfall_clearance_id:
        clearance = service.shortfall_clearance
        if clearance.car_id != car.id or clearance.date != service_date:
            clash = ShortfallClearance.query.filter(
                ShortfallClearance.car_id == car.id,
                ShortfallClearance.date == service_date,
                ShortfallClearance.id != clearance.id,
            ).first()
            if clash:
                service.shortfall_clearance_id = None
                db.session.flush()
                db.session.delete(clearance)
                clearance = clash
                service.shortfall_clearance_id = clearance.id
            else:
                clearance.car_id = car.id
                clearance.date = service_date
        clearance.description = note
        return

    existing = ShortfallClearance.query.filter_by(car_id=car.id, date=service_date).first()
    if existing:
        existing.description = note
        clearance = existing
    else:
        clearance = ShortfallClearance(car_id=car.id, date=service_date, description=note)
        db.session.add(clearance)
        db.session.flush()
    service.shortfall_clearance_id = clearance.id


@bp.route("/")
def index():
    car_id = request.args.get("car_id", type=int)

    predictions = service_predictions()

    q = CarService.query
    if car_id:
        q = q.filter(CarService.car_id == car_id)
    history = q.order_by(CarService.service_date.desc(), CarService.id.desc()).limit(30).all()

    return render_template(
        "service/index.html",
        predictions=predictions,
        history=history,
        cars=Car.query.order_by(Car.code).all(),
        shops=Shop.query.filter_by(active=True).order_by(Shop.name).all(),
        shop_dashboard=shop_dashboard(),
        car_id=car_id,
    )


@bp.route("/new", methods=["POST"])
def new():
    service_date = parse_date(request.form.get("service_date"), date.today())
    error = validate_service_date(service_date)
    car_id = int(request.form["car_id"])
    description = (request.form.get("description") or "").strip() or None
    shop_id = request.form.get("shop_id", type=int) or None

    if error:
        flash(error, "danger")
        return redirect(url_for("service.index"))

    car = Car.query.get_or_404(car_id)
    shop = Shop.query.get_or_404(shop_id) if shop_id else None
    service = CarService(
        car_id=car_id, service_date=service_date, description=description, status="open", shop_id=shop_id
    )
    db.session.add(service)
    db.session.flush()
    if shop is None:
        # Only a staff-logged service day means the car sat idle -- a ticket
        # opened for a vendor doesn't auto-excuse that day's collection.
        _sync_service_clearance(service, car, service_date)
    db.session.commit()
    if shop:
        flash(_("Tiketi imefunguliwa kwa muuza %(shop_name)s. Wanaweza kuongeza vipengele na kuwasilisha.", shop_name=shop.name), "success")
    else:
        flash(_("Tiketi ya huduma imefunguliwa. Ongeza vipengele (vipuri/gharama) kisha ufunge tiketi."), "success")
    return redirect(url_for("service.ticket_detail", service_id=service.id))


@bp.route("/<int:service_id>")
def ticket_detail(service_id):
    service = CarService.query.get_or_404(service_id)
    return render_template(
        "service/ticket.html",
        service=service,
        item_categories=ServiceItemCategory.query.filter_by(active=True).order_by(ServiceItemCategory.name).all(),
        expense_categories=ExpenseCategory.query.filter_by(active=True).order_by(ExpenseCategory.name).all(),
    )


@bp.route("/<int:service_id>/items/new", methods=["POST"])
def add_item(service_id):
    service = CarService.query.get_or_404(service_id)
    if service.shop_id:
        flash(_("Tiketi hii ni ya muuza -- vipengele vyake vinasimamiwa na muuza mwenyewe."), "danger")
        return redirect(url_for("service.ticket_detail", service_id=service.id))
    if not service.is_open:
        flash(_("Tiketi imefungwa -- huwezi kuongeza kipengele. Ifungue tena kwanza."), "danger")
        return redirect(url_for("service.ticket_detail", service_id=service.id))

    category_id = request.form.get("category_id", type=int)
    name = (request.form.get("name") or "").strip()
    quantity = float(request.form.get("quantity") or 1)
    unit_cost = float(request.form.get("unit_cost") or 0)
    note = (request.form.get("note") or "").strip() or None

    if not name:
        flash(_("Weka jina la kipengele (kipuri/gharama)."), "danger")
    elif not category_id:
        flash(_("Chagua aina ya kipengele."), "danger")
    elif quantity <= 0:
        flash(_("Idadi lazima iwe zaidi ya sifuri."), "danger")
    elif unit_cost < 0:
        flash(_("Bei ya kitengo si sahihi."), "danger")
    else:
        db.session.add(
            CarServiceItem(
                service_id=service.id,
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

    return redirect(url_for("service.ticket_detail", service_id=service.id))


@bp.route("/<int:service_id>/items/<int:item_id>/delete", methods=["POST"])
def delete_item(service_id, item_id):
    service = CarService.query.get_or_404(service_id)
    item = CarServiceItem.query.filter_by(id=item_id, service_id=service.id).first_or_404()
    if service.shop_id:
        flash(_("Tiketi hii ni ya muuza -- vipengele vyake vinasimamiwa na muuza mwenyewe."), "danger")
        return redirect(url_for("service.ticket_detail", service_id=service.id))
    if not service.is_open:
        flash(_("Tiketi imefungwa -- huwezi kufuta kipengele. Ifungue tena kwanza."), "danger")
    else:
        db.session.delete(item)
        db.session.commit()
        flash(_("Kipengele kimefutwa."), "info")
    return redirect(url_for("service.ticket_detail", service_id=service.id))


@bp.route("/<int:service_id>/confirm", methods=["POST"])
def confirm(service_id):
    service = CarService.query.get_or_404(service_id)
    if service.shop_id:
        flash(_("Tiketi ya muuza inafungwa kwa kulipa (rekodi malipo), siyo kwa kitufe hiki."), "danger")
        return redirect(url_for("service.ticket_detail", service_id=service.id))
    if not service.is_open:
        flash(_("Tiketi hii tayari imefungwa."), "danger")
        return redirect(url_for("service.ticket_detail", service_id=service.id))

    total = service.total_cost
    category_id = request.form.get("category_id", type=int)

    if total > 0 and not category_id:
        flash(_("Chagua aina ya matumizi itakayopokea gharama ya tiketi hii."), "danger")
        return redirect(url_for("service.ticket_detail", service_id=service.id))

    car = service.car
    _apply_cost(service, car.id, total, category_id, service.service_date, service.description)
    service.status = "confirmed"
    service.confirmed_at = datetime.utcnow()
    service.confirmed_by_id = get_current_user().id
    db.session.commit()
    flash(_("Tiketi imefungwa. Gharama ya %(total)s imepelekwa kwenye matumizi ya gari %(car_code)s.", total=f"{total:,.0f}", car_code=car.code), "success")
    return redirect(url_for("service.ticket_detail", service_id=service.id))


@bp.route("/<int:service_id>/reopen", methods=["POST"])
def reopen(service_id):
    service = CarService.query.get_or_404(service_id)
    if service.shop_id:
        flash(_("Tiketi ya muuza inarudishwa kwa muuza kwa kitufe cha 'Rudisha kwa Muuza', siyo hiki."), "danger")
    elif service.is_open:
        flash(_("Tiketi hii tayari iko wazi."), "danger")
    else:
        service.status = "open"
        service.confirmed_at = None
        service.confirmed_by_id = None
        db.session.commit()
        flash(_("Tiketi imefunguliwa tena. Unaweza kuongeza/kufuta vipengele kisha kufunga tena."), "success")
    return redirect(url_for("service.ticket_detail", service_id=service.id))


@bp.route("/<int:service_id>/approve", methods=["POST"])
def approve(service_id):
    service = CarService.query.get_or_404(service_id)
    if not service.shop_id:
        flash(_("Tiketi hii siyo ya muuza."), "danger")
    elif not service.is_submitted:
        flash(_("Tiketi hii siyo katika hatua ya kuwasilishwa."), "danger")
    else:
        service.status = "approved"
        service.approved_at = datetime.utcnow()
        service.approved_by_id = get_current_user().id
        db.session.commit()
        flash(_("Tiketi imethibitishwa. Sasa unaweza kurekodi malipo. Haiwezi tena kurudishwa kwa muuza."), "success")
    return redirect(url_for("service.ticket_detail", service_id=service.id))


@bp.route("/<int:service_id>/return_to_shop", methods=["POST"])
def return_to_shop(service_id):
    service = CarService.query.get_or_404(service_id)
    if not service.shop_id:
        flash(_("Tiketi hii siyo ya muuza."), "danger")
    elif not service.is_submitted:
        flash(_("Tiketi hii haiwezi tena kurudishwa kwa muuza -- tayari imethibitishwa."), "danger")
    else:
        service.status = "open"
        db.session.commit()
        flash(_("Tiketi imerudishwa kwa muuza %(shop_name)s kwa marekebisho. Wataweza kuongeza/kufuta vipengele kisha kuwasilisha tena.", shop_name=service.shop.name), "success")
    return redirect(url_for("service.ticket_detail", service_id=service.id))


@bp.route("/<int:service_id>/payments/new", methods=["POST"])
def add_payment(service_id):
    service = CarService.query.get_or_404(service_id)
    if not service.shop_id:
        flash(_("Tiketi hii siyo ya muuza."), "danger")
        return redirect(url_for("service.ticket_detail", service_id=service.id))
    if not service.is_approved:
        flash(_("Tiketi hii haijathibitishwa bado au tayari imelipwa kikamilifu."), "danger")
        return redirect(url_for("service.ticket_detail", service_id=service.id))

    payment_date = parse_date(request.form.get("date"), date.today())
    error = validate_service_date(payment_date)
    amount = float(request.form.get("amount") or 0)
    note = (request.form.get("note") or "").strip() or None
    category_id = service.payment_category_id or request.form.get("category_id", type=int)

    if error:
        flash(error, "danger")
    elif amount <= 0:
        flash(_("Kiasi cha malipo lazima kiwe zaidi ya sifuri."), "danger")
    elif amount > service.balance_due + 0.01:
        flash(_("Kiasi kinazidi baki linalodaiwa (%(balance)s).", balance=f"{service.balance_due:,.0f}"), "danger")
    elif not category_id:
        flash(_("Chagua aina ya matumizi kwa malipo haya (itatumika kwa malipo yote ya tiketi hii)."), "danger")
    else:
        if not service.payment_category_id:
            service.payment_category_id = category_id
        entry = ConsumptionEntry(
            date=payment_date,
            car_id=service.car_id,
            category_id=service.payment_category_id,
            amount=amount,
            description=f"Malipo kwa {service.shop.name} - Tiketi #{service.id}" + (f" ({note})" if note else ""),
        )
        db.session.add(entry)
        db.session.flush()
        # Appended via the relationship (not db.session.add with a bare service_id)
        # so service.payments/paid_amount reflect it immediately below -- the
        # balance_due check above already lazy-loaded and cached that collection.
        service.payments.append(
            ShopServicePayment(
                amount=amount,
                date=payment_date,
                note=note,
                consumption_entry_id=entry.id,
                recorded_by_id=get_current_user().id,
            )
        )
        db.session.flush()
        if service.paid_amount >= service.total_cost:
            service.status = "confirmed"
            service.confirmed_at = datetime.utcnow()
            service.confirmed_by_id = get_current_user().id
            flash(_("Malipo ya %(amount)s yamerekodiwa. Tiketi imelipwa kikamilifu.", amount=f"{amount:,.0f}"), "success")
        else:
            flash(_("Malipo ya %(amount)s yamerekodiwa. Baki: %(balance)s.", amount=f"{amount:,.0f}", balance=f"{service.balance_due:,.0f}"), "success")
        db.session.commit()

    return redirect(url_for("service.ticket_detail", service_id=service.id))


@bp.route("/<int:service_id>/payments/<int:payment_id>/delete", methods=["POST"])
def delete_payment(service_id, payment_id):
    service = CarService.query.get_or_404(service_id)
    payment = ShopServicePayment.query.filter_by(id=payment_id, service_id=service.id).first_or_404()

    entry = payment.consumption_entry
    was_confirmed = service.status == "confirmed"
    db.session.delete(payment)
    if entry:
        db.session.delete(entry)
    db.session.flush()
    if was_confirmed and service.paid_amount < service.total_cost:
        service.status = "approved"
        service.confirmed_at = None
        service.confirmed_by_id = None
    db.session.commit()
    flash(_("Malipo yamefutwa."), "info")
    return redirect(url_for("service.ticket_detail", service_id=service.id))


@bp.route("/<int:service_id>/edit", methods=["GET", "POST"])
def edit(service_id):
    service = CarService.query.get_or_404(service_id)
    if service.shop_id:
        flash(_("Tiketi hii ni ya muuza -- taarifa zake zinasimamiwa na muuza mwenyewe."), "danger")
        return redirect(url_for("service.ticket_detail", service_id=service.id))
    if not service.is_open:
        flash(_("Tiketi iliyofungwa haiwezi kuhaririwa. Ifungue tena kwanza."), "danger")
        return redirect(url_for("service.ticket_detail", service_id=service.id))

    cars = Car.query.order_by(Car.code).all()

    if request.method == "POST":
        service_date = parse_date(request.form.get("service_date"), service.service_date)
        error = validate_service_date(service_date)
        car_id = int(request.form["car_id"])
        description = (request.form.get("description") or "").strip() or None

        if error:
            flash(error, "danger")
            return render_template("service/edit.html", service=service, cars=cars)

        car = Car.query.get_or_404(car_id)
        service.service_date = service_date
        service.car_id = car_id
        service.description = description
        _sync_service_clearance(service, car, service_date)
        db.session.commit()
        flash(_("Tiketi ya huduma imesasishwa."), "success")
        return redirect(url_for("service.ticket_detail", service_id=service.id))

    return render_template("service/edit.html", service=service, cars=cars)


@bp.route("/<int:service_id>/delete", methods=["POST"])
def delete(service_id):
    service = CarService.query.get_or_404(service_id)
    linked = service.consumption_entry
    clearance = service.shortfall_clearance
    payment_entries = [p.consumption_entry for p in service.payments if p.consumption_entry]
    db.session.delete(service)
    if linked:
        db.session.delete(linked)
    if clearance:
        db.session.delete(clearance)
    for entry in payment_entries:
        db.session.delete(entry)
    db.session.commit()
    flash(_("Tiketi ya huduma imefutwa."), "info")
    return redirect(url_for("service.index"))


@bp.route("/car/<int:car_id>/interval", methods=["POST"])
def update_interval(car_id):
    car = Car.query.get_or_404(car_id)
    car.service_interval_days = int(request.form.get("service_interval_days") or 20)
    db.session.commit()
    flash(_("Muda wa huduma wa %(car_code)s umesasishwa.", car_code=car.code), "success")
    return redirect(url_for("service.index"))


@bp.route("/car/<int:car_id>/sms", methods=["POST"])
@require_permission("sms")
def send_service_sms(car_id):
    car = Car.query.get_or_404(car_id)
    prediction = predict_for_car(car)
    next_url = request.form.get("next") or url_for("service.index")

    if prediction["status"] not in ("overdue", "due_soon"):
        flash(_("Gari %(car_code)s halihitaji huduma kwa sasa.", car_code=car.code), "danger")
        return redirect(next_url)

    ok, reason = can_send(car)
    if not ok:
        flash(reason, "danger")
        return redirect(next_url)

    if prediction["status"] == "overdue":
        timing = f"lilipaswa kufanyiwa huduma tarehe {prediction['due_date'].strftime('%d-%m-%Y')} (limechelewa)"
    else:
        timing = f"linahitaji huduma tarehe {prediction['due_date'].strftime('%d-%m-%Y')} (siku {prediction['days_remaining']} zijazo)"
    message = (
        f"Habari {car.driver.name}, gari {car.code} {timing}. "
        f"Tafadhali panga huduma haraka. - BICON TRANS"
    )
    sent, error = send_and_log(car, "service", message, get_current_user())
    if sent:
        flash(_("SMS ya huduma imetumwa kwa dereva wa %(car_code)s.", car_code=car.code), "success")
    else:
        flash(error, "danger")
    return redirect(next_url)
