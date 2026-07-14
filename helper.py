from flask import Flask, render_template, redirect, url_for, request, flash, current_app
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
import os
import time
from zk import ZK
from flask import current_app


def parse_float(val):
    try:
        return float(val) if val not in (None, '', 'None') else None
    except ValueError:
        return None
    
def parse_package_months(package_duration):
    """Convert package duration strings like '1 Month', '3 Months', '1 Year' to months."""
    if not package_duration:
        return 1
    duration = str(package_duration).lower().replace(' ', '')
    if 'year' in duration or duration in ('12month', '12months'):
        return 12
    if '6month' in duration:
        return 6
    if '3month' in duration:
        return 3
    return 1


def get_billing_date(base_date, package_duration):
    """
    Next billing date from base_date (admission or current billing)
    advanced by the package duration.
    """
    if not base_date:
        return None
    months = parse_package_months(package_duration)
    return base_date + relativedelta(months=months)


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


# def generate_membership_no():
#     today_str = datetime.now().strftime('%Y%m')
#     last = Customer.query.order_by(Customer.id.desc()).first()
#     next_num = 1 if not last else last.id + 1
#     return f"{today_str}-{next_num:03d}"


def generate_membership_no(prefix="XYZ"):
    """
    Generate next membership number based on latest membership_no in DB.
    Example:
        XYZ-00001 -> XYZ-00002
    """
    last_customer = (
        Customer.query
        .filter(Customer.membership_no.isnot(None))
        .filter(Customer.membership_no != "")
        .order_by(Customer.id.desc())
        .first()
    )

    if not last_customer or not last_customer.membership_no:
        return f"{prefix}-00001"

    last_membership_no = last_customer.membership_no.strip()

    match = re.match(r"^([A-Za-z]+)-(\d+)$", last_membership_no)
    if not match:
        return f"{prefix}-00001"

    last_prefix = match.group(1)
    last_number = int(match.group(2))

    next_number = last_number + 1
    return f"{last_prefix}-{next_number:06d}"


def validate_phone(form, field):
    phone = field.data.strip()
    if not phone.isdigit() or len(phone) != 11:
        raise ValidationError('Phone number must be exactly 11 digits.')
    if phone.startswith('+'):
        raise ValidationError('Enter without country code (e.g., 03001234567).')
    




def generate_unique_thumb_id(existing_ids):
    for length in (4, 5):
        start = 10 ** (length - 1)
        end = (10 ** length) - 1
        for num in range(start, end + 1):
            candidate = str(num)
            if candidate not in existing_ids:
                return candidate
    raise Exception("No available 4-digit or 5-digit thumb ID found")





def create_zkteco_user(thumb_id, name):
    import os
    from zk import ZK

    zk_ip = os.getenv("ZK_IP", "")
    zk_port = int(os.getenv("ZK_PORT", "4370"))
    zk_timeout = int(os.getenv("ZK_TIMEOUT", "10"))
    zk_password = int(os.getenv("ZK_PASSWORD", "0"))

    if not zk_ip:
        raise Exception("ZK_IP is not configured")

    zk = ZK(
        zk_ip,
        port=zk_port,
        timeout=zk_timeout,
        password=zk_password,
        force_udp=False,
        ommit_ping=False,
    )

    conn = None
    try:
        conn = zk.connect()
        conn.disable_device()

        users = conn.get_users() or []
        used_uids = {getattr(u, "uid", None) for u in users if getattr(u, "uid", None) is not None}

        next_uid = 1
        while next_uid in used_uids:
            next_uid += 1

        conn.set_user(
            uid=next_uid,
            name=name[:24] if name else f"User {thumb_id}",
            privilege=0,
            password='',
            group_id='',
            user_id=str(thumb_id),
        )

        # Optional / device-dependent:
        # if hasattr(conn, 'enroll_user'):
        #     conn.enroll_user(str(thumb_id))

        return {
            "success": True,
            "message": f"User created on device with Thumb ID {thumb_id}. Please enroll fingerprint on machine."
        }

    finally:
        if conn:
            try:
                conn.enable_device()
                conn.disconnect()
            except Exception:
                pass



def generate_unique_thumb_id():
    """
    Generate the first available 4-digit or 5-digit thumb ID
    not already used in Customer.thumb_id.
    """
    existing_ids = {
        str(row[0]).strip()
        for row in db.session.query(Customer.thumb_id)
        .filter(Customer.thumb_id.isnot(None))
        .all()
        if row[0]
    }

    for length in (4, 5):
        start = 10 ** (length - 1)
        end = (10 ** length) - 1
        for num in range(start, end + 1):
            candidate = str(num)
            if candidate not in existing_ids:
                return candidate

    raise Exception("No available 4-digit or 5-digit thumb ID found.")


