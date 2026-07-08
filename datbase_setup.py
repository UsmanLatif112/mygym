from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

app = Flask(__name__)

# ========================
# DATABASE CONFIG
# ========================
DB_USER = "mygymlahore_admin_alphafitnessgym"
DB_PASS = "Waqas%400336"
DB_HOST = "148.163.100.132"
DB_PORT = "3306"
DB_NAME = "mygymlahore_alphafitnessgym"

app.config["SQLALCHEMY_DATABASE_URI"] = (
    f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# ========================
# MODELS
# ========================

class User(UserMixin, db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255))
    thumb_id = db.Column(db.String(100))
    role_id = db.Column(db.String(100))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Packages(db.Model):
    __tablename__ = "packages"

    id = db.Column(db.Integer, primary_key=True)
    package_name = db.Column(db.String(100), nullable=False)
    package_type = db.Column(db.String(50), nullable=False)
    package_duration = db.Column(db.String(50), nullable=False)
    package_price = db.Column(db.Integer, nullable=False)
    registration_fees = db.Column(db.Integer, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )


class Customer(db.Model):
    __tablename__ = "customer"

    id = db.Column(db.Integer, primary_key=True)

    membership_no = db.Column(
        db.String(20),
        unique=True
    )

    admission_date = db.Column(db.Date)

    type = db.Column(db.String(32))

    package_id = db.Column(
        db.Integer,
        db.ForeignKey("packages.id")
    )

    status = db.Column(
        db.String(20),
        default="Not Paid"
    )

    billing_date = db.Column(db.Date)

    name = db.Column(
        db.String(120),
        nullable=False
    )

    email = db.Column(db.String(120))
    father_or_husband = db.Column(db.String(120))
    cnic = db.Column(db.String(20))

    gender = db.Column(db.String(20))
    marital_status = db.Column(db.String(20))

    blood_group = db.Column(db.String(10))

    dob = db.Column(db.Date)

    height = db.Column(db.Float)
    weight = db.Column(db.Float)
    waist = db.Column(db.Float)

    profession = db.Column(db.String(120))

    nationality = db.Column(db.String(50))

    address = db.Column(db.String(200))

    phone = db.Column(db.String(30))
    emergency_contact = db.Column(db.String(30))

    package = db.Column(db.String(50))

    personal_training_time = db.Column(db.String(50))

    trainer = db.Column(db.String(50))

    bmi_test = db.Column(db.String(10))

    bmi_value = db.Column(db.Float)

    illnesses = db.Column(db.String(200))
    illness_other = db.Column(db.String(100))

    join_reasons = db.Column(db.String(200))

    terms_accepted = db.Column(
        db.Boolean,
        default=False
    )

    thumb_id = db.Column(db.String(100))

    discount_amount = db.Column(
        db.Integer,
        default=0
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )


class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    customer_id = db.Column(
        db.Integer,
        db.ForeignKey("customer.id")
    )

    amount = db.Column(db.Integer)

    date = db.Column(db.Date)

    is_paid = db.Column(
        db.Boolean,
        default=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(
        db.String(120),
        nullable=False
    )

    description = db.Column(db.String(255))

    amount = db.Column(
        db.Integer,
        nullable=False
    )

    paid_by = db.Column(
        db.String(120),
        nullable=False
    )

    payment_method = db.Column(
        db.String(50),
        nullable=False
    )

    transaction_id = db.Column(db.String(100))

    date = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )


class Trainer(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(120))

    salary = db.Column(db.Integer)

    account_no = db.Column(db.String(100))

    thumb_id = db.Column(db.String(100))

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )


class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id")
    )

    timestamp = db.Column(db.DateTime)

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )


class Billing(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    customer_name = db.Column(
        db.String(120),
        nullable=False
    )

    membership_no = db.Column(
        db.String(20),
        nullable=False
    )

    customer_cnic = db.Column(
        db.String(20),
        nullable=False
    )

    paid_to_be_amount = db.Column(
        db.Integer,
        nullable=False
    )

    paid_amount = db.Column(
        db.Integer,
        nullable=False
    )

    remaining_amount = db.Column(
        db.Integer,
        nullable=False
    )

    payment_collected_by = db.Column(
        db.String(100),
        nullable=False
    )

    payment_date = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    payment_method = db.Column(
        db.String(50),
        nullable=False
    )

    transaction_id = db.Column(
        db.String(50)
    )

    discount_amount = db.Column(
        db.Integer,
        default=0
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )


class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(
        db.String(100),
        nullable=False
    )

    status = db.Column(
        db.String(50),
        nullable=False
    )

    employment_type = db.Column(
        db.String(50),
        nullable=False
    )

    timing = db.Column(db.String(50))

    shift = db.Column(db.String(50))

    salary = db.Column(db.Integer)

    phone_number = db.Column(db.String(20))

    cnic = db.Column(db.String(20))

    thumb_id = db.Column(db.String(100))

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )


class BillingHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)

class SalaryHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)

class RemainingAmount(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    membership_no = db.Column(
        db.String(20),
        nullable=False
    )

    remaining_amount = db.Column(
        db.Integer,
        default=0
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


# ========================
# CREATE TABLES
# ========================

with app.app_context():

    db.create_all()

    existing = User.query.filter_by(
        username="Waqas_Alpha"
    ).first()

    if not existing:

        user = User(
            username="Waqas_Alpha",
            role_id="1"
        )

        user.set_password(
            "Waqas@01478520"
        )

        db.session.add(user)
        db.session.commit()

        print("✅ Tables created")
        print("✅ Admin user inserted")

    else:
        print("ℹ User already exists")