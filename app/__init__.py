import os
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, flash, redirect, request, url_for

from .extensions import db
from .security import get_current_user

# One permission code per admin-gated blueprint; dashboard and auth need no entry
# since every logged-in user may reach them. Kept next to create_app() (rather than
# in security.py) since it's really routing config, not an auth primitive.
PERMISSION_MAP = {
    "collections": "collections",
    "reconciliation": "reconciliation",
    "consumption": "consumption",
    "debts": "debts",
    "allowances": "allowances",
    "cars": "cars",
    "drivers": "cars",
    "service": "service",
    "renewals": "renewals",
    "categories": "categories",
    "reports": "reports",
    "admin": "users",
    "smslog": "sms",
}

# Passenger/cPanel (and any WSGI host that isn't Docker) does not source a shell
# environment for us, so .env is loaded explicitly here. Real environment variables
# set by the host (e.g. cPanel's "Setup Python App" UI) always win — load_dotenv()
# never overwrites a variable that's already set.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "bicon-trans-dev-key")
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
        _seed_driver_allowances()
        _seed_auth()
        _run_legacy_import()

    from .routes.auth import bp as auth_bp
    from .routes.dashboard import bp as dashboard_bp
    from .routes.collections import bp as collections_bp
    from .routes.consumption import bp as consumption_bp
    from .routes.debts import bp as debts_bp
    from .routes.allowances import bp as allowances_bp
    from .routes.cars import bp as cars_bp
    from .routes.drivers import bp as drivers_bp
    from .routes.categories import bp as categories_bp
    from .routes.reports import bp as reports_bp
    from .routes.reconciliation import bp as reconciliation_bp
    from .routes.service import bp as service_bp
    from .routes.renewals import bp as renewals_bp
    from .routes.admin import bp as admin_bp
    from .routes.smslog import bp as smslog_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(collections_bp, url_prefix="/collections")
    app.register_blueprint(consumption_bp, url_prefix="/consumption")
    app.register_blueprint(debts_bp, url_prefix="/debts")
    app.register_blueprint(allowances_bp, url_prefix="/allowances")
    app.register_blueprint(cars_bp, url_prefix="/cars")
    app.register_blueprint(drivers_bp, url_prefix="/drivers")
    app.register_blueprint(categories_bp, url_prefix="/categories")
    app.register_blueprint(reports_bp, url_prefix="/reports")
    app.register_blueprint(reconciliation_bp, url_prefix="/reconciliation")
    app.register_blueprint(service_bp, url_prefix="/service")
    app.register_blueprint(renewals_bp, url_prefix="/renewals")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(smslog_bp, url_prefix="/sms-log")

    app.jinja_env.filters["money"] = lambda v: f"{(v or 0):,.0f}"

    def _money_short(v):
        v = v or 0
        sign = "-" if v < 0 else ""
        v = abs(v)
        if v >= 1_000_000:
            s = round(v / 1_000_000, 1)
            if s == int(s):
                s = int(s)
            return f"{sign}{s}M"
        return f"{sign}{v:,.0f}"

    app.jinja_env.filters["money_short"] = _money_short

    from .sms import can_send as sms_can_send
    from .utils import MAX_BACKDATE_DAYS, transaction_locked

    app.jinja_env.globals["transaction_locked"] = transaction_locked
    app.jinja_env.globals["sms_ready"] = lambda car: sms_can_send(car)[0]

    @app.context_processor
    def _inject_date_bounds():
        today = date.today()
        return {
            "today_iso": today.isoformat(),
            "min_entry_date_iso": (today - timedelta(days=MAX_BACKDATE_DAYS)).isoformat(),
        }

    @app.context_processor
    def _inject_current_user():
        return {"current_user": get_current_user()}

    @app.before_request
    def _require_login():
        if request.endpoint in (None, "auth.login", "static"):
            return None
        user = get_current_user()
        if not user:
            return redirect(url_for("auth.login", next=request.path))
        required_permission = PERMISSION_MAP.get(request.blueprint)
        if required_permission and not user.has_permission(required_permission):
            flash("Huna ruhusa ya kufikia ukurasa huu.", "danger")
            return redirect(url_for("dashboard.index"))
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

    service_cols = [row[1] for row in db.session.execute(text("PRAGMA table_info(car_services)")).fetchall()]
    if "shortfall_clearance_id" not in service_cols:
        db.session.execute(
            text(
                "ALTER TABLE car_services ADD COLUMN shortfall_clearance_id INTEGER "
                "REFERENCES shortfall_clearances(id)"
            )
        )
        db.session.commit()

    car_cols = [row[1] for row in db.session.execute(text("PRAGMA table_info(cars)")).fetchall()]
    if "daily_target" not in car_cols:
        db.session.execute(text("ALTER TABLE cars ADD COLUMN daily_target FLOAT NOT NULL DEFAULT 0"))
        db.session.commit()
    if "service_interval_days" not in car_cols:
        db.session.execute(
            text("ALTER TABLE cars ADD COLUMN service_interval_days INTEGER NOT NULL DEFAULT 20")
        )
        db.session.commit()
    if "driver_id" not in car_cols:
        db.session.execute(text("ALTER TABLE cars ADD COLUMN driver_id INTEGER REFERENCES drivers(id)"))
        db.session.commit()
        db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_cars_driver_id ON cars (driver_id)"))
        db.session.commit()

    # One-time backfill: cars used to carry driver_name/driver_phone/sms_enabled
    # directly. Turn any existing values into real Driver rows (one driver, one
    # car) before dropping the old columns.
    if "driver_name" in car_cols:
        from .models import Driver

        legacy_rows = (
            db.session.execute(text("SELECT * FROM cars WHERE driver_name IS NOT NULL AND driver_name != ''"))
            .mappings()
            .fetchall()
        )
        for row in legacy_rows:
            driver_name = row["driver_name"]
            driver = Driver.query.filter_by(name=driver_name).first()
            if driver is None:
                driver = Driver(name=driver_name, phone=row.get("driver_phone"), sms_enabled=bool(row.get("sms_enabled", 1)))
                db.session.add(driver)
                db.session.flush()
            db.session.execute(text("UPDATE cars SET driver_id = :did WHERE id = :cid"), {"did": driver.id, "cid": row["id"]})
        db.session.commit()

        for legacy_col in ("driver_name", "driver_phone", "sms_enabled"):
            if legacy_col in car_cols:
                try:
                    db.session.execute(text(f"ALTER TABLE cars DROP COLUMN {legacy_col}"))
                    db.session.commit()
                except Exception:
                    db.session.rollback()

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
    from .models import Car, DocumentType, ExpenseCategory

    if Car.query.count() == 0:
        for code in ["DES", "DDS", "AAX", "CJK"]:
            db.session.add(Car(code=code))
    if ExpenseCategory.query.count() == 0:
        db.session.add(ExpenseCategory(name="MATUMIZI"))
    if not ExpenseCategory.query.filter_by(name="SERVICE").first():
        db.session.add(ExpenseCategory(name="SERVICE"))
    if DocumentType.query.count() == 0:
        for name in ["LATRA", "BIMA (INSURANCE)", "LESENI YA BARABARA"]:
            db.session.add(DocumentType(name=name))
    db.session.commit()


