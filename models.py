from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    thumb_id = db.Column(db.String(100))
    role_id = db.Column(db.String(100))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    membership_no = db.Column(db.String(20), unique=True)
    admission_date = db.Column(db.Date)
    type = db.Column(db.String(32))
    package_id = db.Column(db.Integer, db.ForeignKey('packages.id')) 
    status = db.Column(db.String(20), default="Not Paid")
    billing_date = db.Column(db.Date)
    name = db.Column(db.String(120), nullable=False)
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
    bmi_test = db.Column(db.String(10))  # 'Yes' or 'No'
    bmi_value = db.Column(db.Float)
    illnesses = db.Column(db.String(200))
    illness_other = db.Column(db.String(100))
    join_reasons = db.Column(db.String(200))
    terms_accepted = db.Column(db.Boolean, default=False)
    thumb_id = db.Column(db.String(100))
    invoices = db.relationship('Invoice', backref='customer', cascade="all, delete-orphan")
    billings = db.relationship('Billing', backref='customer', primaryjoin="Customer.cnic == foreign(Billing.customer_cnic)", cascade="all, delete-orphan")
    billing_histories = db.relationship('BillingHistory', backref='customer', primaryjoin="Customer.cnic == foreign(BillingHistory.customer_cnic)", cascade="all, delete-orphan")

class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'))
    amount = db.Column(db.Float)
    date = db.Column(db.Date)
    is_paid = db.Column(db.Boolean, default=False)

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    paid_by = db.Column(db.String(120), nullable=False)  # Employee name
    payment_method = db.Column(db.String(50), nullable=False)
    transaction_id = db.Column(db.String(100), nullable=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)

class Trainer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120))
    salary = db.Column(db.Float)
    account_no = db.Column(db.String(100))
    thumb_id = db.Column(db.String(100))  # For attendance

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    timestamp = db.Column(db.DateTime)

class Billing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(120), nullable=False)
    membership_no = db.Column(db.String(20), nullable=False)
    customer_cnic = db.Column(db.String(20), nullable=False) 
    paid_to_be_amount = db.Column(db.Float, nullable=False)
    paid_amount = db.Column(db.Float, nullable=False)
    remaining_amount = db.Column(db.Float, nullable=False)
    payment_collected_by = db.Column(db.String(100), nullable=False)   # Employee name or ID
    payment_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    payment_method = db.Column(db.String(50), nullable=False)  
    transaction_id = db.Column(db.String(50), nullable=True) 

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(50), nullable=False)
    employment_type = db.Column(db.String(50), nullable=False)
    timing = db.Column(db.String(50), nullable=True)
    shift = db.Column(db.String(50), nullable=True)
    salary = db.Column(db.Float, nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)
    cnic = db.Column(db.String(20), nullable=True)
    thumb_id = db.Column(db.String(100))  # For attendance
    salaries = db.relationship('SalaryHistory', backref='employee', primaryjoin="Employee.id == foreign(SalaryHistory.employee_id)", cascade="all, delete-orphan")

class Packages(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    package_name = db.Column(db.String(100), nullable=False)
    package_type = db.Column(db.String(50), nullable=False)  # e.g., 'Individual' or 'Personal'
    package_duration = db.Column(db.String(50), nullable=False)  # e.g., '1 Month', '6 Months'
    package_price = db.Column(db.Float, nullable=False)
    registration_fees = db.Column(db.Float, nullable=False)
    
class BillingHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_cnic = db.Column(db.String(20), nullable=False)
    customer_name = db.Column(db.String(120), nullable=False)
    membership_no = db.Column(db.String(20), nullable=False)
    amount_to_be_paid = db.Column(db.Float, nullable=False)
    paid_amount = db.Column(db.Float, nullable=False)
    remaining_amount = db.Column(db.Float, nullable=False)
    payment_collected_by = db.Column(db.String(100), nullable=False)
    payment_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    payment_method = db.Column(db.String(50), nullable=False)
    transaction_id = db.Column(db.String(50), nullable=True)


class SalaryHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, nullable=False)
    employee_name = db.Column(db.String(120), nullable=False)
    salary_amount = db.Column(db.Float, nullable=False)
    payment_type = db.Column(db.String(20), nullable=False)  # 'Salary' or 'Advance'
    payment_method = db.Column(db.String(50), nullable=False)  # 'Cash' or 'Online'
    transaction_id = db.Column(db.String(100), nullable=True)
    transaction_date = db.Column(db.DateTime, default=datetime.utcnow)
