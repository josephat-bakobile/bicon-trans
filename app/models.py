from datetime import date as date_cls, datetime

from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


role_permissions = db.Table(
    "role_permissions",
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id"), primary_key=True),
    db.Column("permission_id", db.Integer, db.ForeignKey("permissions.id"), primary_key=True),
)


class Permission(db.Model):
    """A fixed, code-defined capability (one per menu/module). Seeded once at
    startup in _seed_auth(); not user-creatable, only assignable to roles."""

    __tablename__ = "permissions"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)

    def __repr__(self):
        return self.code


class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    is_super_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    permissions = db.relationship("Permission", secondary=role_permissions, backref="roles")

    def has_permission(self, code):
        if self.is_super_admin:
            return True
        return any(p.code == code for p in self.permissions)

    def __repr__(self):
        return self.name


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    full_name = db.Column(db.String(120))
    password_hash = db.Column(db.String(255), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    role = db.relationship("Role")

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    def has_permission(self, code):
        return self.role.has_permission(code)

    def __repr__(self):
        return self.username


class Driver(db.Model):
    """A driver, independent of any car. One driver may operate at most one car
    at a time -- enforced by the unique constraint on Car.driver_id -- so a
    driver is reassigned (not duplicated) when they move to a different car."""

    __tablename__ = "drivers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    sms_enabled = db.Column(db.Boolean, default=True, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return self.name


class Car(db.Model):
    __tablename__ = "cars"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100))
    driver_id = db.Column(db.Integer, db.ForeignKey("drivers.id"), unique=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    daily_target = db.Column(db.Float, default=0.0, nullable=False)
    service_interval_days = db.Column(db.Integer, default=20, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    driver = db.relationship("Driver", backref=db.backref("car", uselist=False))

    def __repr__(self):
        return self.code


class ExpenseCategory(db.Model):
    __tablename__ = "expense_categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return self.name


class CollectionTransaction(db.Model):
    """The bank-facing event: one deposit/handover to the agent, reconciled against
    the bank statement by trans_no + transaction_date. May bundle contributions from
    several cars, and each car's contribution may itself cover more than one day's
    target (see CollectionLine.collection_date)."""

    __tablename__ = "collection_transactions"

    id = db.Column(db.Integer, primary_key=True)
    trans_no = db.Column(db.String(30), unique=True, nullable=False)
    transaction_date = db.Column(db.Date, nullable=False, default=date_cls.today)
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    lines = db.relationship(
        "CollectionLine",
        backref="transaction",
        cascade="all, delete-orphan",
        order_by="CollectionLine.id",
    )

    @property
    def total(self):
        return sum(line.amount for line in self.lines)


class CollectionLine(db.Model):
    """One car's contribution within a transaction. collection_date is the day this
    amount counts toward for that car's daily_target — independent of the parent
    transaction's bank date, so a driver catching up on an earlier shortfall can have
    the same transaction split across several collection_date rows for one car."""

    __tablename__ = "collection_lines"

    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(
        db.Integer, db.ForeignKey("collection_transactions.id"), nullable=False
    )
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    collection_date = db.Column(db.Date, nullable=False, default=date_cls.today)
    amount = db.Column(db.Float, nullable=False)
    note = db.Column(db.String(255))

    car = db.relationship("Car")


class ConsumptionEntry(db.Model):
    __tablename__ = "consumption_entries"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=date_cls.today)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("expense_categories.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    car = db.relationship("Car")
    category = db.relationship("ExpenseCategory")


class Debt(db.Model):
    """An amount a car owes (increases the outstanding balance)."""

    __tablename__ = "debts"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=date_cls.today)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    car = db.relationship("Car")


class DebtPayment(db.Model):
    """An amount a car has paid back (reduces the outstanding balance)."""

    __tablename__ = "debt_payments"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=date_cls.today)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    car = db.relationship("Car")


class ShortfallClearance(db.Model):
    """Explanation recorded against a car/date whose collection fell short of
    (or missed entirely) that car's daily_target. Clears the day off the
    open-shortfalls report without deleting the underlying shortage."""

    __tablename__ = "shortfall_clearances"
    __table_args__ = (db.UniqueConstraint("car_id", "date", name="uq_shortfall_car_date"),)

    id = db.Column(db.Integer, primary_key=True)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    description = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    car = db.relationship("Car")


