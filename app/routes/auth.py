from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = request.form.get("password") or ""
        if password == current_app.config["SITE_PASSWORD"]:
            session.permanent = True
            session["logged_in"] = True
            next_url = request.args.get("next") or url_for("dashboard.index")
            return redirect(next_url)
        flash("Nenosiri si sahihi.", "danger")
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