def _seed_driver_allowances():
    """One-time bootstrap: every driver already received their mid-month (kati)
    August 2026 allowance in real life before this module existed, so back-fill
    those as confirmed records (with their auto shortfall clearances) the first
    time this runs. After that, predictions correctly pick up from the
    end-of-month (mwisho) slot onward. No-op once any DriverAllowance exists."""
    from .driver_allowance import _allowance_cars, give_allowance, scheduled_date_for
    from .models import DriverAllowance

    if DriverAllowance.query.count() > 0:
        return

    period_year, period_month, period_type = 2026, 8, "kati"
    for car in _allowance_cars():
        given_date = scheduled_date_for(car.id, period_year, period_month, period_type)
        give_allowance(car, period_year, period_month, period_type, given_date)


# (code, display name) — code values must match PERMISSION_MAP's targets above.
PERMISSIONS = [
    ("collections", "Makusanyo"),
    ("reconciliation", "Upatanisho"),
    ("consumption", "Matumizi"),
    ("debts", "Madeni"),
    ("allowances", "Posho za Madereva"),
    ("cars", "Magari"),
    ("service", "Huduma"),
    ("renewals", "Nyaraka"),
    ("categories", "Aina za Matumizi"),
    ("reports", "Ripoti"),
    ("users", "Watumiaji na Majukumu"),
    ("sms", "Kutuma SMS kwa Madereva"),
]

DEFAULT_SUPER_ADMIN_USERNAME = "josephat.bakobile"
DEFAULT_SUPER_ADMIN_PASSWORD = "Bicon#123"


def _seed_auth():
    """Ensures the fixed permission set, a Super Admin role (always all-access,
    see Role.has_permission), and one Super Admin login exist. Runs on every
    startup but each step is a no-op once already seeded."""
    from .models import Permission, Role, User

    for code, name in PERMISSIONS:
        if not Permission.query.filter_by(code=code).first():
            db.session.add(Permission(code=code, name=name))
    db.session.commit()

    super_role = Role.query.filter_by(is_super_admin=True).first()
    if not super_role:
        super_role = Role(name="Msimamizi Mkuu", is_super_admin=True)
        db.session.add(super_role)
        db.session.commit()

    if User.query.count() == 0:
        admin = User(
            username=DEFAULT_SUPER_ADMIN_USERNAME,
            full_name="Josephat Bakobile",
            role=super_role,
        )
        admin.set_password(DEFAULT_SUPER_ADMIN_PASSWORD)
        db.session.add(admin)
        db.session.commit()


def _run_legacy_import():
    from .legacy_import import import_legacy

    xlsx_path = os.environ.get("LEGACY_XLSX_PATH")
    if not xlsx_path:
        return
    result = import_legacy(xlsx_path)
    print(f"[legacy_import] {result}", flush=True)