class DriverAllowance(db.Model):
    """A confirmed Posho ya Dereva disbursement: one of a car's 2 monthly slots
    (mid-month 'kati' or end-of-month 'mwisho'), amount always the car's
    daily_target at confirmation time -- the driver keeps that day's collection
    instead of depositing it. If the car had an outstanding debt, some or all of
    the amount is redirected to a linked DebtPayment instead of cash; either way
    the day is auto-explained via a matching ShortfallClearance."""

    __tablename__ = "driver_allowances"
    __table_args__ = (
        db.UniqueConstraint("car_id", "period_year", "period_month", "period_type", name="uq_allowance_car_period"),
    )

    id = db.Column(db.Integer, primary_key=True)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    period_year = db.Column(db.Integer, nullable=False)
    period_month = db.Column(db.Integer, nullable=False)
    period_type = db.Column(db.String(10), nullable=False)  # 'kati' (mid-month) | 'mwisho' (end-of-month)
    date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    applied_to_debt = db.Column(db.Float, default=0.0, nullable=False)
    debt_payment_id = db.Column(db.Integer, db.ForeignKey("debt_payments.id"))
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    car = db.relationship("Car")
    debt_payment = db.relationship("DebtPayment")

    @property
    def cash_amount(self):
        return self.amount - self.applied_to_debt


class CarService(db.Model):
    """A service event performed on a car. The most recent row per car is the
    baseline the next-service prediction counts forward from; the first row ever
    entered for a car (which may be backfilled) is simply its baseline. If a cost
    is recorded, a linked ConsumptionEntry is auto-created so it flows into the
    existing consumption totals/reports without double entry. A car doesn't
    collect on the day it's serviced either, so a linked ShortfallClearance is
    kept in sync the same way, auto-explaining that day's shortfall."""

    __tablename__ = "car_services"

    id = db.Column(db.Integer, primary_key=True)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    service_date = db.Column(db.Date, nullable=False, default=date_cls.today)
    description = db.Column(db.String(255))
    consumption_entry_id = db.Column(
        db.Integer, db.ForeignKey("consumption_entries.id"), unique=True
    )
    shortfall_clearance_id = db.Column(
        db.Integer, db.ForeignKey("shortfall_clearances.id"), unique=True
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    car = db.relationship("Car")
    consumption_entry = db.relationship("ConsumptionEntry")
    shortfall_clearance = db.relationship("ShortfallClearance")

    @property
    def cost(self):
        return self.consumption_entry.amount if self.consumption_entry else 0.0


class DocumentType(db.Model):
    """A category of yearly renewal a car must keep current, e.g. LATRA, BIMA
    (insurance), Leseni ya Barabara. Configurable so new renewal types can be
    added without a code change, same pattern as ExpenseCategory."""

    __tablename__ = "document_types"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return self.name


class CarDocument(db.Model):
    """One renewal period of a given document type for a car. expire_date is
    always start_date + 1 year - 1 day, computed at creation time. The most
    recent row (by start_date) per car/document_type pair is the current
    renewal period that alerts/status are calculated from."""

    __tablename__ = "car_documents"

    id = db.Column(db.Integer, primary_key=True)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    document_type_id = db.Column(db.Integer, db.ForeignKey("document_types.id"), nullable=False)
    start_date = db.Column(db.Date, nullable=False, default=date_cls.today)
    expire_date = db.Column(db.Date, nullable=False)
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    car = db.relationship("Car")
    document_type = db.relationship("DocumentType")


class SmsLog(db.Model):
    """One attempted SMS send (whether it succeeded or not), for audit/troubleshooting
    -- e.g. a driver claiming they never got a notification, or checking Beem usage."""

    __tablename__ = "sms_logs"

    id = db.Column(db.Integer, primary_key=True)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"))
    driver_id = db.Column(db.Integer, db.ForeignKey("drivers.id"))
    phone = db.Column(db.String(20))
    scenario = db.Column(db.String(30), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(10), nullable=False)
    error = db.Column(db.String(255))
    sent_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    car = db.relationship("Car")
    driver = db.relationship("Driver")
    sent_by = db.relationship("User")
