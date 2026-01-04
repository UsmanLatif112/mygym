from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from models import db, User, Customer
from datetime import datetime
import json
from dateutil.relativedelta import relativedelta
from wtforms.validators import ValidationError
from flask_wtf import FlaskForm
from wtforms import StringField, StringField, PasswordField, SubmitField, FloatField, SelectField, DateField, BooleanField, SelectMultipleField, TextAreaField, RadioField
from wtforms.validators import DataRequired, Email, Length, Optional, Regexp,  ValidationError
import re
from models import Customer,Employee

def parse_float(val):
    try:
        return float(val) if val not in (None, '', 'None') else None
    except ValueError:
        return None
    
def get_billing_date(admission_date, package):
    # Defensive: if package is None, treat as '1Month'
    if not package:
        months = 1
    elif '3Month' in package:
        months = 3
    elif '6Month' in package:
        months = 6
    else:
        months = 1
    return admission_date + relativedelta(months=months)


def parse_tagify(data):
    try:
        tags = json.loads(data)
        return ', '.join(tag['value'] for tag in tags if tag.get('value'))
    except Exception:
        return data or ''

def serialize_billing_history(billing_history):
    return {
        'id': billing_history.id,
        'customer_cnic': billing_history.customer_cnic,
        'customer_name': billing_history.customer_name,
        'membership_no': billing_history.membership_no,
        'amount_to_be_paid': billing_history.amount_to_be_paid,
        'paid_amount': billing_history.paid_amount,
        'remaining_amount': billing_history.remaining_amount,
        'payment_collected_by': billing_history.payment_collected_by,
        'payment_method': billing_history.payment_method,
        'transaction_id': billing_history.transaction_id,
        'payment_date': billing_history.payment_date.strftime('%Y-%m-%d')  # Convert to string here
    }


    
def get_customer_type(package):
    if not package:
        return "Unknown"
    if "Individual" in package:
        return "Individual"
    elif "Personal" in package:
        return "Personal"
    return "Unknown"


def generate_membership_no():
    today_str = datetime.now().strftime('%Y%m')
    last = Customer.query.order_by(Customer.id.desc()).first()
    next_num = 1 if not last else last.id + 1
    return f"{today_str}-{next_num:03d}"


def validate_phone(form, field):
    phone = field.data.strip()
    if not phone.isdigit() or len(phone) != 11:
        raise ValidationError('Phone number must be exactly 11 digits.')
    if phone.startswith('+'):
        raise ValidationError('Enter without country code (e.g., 03001234567).')