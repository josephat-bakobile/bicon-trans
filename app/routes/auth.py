from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from ..models import User

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = User.query.filter_by(username=username).first()
        if user and user.active and user.check_password(password):
            session.clear()
            session.permanent = True
            session["user_id"] = user.id
            next_url = request.args.get("next") or url_for("dashboard.index")
            return redirect(next_url)
        flash("Jina la mtumiaji au nenosiri si sahihi.", "danger")
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
