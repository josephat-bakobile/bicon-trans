from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _

from ..extensions import db
from ..models import Permission, Role, Shop, User
from ..security import get_current_user, validate_password_strength

bp = Blueprint("admin", __name__)


@bp.route("/users")
def users_list():
    users = User.query.order_by(User.username).all()
    roles = Role.query.order_by(Role.name).all()
    return render_template("admin/users.html", users=users, roles=roles)


@bp.route("/users/new", methods=["POST"])
def users_new():
    username = (request.form.get("username") or "").strip()
    full_name = (request.form.get("full_name") or "").strip() or None
    password = request.form.get("password") or ""
    role_id = request.form.get("role_id")
    role = Role.query.get(role_id) if role_id else None

    password_error = validate_password_strength(password) if password else None

    if not username or not password or not role:
        flash(_("Jina la mtumiaji, nenosiri na jukumu vinahitajika."), "danger")
    elif password_error:
        flash(password_error, "danger")
    elif User.query.filter_by(username=username).first() or Shop.query.filter_by(username=username).first():
        # Staff and shops share one login page (auth.login) and are told apart
        # only by which table's username matches, so a name can't be reused
        # across the two tables either.
        flash(_("Jina la mtumiaji '%(username)s' tayari linatumika.", username=username), "danger")
    else:
        user = User(username=username, full_name=full_name, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash(_("Mtumiaji '%(username)s' ameongezwa.", username=username), "success")
    return redirect(url_for("admin.users_list"))


@bp.route("/users/<int:user_id>/edit", methods=["POST"])
def users_edit(user_id):
    user = User.query.get_or_404(user_id)
    full_name = (request.form.get("full_name") or "").strip() or None
    role_id = request.form.get("role_id")
    role = Role.query.get(role_id) if role_id else None

    if not role:
        flash(_("Jukumu linahitajika."), "danger")
        return redirect(url_for("admin.users_list"))

    if user.role.is_super_admin and not role.is_super_admin:
        remaining = User.query.join(Role).filter(
            Role.is_super_admin.is_(True), User.id != user.id, User.active.is_(True)
        ).count()
        if remaining == 0:
            flash(_("Haiwezekani: huyu ndiye Msimamizi Mkuu pekee aliyebaki."), "danger")
            return redirect(url_for("admin.users_list"))

    user.full_name = full_name
    user.role = role
    db.session.commit()
    flash(_("Mtumiaji '%(username)s' amesasishwa.", username=user.username), "success")
    return redirect(url_for("admin.users_list"))


@bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
def users_reset_password(user_id):
    user = User.query.get_or_404(user_id)
    password = request.form.get("password") or ""
    password_error = validate_password_strength(password) if password else _("Nenosiri jipya linahitajika.")
    if password_error:
        flash(password_error, "danger")
    else:
        user.set_password(password)
        user.failed_attempts = 0
        user.locked_until = None
        db.session.commit()
        flash(_("Nenosiri la '%(username)s' limebadilishwa.", username=user.username), "success")
    return redirect(url_for("admin.users_list"))


@bp.route("/users/<int:user_id>/toggle", methods=["POST"])
def users_toggle(user_id):
    user = User.query.get_or_404(user_id)
    current = get_current_user()

    if user.id == current.id:
        flash(_("Huwezi kujizima mwenyewe."), "danger")
        return redirect(url_for("admin.users_list"))

    if user.active and user.role.is_super_admin:
        remaining = User.query.join(Role).filter(
            Role.is_super_admin.is_(True), User.id != user.id, User.active.is_(True)
        ).count()
        if remaining == 0:
            flash(_("Haiwezekani: huyu ndiye Msimamizi Mkuu pekee aliyebaki."), "danger")
            return redirect(url_for("admin.users_list"))

    user.active = not user.active
    db.session.commit()
    return redirect(url_for("admin.users_list"))


@bp.route("/shops")
def shops_list():
    shops = Shop.query.order_by(Shop.name).all()
    return render_template("admin/shops.html", shops=shops)


@bp.route("/shops/new", methods=["POST"])
def shops_new():
    name = (request.form.get("name") or "").strip()
    username = (request.form.get("username") or "").strip()
    phone = (request.form.get("phone") or "").strip() or None
    password = request.form.get("password") or ""

    password_error = validate_password_strength(password) if password else None

    if not name or not username or not password:
        flash(_("Jina la muuza, jina la mtumiaji na nenosiri vinahitajika."), "danger")
    elif password_error:
        flash(password_error, "danger")
    elif Shop.query.filter_by(username=username).first() or User.query.filter_by(username=username).first():
        flash(_("Jina la mtumiaji '%(username)s' tayari linatumika.", username=username), "danger")
    else:
        shop = Shop(name=name, username=username, phone=phone)
        shop.set_password(password)
        db.session.add(shop)
        db.session.commit()
        flash(_("Muuza '%(name)s' ameongezwa.", name=name), "success")
    return redirect(url_for("admin.shops_list"))


@bp.route("/shops/<int:shop_id>/edit", methods=["POST"])
def shops_edit(shop_id):
    shop = Shop.query.get_or_404(shop_id)
    name = (request.form.get("name") or "").strip()
    phone = (request.form.get("phone") or "").strip() or None

    if not name:
        flash(_("Jina la muuza linahitajika."), "danger")
    else:
        shop.name = name
        shop.phone = phone
        db.session.commit()
        flash(_("Muuza '%(name)s' amesasishwa.", name=shop.name), "success")
    return redirect(url_for("admin.shops_list"))


@bp.route("/shops/<int:shop_id>/reset-password", methods=["POST"])
def shops_reset_password(shop_id):
    shop = Shop.query.get_or_404(shop_id)
    password = request.form.get("password") or ""
    password_error = validate_password_strength(password) if password else _("Nenosiri jipya linahitajika.")
    if password_error:
        flash(password_error, "danger")
    else:
        shop.set_password(password)
        shop.failed_attempts = 0
        shop.locked_until = None
        db.session.commit()
        flash(_("Nenosiri la '%(username)s' limebadilishwa.", username=shop.username), "success")
    return redirect(url_for("admin.shops_list"))


@bp.route("/shops/<int:shop_id>/toggle", methods=["POST"])
def shops_toggle(shop_id):
    shop = Shop.query.get_or_404(shop_id)
    shop.active = not shop.active
    db.session.commit()
    return redirect(url_for("admin.shops_list"))


@bp.route("/roles")
def roles_list():
    roles = Role.query.order_by(Role.name).all()
    permissions = Permission.query.order_by(Permission.name).all()
    return render_template("admin/roles.html", roles=roles, permissions=permissions)


@bp.route("/roles/new", methods=["POST"])
def roles_new():
    name = (request.form.get("name") or "").strip()
    perm_codes = request.form.getlist("permissions")

    if not name:
        flash(_("Jina la jukumu linahitajika."), "danger")
    elif Role.query.filter_by(name=name).first():
        flash(_("Jukumu '%(name)s' tayari lipo.", name=name), "danger")
    else:
        role = Role(name=name)
        role.permissions = Permission.query.filter(Permission.code.in_(perm_codes)).all()
        db.session.add(role)
        db.session.commit()
        flash(_("Jukumu '%(name)s' limeongezwa.", name=name), "success")
    return redirect(url_for("admin.roles_list"))


@bp.route("/roles/<int:role_id>/edit", methods=["POST"])
def roles_edit(role_id):
    role = Role.query.get_or_404(role_id)
    if role.is_super_admin:
        flash(_("Jukumu la Msimamizi Mkuu lina ruhusa zote kila wakati na haliwezi kubadilishwa."), "danger")
        return redirect(url_for("admin.roles_list"))

    name = (request.form.get("name") or "").strip()
    perm_codes = request.form.getlist("permissions")

    if not name:
        flash(_("Jina la jukumu linahitajika."), "danger")
        return redirect(url_for("admin.roles_list"))

    existing = Role.query.filter(Role.name == name, Role.id != role.id).first()
    if existing:
        flash(_("Jukumu '%(name)s' tayari lipo.", name=name), "danger")
        return redirect(url_for("admin.roles_list"))

    role.name = name
    role.permissions = Permission.query.filter(Permission.code.in_(perm_codes)).all()
    db.session.commit()
    flash(_("Jukumu '%(name)s' limesasishwa.", name=name), "success")
    return redirect(url_for("admin.roles_list"))


@bp.route("/roles/<int:role_id>/delete", methods=["POST"])
def roles_delete(role_id):
    role = Role.query.get_or_404(role_id)
    if role.is_super_admin:
        flash(_("Jukumu la Msimamizi Mkuu haliwezi kufutwa."), "danger")
    elif User.query.filter_by(role_id=role.id).count() > 0:
        flash(_("Jukumu '%(name)s' bado linatumiwa na watumiaji, haliwezi kufutwa.", name=role.name), "danger")
    else:
        db.session.delete(role)
        db.session.commit()
        flash(_("Jukumu '%(name)s' limefutwa.", name=role.name), "success")
    return redirect(url_for("admin.roles_list"))