def zk_connect():
    zk_ip = os.getenv("ZK_IP", "")
    zk_port = int(os.getenv("ZK_PORT", "4370"))
    zk_timeout = int(os.getenv("ZK_TIMEOUT", "10"))
    zk_password = int(os.getenv("ZK_PASSWORD", "0"))

    if not zk_ip:
        raise Exception("ZK_IP is not configured.")

    zk = ZK(
        zk_ip,
        port=zk_port,
        timeout=zk_timeout,
        password=zk_password,
        force_udp=False,
        ommit_ping=False,
    )
    return zk.connect()


def zk_find_user_by_user_id(conn, user_id):
    users = conn.get_users() or []
    for user in users:
        if str(getattr(user, "user_id", "")).strip() == str(user_id).strip():
            return user
    return None


def zk_get_next_uid(conn):
    users = conn.get_users() or []
    used_uids = {
        getattr(user, "uid", None)
        for user in users
        if getattr(user, "uid", None) is not None
    }

    next_uid = 1
    while next_uid in used_uids:
        next_uid += 1
    return next_uid


def zk_create_or_get_user(conn, thumb_id, name):
    """
    Ensure a user exists on the device for this thumb_id.
    Returns a dict with uid, user_id, name, created.
    """
    existing_user = zk_find_user_by_user_id(conn, thumb_id)
    if existing_user:
        return {
            "uid": getattr(existing_user, "uid", None),
            "user_id": str(getattr(existing_user, "user_id", "")),
            "name": getattr(existing_user, "name", ""),
            "created": False,
        }

    next_uid = zk_get_next_uid(conn)

    conn.set_user(
        uid=next_uid,
        name=(name or f"User {thumb_id}")[:24],
        privilege=0,   # normal user
        password="",
        group_id="",
        user_id=str(thumb_id),
    )

    time.sleep(1)

    created_user = zk_find_user_by_user_id(conn, thumb_id)
    if created_user:
        return {
            "uid": getattr(created_user, "uid", None),
            "user_id": str(getattr(created_user, "user_id", "")),
            "name": getattr(created_user, "name", ""),
            "created": True,
        }

    return {
        "uid": next_uid,
        "user_id": str(thumb_id),
        "name": name,
        "created": True,
    }


def zk_start_enrollment(conn, uid, thumb_id, temp_id=0):
    """
    Start fingerprint enrollment on device.

    Important:
    On K50/pyzk, enroll_user may return False even when the machine
    actually starts enrollment. So False is not treated as failure here.
    """
    try:
        result = conn.enroll_user(uid=uid, temp_id=temp_id, user_id=str(thumb_id))
        current_app.logger.info(
            "ZKTeco enroll_user called for uid=%s thumb_id=%s temp_id=%s result=%s",
            uid, thumb_id, temp_id, result
        )
        return {
            "success": True,
            "raw_result": result,
            "message": "Enrollment command sent to machine. Please place finger on machine."
        }
    except Exception as exc:
        current_app.logger.warning(
            "ZKTeco enroll_user raised exception for uid=%s thumb_id=%s temp_id=%s: %s",
            uid, thumb_id, temp_id, exc
        )
        return {
            "success": True,
            "raw_result": str(exc),
            "message": "Enrollment command sent to machine. If prompted, place finger now."
        }



def register_or_enroll_customer_on_zkteco(customer):
    """
    Ensures customer has a thumb_id, ensures device user exists,
    and sends enrollment command to device.
    """
    conn = None
    try:
        if customer.thumb_id and str(customer.thumb_id).strip():
            thumb_id = str(customer.thumb_id).strip()
        else:
            thumb_id = generate_unique_thumb_id()
            customer.thumb_id = thumb_id
            db.session.commit()

        conn = zk_connect()
        conn.disable_device()

        device_user = zk_create_or_get_user(conn, thumb_id, customer.name)
        uid = device_user.get("uid")

        if uid is None:
            raise Exception("Unable to determine device UID for enrollment.")

        enroll_result = zk_start_enrollment(conn, uid=uid, thumb_id=thumb_id, temp_id=0)

        return {
            "success": True,
            "thumb_id": thumb_id,
            "uid": uid,
            "created": device_user.get("created", False),
            "message": enroll_result["message"],
            "raw_result": enroll_result.get("raw_result"),
        }

    finally:
        if conn:
            try:
                conn.enable_device()
                conn.disconnect()
            except Exception:
                pass
