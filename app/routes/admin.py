from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import Permission, Role, User
from ..security import get_current_user

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

    if not username or not password or not role:
        flash("Jina la mtumiaji, nenosiri na jukumu vinahitajika.", "danger")
    elif User.query.filter_by(username=username).first():
        flash(f"Mtumiaji '{username}' tayari yupo.", "danger")
    else:
        user = User(username=username, full_name=full_name, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash(f"Mtumiaji '{username}' ameongezwa.", "success")
    return redirect(url_for("admin.users_list"))


@bp.route("/users/<int:user_id>/edit", methods=["POST"])
def users_edit(user_id):
    user = User.query.get_or_404(user_id)
    full_name = (request.form.get("full_name") or "").strip() or None
    role_id = request.form.get("role_id")
    role = Role.query.get(role_id) if role_id else None

    if not role:
        flash("Jukumu linahitajika.", "danger")
        return redirect(url_for("admin.users_list"))

    if user.role.is_super_admin and not role.is_super_admin:
        remaining = User.query.join(Role).filter(
            Role.is_super_admin.is_(True), User.id != user.id, User.active.is_(True)
        ).count()
        if remaining == 0:
            flash("Haiwezekani: huyu ndiye Msimamizi Mkuu pekee aliyebaki.", "danger")
            return redirect(url_for("admin.users_list"))

    user.full_name = full_name
    user.role = role
    db.session.commit()
    flash(f"Mtumiaji '{user.username}' amesasishwa.", "success")
    return redirect(url_for("admin.users_list"))


@bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
def users_reset_password(user_id):
    user = User.query.get_or_404(user_id)
    password = request.form.get("password") or ""
    if len(password) < 4:
        flash("Nenosiri jipya linahitajika (angalau herufi 4).", "danger")
    else:
        user.set_password(password)
        db.session.commit()
        flash(f"Nenosiri la '{user.username}' limebadilishwa.", "success")
    return redirect(url_for("admin.users_list"))


@bp.route("/users/<int:user_id>/toggle", methods=["POST"])
def users_toggle(user_id):
    user = User.query.get_or_404(user_id)
    current = get_current_user()

    if user.id == current.id:
        flash("Huwezi kujizima mwenyewe.", "danger")
        return redirect(url_for("admin.users_list"))

    if user.active and user.role.is_super_admin:
        remaining = User.query.join(Role).filter(
            Role.is_super_admin.is_(True), User.id != user.id, User.active.is_(True)
        ).count()
        if remaining == 0:
            flash("Haiwezekani: huyu ndiye Msimamizi Mkuu pekee aliyebaki.", "danger")
            return redirect(url_for("admin.users_list"))

    user.active = not user.active
    db.session.commit()
    return redirect(url_for("admin.users_list"))


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
        flash("Jina la jukumu linahitajika.", "danger")
    elif Role.query.filter_by(name=name).first():
        flash(f"Jukumu '{name}' tayari lipo.", "danger")
    else:
        role = Role(name=name)
        role.permissions = Permission.query.filter(Permission.code.in_(perm_codes)).all()
        db.session.add(role)
        db.session.commit()
        flash(f"Jukumu '{name}' limeongezwa.", "success")
    return redirect(url_for("admin.roles_list"))


@bp.route("/roles/<int:role_id>/edit", methods=["POST"])
def roles_edit(role_id):
    role = Role.query.get_or_404(role_id)
    if role.is_super_admin:
        flash("Jukumu la Msimamizi Mkuu lina ruhusa zote kila wakati na haliwezi kubadilishwa.", "danger")
        return redirect(url_for("admin.roles_list"))

    name = (request.form.get("name") or "").strip()
    perm_codes = request.form.getlist("permissions")

    if not name:
        flash("Jina la jukumu linahitajika.", "danger")
        return redirect(url_for("admin.roles_list"))

    existing = Role.query.filter(Role.name == name, Role.id != role.id).first()
    if existing:
        flash(f"Jukumu '{name}' tayari lipo.", "danger")
        return redirect(url_for("admin.roles_list"))

    role.name = name
    role.permissions = Permission.query.filter(Permission.code.in_(perm_codes)).all()
    db.session.commit()
    flash(f"Jukumu '{name}' limesasishwa.", "success")
    return redirect(url_for("admin.roles_list"))


@bp.route("/roles/<int:role_id>/delete", methods=["POST"])
def roles_delete(role_id):
    role = Role.query.get_or_404(role_id)
    if role.is_super_admin:
        flash("Jukumu la Msimamizi Mkuu haliwezi kufutwa.", "danger")
    elif User.query.filter_by(role_id=role.id).count() > 0:
        flash(f"Jukumu '{role.name}' bado linatumiwa na watumiaji, haliwezi kufutwa.", "danger")
    else:
        db.session.delete(role)
        db.session.commit()
        flash(f"Jukumu '{role.name}' limefutwa.", "success")
    return redirect(url_for("admin.roles_list"))
