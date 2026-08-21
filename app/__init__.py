import os
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, redirect, request, session, url_for

from .extensions import db

# Passenger/cPanel (and any WSGI host that isn't Docker) does not source a shell
# environment for us, so .env is loaded explicitly here. Real environment variables
# set by the host (e.g. cPanel's "Setup Python App" UI) always win — load_dotenv()
# never overwrites a variable that's already set.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


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
    from .routes.reconciliation import bp as reconciliation_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(collections_bp, url_prefix="/collections")
    app.register_blueprint(consumption_bp, url_prefix="/consumption")
    app.register_blueprint(debts_bp, url_prefix="/debts")
    app.register_blueprint(cars_bp, url_prefix="/cars")
    app.register_blueprint(categories_bp, url_prefix="/categories")
    app.register_blueprint(reports_bp, url_prefix="/reports")
    app.register_blueprint(reconciliation_bp, url_prefix="/reconciliation")

    app.jinja_env.filters["money"] = lambda v: f"{(v or 0):,.0f}"

    from .utils import MAX_BACKDATE_DAYS, transaction_locked

    app.jinja_env.globals["transaction_locked"] = transaction_locked

    @app.context_processor
    def _inject_date_bounds():
        today = date.today()
        return {
            "today_iso": today.isoformat(),
            "min_entry_date_iso": (today - timedelta(days=MAX_BACKDATE_DAYS)).isoformat(),
        }

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

    car_cols = [row[1] for row in db.session.execute(text("PRAGMA table_info(cars)")).fetchall()]
    if "daily_target" not in car_cols:
        db.session.execute(text("ALTER TABLE cars ADD COLUMN daily_target FLOAT NOT NULL DEFAULT 0"))
        db.session.commit()
    if "driver_name" not in car_cols:
        db.session.execute(text("ALTER TABLE cars ADD COLUMN driver_name VARCHAR(100)"))
        db.session.commit()

    txn_cols = [row[1] for row in db.session.execute(text("PRAGMA table_info(collection_transactions)")).fetchall()]
    if "transaction_date" not in txn_cols and "date" in txn_cols:
        db.session.execute(text("ALTER TABLE collection_transactions RENAME COLUMN date TO transaction_date"))
        db.session.commit()

    line_cols = [row[1] for row in db.session.execute(text("PRAGMA table_info(collection_lines)")).fetchall()]
    if "collection_date" not in line_cols:
        db.session.execute(text("ALTER TABLE collection_lines ADD COLUMN collection_date DATE"))
        db.session.commit()

        db.session.execute(
            text(
                "UPDATE collection_lines SET collection_date = ("
                "SELECT transaction_date FROM collection_transactions "
                "WHERE collection_transactions.id = collection_lines.transaction_id"
                ")"
            )
        )
        db.session.commit()

    # Heals orphaned collection_lines left behind by a pre-fix bug where a bulk
    # delete on collection_transactions skipped the ORM cascade. Safe to run every
    # startup: a line only matches here if its parent transaction no longer exists.
    orphaned = db.session.execute(
        text(
            "DELETE FROM collection_lines WHERE transaction_id NOT IN "
            "(SELECT id FROM collection_transactions)"
        )
    )
    if orphaned.rowcount:
        print(f"[migrate] removed {orphaned.rowcount} orphaned collection_lines row(s)", flush=True)
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
