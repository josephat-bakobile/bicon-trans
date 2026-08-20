import os
from datetime import timedelta

from flask import Flask, redirect, request, session, url_for

from .extensions import db


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "bicon-trans-dev-key")
    app.config["SITE_PASSWORD"] = os.environ.get("SITE_PASSWORD", "bicontrans2026")
    app.config["ACTION_CODE"] = os.environ.get("ACTION_CODE", "BAKOBILE")
    app.permanent_session_lifetime = timedelta(hours=8)

    db_path = os.environ.get("DATABASE_PATH", os.path.join(os.getcwd(), "data", "bicon_trans.db"))
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    with app.app_context():
        from . import models  # noqa: F401

        db.create_all()
        _migrate_schema()
        _seed_defaults()
        _run_legacy_import()

    from .routes.auth import bp as auth_bp
    from .routes.dashboard import bp as dashboard_bp
    from .routes.collections import bp as collections_bp
    from .routes.consumption import bp as consumption_bp
    from .routes.debts import bp as debts_bp
    from .routes.cars import bp as cars_bp
    from .routes.categories import bp as categories_bp
    from .routes.reports import bp as reports_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(collections_bp, url_prefix="/collections")
    app.register_blueprint(consumption_bp, url_prefix="/consumption")
    app.register_blueprint(debts_bp, url_prefix="/debts")
    app.register_blueprint(cars_bp, url_prefix="/cars")
    app.register_blueprint(categories_bp, url_prefix="/categories")
    app.register_blueprint(reports_bp, url_prefix="/reports")

    app.jinja_env.filters["money"] = lambda v: f"{(v or 0):,.0f}"

    @app.before_request
    def _require_login():
        if request.endpoint in (None, "auth.login", "static"):
            return None
        if not session.get("logged_in"):
            return redirect(url_for("auth.login", next=request.path))
        return None

    return app


def _migrate_schema():
    """Lightweight in-place migrations for columns added after the first release."""
    from sqlalchemy import text

    cols = [row[1] for row in db.session.execute(text("PRAGMA table_info(collection_transactions)")).fetchall()]
    if "trans_no" not in cols:
        db.session.execute(text("ALTER TABLE collection_transactions ADD COLUMN trans_no VARCHAR(30)"))
        db.session.commit()

        from .models import CollectionTransaction

        for txn in CollectionTransaction.query.order_by(CollectionTransaction.id).all():
            txn.trans_no = f"TRX-{txn.id:05d}"
        db.session.commit()

        db.session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_collection_transactions_trans_no "
                "ON collection_transactions (trans_no)"
            )
        )
        db.session.commit()


def _seed_defaults():
    from .models import Car, ExpenseCategory

    if Car.query.count() == 0:
        for code in ["DES", "DDS", "AAX", "CJK"]:
            db.session.add(Car(code=code))
    if ExpenseCategory.query.count() == 0:
        db.session.add(ExpenseCategory(name="MATUMIZI"))
    db.session.commit()


def _run_legacy_import():
    from .legacy_import import import_legacy

    xlsx_path = os.environ.get("LEGACY_XLSX_PATH")
    if not xlsx_path:
        return
    result = import_legacy(xlsx_path)
    print(f"[legacy_import] {result}", flush=True)
