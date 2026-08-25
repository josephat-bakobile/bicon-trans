import re
from datetime import datetime, timedelta
from functools import wraps

from flask import flash, g, redirect, request, session, url_for
from flask_babel import gettext as _

# Shared by User and Shop logins (both carry failed_attempts/locked_until).
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def is_locked(account):
    return account.locked_until is not None and account.locked_until > datetime.utcnow()


def register_failed_login(account):
    """Bumps the failed-attempt counter and locks the account out for
    LOCKOUT_MINUTES once MAX_FAILED_ATTEMPTS is reached. Caller must commit."""
    account.failed_attempts = (account.failed_attempts or 0) + 1
    if account.failed_attempts >= MAX_FAILED_ATTEMPTS:
        account.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)


def register_successful_login(account):
    account.failed_attempts = 0
    account.locked_until = None


def validate_password_strength(raw_password):
    """Returns a Swahili error message if raw_password is too weak, else None."""
    if len(raw_password) < 8:
        return _("Nenosiri linahitaji angalau herufi 8.")
    if not re.search(r"[A-Za-z]", raw_password):
        return _("Nenosiri linahitaji angalau herufi moja ya alfabeti.")
    if not re.search(r"[0-9]", raw_password):
        return _("Nenosiri linahitaji angalau namba moja.")
    return None


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


def get_current_shop():
    """Loads and caches (per-request, via g) the Shop for the logged-in shop
    portal session -- a completely separate auth domain from staff Users, keyed
    off session["shop_id"] instead of session["user_id"]."""
    if "shop" not in g:
        from .models import Shop

        shop = None
        shop_id = session.get("shop_id")
        if shop_id is not None:
            shop = Shop.query.get(shop_id)
            if shop is not None and not shop.active:
                shop = None
        g.shop = shop
    return g.shop


def require_shop_login(f):
    """Guard for shop-portal views. Staff and shops share one login page
    (auth.login), which routes each to their own session domain -- there's no
    separate shop_portal.login anymore."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        if not get_current_shop():
            flash("Tafadhali ingia kwanza.", "danger")
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)

    return wrapper
