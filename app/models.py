from datetime import date as date_cls, datetime

from .extensions import db


class Car(db.Model):
    __tablename__ = "cars"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100))
    driver_name = db.Column(db.String(100))
    active = db.Column(db.Boolean, default=True, nullable=False)
    daily_target = db.Column(db.Float, default=0.0, nullable=False)
    service_interval_days = db.Column(db.Integer, default=20, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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


class CarService(db.Model):
    """A service event performed on a car. The most recent row per car is the
    baseline the next-service prediction counts forward from; the first row ever
    entered for a car (which may be backfilled) is simply its baseline. If a cost
    is recorded, a linked ConsumptionEntry is auto-created so it flows into the
    existing consumption totals/reports without double entry."""

    __tablename__ = "car_services"

    id = db.Column(db.Integer, primary_key=True)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    service_date = db.Column(db.Date, nullable=False, default=date_cls.today)
    description = db.Column(db.String(255))
    consumption_entry_id = db.Column(
        db.Integer, db.ForeignKey("consumption_entries.id"), unique=True
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    car = db.relationship("Car")
    consumption_entry = db.relationship("ConsumptionEntry")

    @property
    def cost(self):
        return self.consumption_entry.amount if self.consumption_entry else 0.0
