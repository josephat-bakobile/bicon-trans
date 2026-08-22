from functools import wraps

from flask import flash, g, redirect, session, url_for


def get_current_user():
    """Loads and caches (per-request, via g) the User for the logged-in session,
    or None if there isn't one / the account was deactivated after login."""
    if "user" not in g:
        from .models import User

        user = None
        user_id = session.get("user_id")
        if user_id is not None:
            user = User.query.get(user_id)
            if user is not None and not user.active:
                user = None
        g.user = user
    return g.user


def require_permission(code):
    """Guard for an individual view when blueprint-level PERMISSION_MAP checking
    (see app/__init__.py) isn't granular enough."""

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if not user or not user.has_permission(code):
                flash("Huna ruhusa ya kufikia ukurasa huu.", "danger")
                return redirect(url_for("dashboard.index"))
            return f(*args, **kwargs)

        return wrapper

    return decorator
