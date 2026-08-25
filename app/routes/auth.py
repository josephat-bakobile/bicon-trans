from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_babel import gettext as _

from ..extensions import db
from ..models import Shop, User
from ..security import (
    get_current_shop,
    get_current_user,
    is_locked,
    register_failed_login,
    register_successful_login,
    validate_password_strength,
)

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    """Single login page for both staff and shops -- tries a staff User first,
    then a Shop, and routes each to its own home/session domain (session["user_id"]
    vs session["shop_id"]) so the rest of the app can tell them apart."""
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        next_url = request.args.get("next")

        user = User.query.filter_by(username=username).first()
        if user and user.active:
            if is_locked(user):
                flash(_("Akaunti hii imefungwa kwa muda kutokana na majaribio mengi yasiyofanikiwa. Jaribu tena baadaye."), "danger")
                return render_template("login.html")
            if user.check_password(password):
                register_successful_login(user)
                db.session.commit()
                session.clear()
                session.permanent = True
                session["user_id"] = user.id
                session["lang"] = user.language
                return redirect(next_url or url_for("dashboard.index"))
            register_failed_login(user)
            db.session.commit()
            flash(_("Jina la mtumiaji au nenosiri si sahihi."), "danger")
            return render_template("login.html")

        shop = Shop.query.filter_by(username=username).first()
        if shop and shop.active:
            if is_locked(shop):
                flash(_("Akaunti hii imefungwa kwa muda kutokana na majaribio mengi yasiyofanikiwa. Jaribu tena baadaye."), "danger")
                return render_template("login.html")
            if shop.check_password(password):
                register_successful_login(shop)
                db.session.commit()
                session.clear()
                session.permanent = True
                session["shop_id"] = shop.id
                session["lang"] = shop.language
                return redirect(next_url or url_for("shop_portal.index"))
            register_failed_login(shop)
            db.session.commit()
            flash(_("Jina la mtumiaji au nenosiri si sahihi."), "danger")
            return render_template("login.html")

        flash(_("Jina la mtumiaji au nenosiri si sahihi."), "danger")
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/lang/<code>", methods=["POST"])
def set_language(code):
    """Sets the UI language for the current session, and persists it on the
    logged-in account (User or Shop) if there is one -- so it's remembered
    next time without the visitor having to pick it again."""
    if code not in ("sw", "en"):
        code = "sw"
    session["lang"] = code

    user = get_current_user()
    if user:
        user.language = code
        db.session.commit()
    else:
        shop = get_current_shop()
        if shop:
            shop.language = code
            db.session.commit()

    return redirect(request.referrer or url_for("auth.login"))


@bp.route("/account/password", methods=["GET", "POST"])
def change_password():
    """Self-service password change for a logged-in staff User."""
    user = get_current_user()
    if not user:
        flash(_("Tafadhali ingia kwanza."), "danger")
        return redirect(url_for("auth.login", next=request.path))

    if request.method == "POST":
        current_password = request.form.get("current_password") or ""
        new_password = request.form.get("new_password") or ""
        confirm_password = request.form.get("confirm_password") or ""

        if not user.check_password(current_password):
            flash(_("Nenosiri la sasa si sahihi."), "danger")
        elif new_password != confirm_password:
            flash(_("Nenosiri jipya na uthibitisho wake havifanani."), "danger")
        else:
            error = validate_password_strength(new_password)
            if error:
                flash(error, "danger")
            else:
                user.set_password(new_password)
                db.session.commit()
                flash(_("Nenosiri lako limebadilishwa."), "success")
                return redirect(url_for("dashboard.index"))

    return render_template("account/password.html")
