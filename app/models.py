from datetime import date as date_cls, datetime

from .extensions import db


class Car(db.Model):
    __tablename__ = "cars"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100))
    active = db.Column(db.Boolean, default=True, nullable=False)
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
    __tablename__ = "collection_transactions"

    id = db.Column(db.Integer, primary_key=True)
    trans_no = db.Column(db.String(30), unique=True, nullable=False)
    date = db.Column(db.Date, nullable=False, default=date_cls.today)
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
    __tablename__ = "collection_lines"

    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(
        db.Integer, db.ForeignKey("collection_transactions.id"), nullable=False
    )
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
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
