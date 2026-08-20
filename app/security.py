from functools import wraps

from flask import current_app, flash, redirect, request, url_for


def require_action_code(f):
    """Guard for every create/update/delete POST: a shared confirmation code must be
    submitted correctly, independent of whether the user is logged in. Checked purely
    server-side so the code never appears in any page's HTML/JS source."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.method == "POST":
            submitted = (request.form.get("action_code") or "").strip()
            expected = current_app.config["ACTION_CODE"]
            if not submitted or submitted != expected:
                flash("Msimbo wa uthibitisho si sahihi. Hakuna kilichobadilishwa.", "danger")
                return redirect(request.referrer or url_for("dashboard.index"))
        return f(*args, **kwargs)

    return wrapper
