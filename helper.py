from flask import Flask, render_template, redirect, url_for, request, flash, current_app
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from models import db, User, Customer, Attendance
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
    




def generate_unique_thumb_id(extra_blocked_ids=None):
    """
    First free 4-digit then 5-digit thumb ID, unused in Customer.thumb_id
    and not present in extra_blocked_ids (e.g. IDs already on the device).
    """
    existing_ids = {
        str(row[0]).strip()
        for row in db.session.query(Customer.thumb_id)
        .filter(Customer.thumb_id.isnot(None))
        .all()
        if row[0]
    }
    if extra_blocked_ids:
        existing_ids.update(
            str(x).strip()
            for x in extra_blocked_ids
            if x is not None and str(x).strip()
        )

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

    from zk_windows_fix import silence_zk_ping_console
    silence_zk_ping_console()

    zk = ZK(
        zk_ip,
        port=zk_port,
        timeout=zk_timeout,
        password=zk_password,
        force_udp=False,
        ommit_ping=False,
    )
    return zk.connect()


def zk_get_device_users(conn):
    return conn.get_users() or []


def zk_used_user_ids(users):
    return {
        str(getattr(user, "user_id", "")).strip()
        for user in users
        if str(getattr(user, "user_id", "")).strip()
    }


def zk_find_user_by_user_id(conn, user_id, users=None):
    users = users if users is not None else zk_get_device_users(conn)
    target = str(user_id).strip()
    for user in users:
        if str(getattr(user, "user_id", "")).strip() == target:
            return user
    return None


def zk_get_next_uid(conn, users=None):
    users = users if users is not None else zk_get_device_users(conn)
    used_uids = {
        getattr(user, "uid", None)
        for user in users
        if getattr(user, "uid", None) is not None
    }

    next_uid = 1
    while next_uid in used_uids:
        next_uid += 1
    return next_uid


def zk_create_or_get_user(conn, thumb_id, name, users=None):
    """
    Ensure a user exists on the device for this thumb_id.
    Returns a dict with uid, user_id, name, created.
    """
    users = users if users is not None else zk_get_device_users(conn)
    existing_user = zk_find_user_by_user_id(conn, thumb_id, users=users)
    display_name = (name or f"User {thumb_id}")[:24]

    if existing_user:
        uid = getattr(existing_user, "uid", None)
        try:
            conn.set_user(
                uid=uid,
                name=display_name,
                privilege=0,
                password="",
                group_id="",
                user_id=str(thumb_id),
            )
        except Exception as exc:
            current_app.logger.warning(
                "Could not refresh device user name for thumb_id=%s: %s", thumb_id, exc
            )
        return {
            "uid": uid,
            "user_id": str(getattr(existing_user, "user_id", "")),
            "name": display_name,
            "created": False,
        }

    next_uid = zk_get_next_uid(conn, users=users)

    conn.set_user(
        uid=next_uid,
        name=display_name,
        privilege=0,
        password="",
        group_id="",
        user_id=str(thumb_id),
    )

    time.sleep(1)

    refreshed = zk_get_device_users(conn)
    created_user = zk_find_user_by_user_id(conn, thumb_id, users=refreshed)
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


def zk_clear_fingerprint(conn, uid, thumb_id, temp_id=0):
    """Remove existing fingerprint template so enroll is not blocked as 'already exists'."""
    try:
        conn.delete_user_template(uid=uid, temp_id=temp_id, user_id=str(thumb_id))
        current_app.logger.info(
            "Cleared fingerprint template uid=%s thumb_id=%s temp_id=%s",
            uid, thumb_id, temp_id,
        )
        time.sleep(0.5)
        return True
    except Exception as exc:
        current_app.logger.info(
            "No fingerprint to clear for uid=%s thumb_id=%s: %s",
            uid, thumb_id, exc,
        )
        return False


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
            "message": "Enrollment started. Place finger on the machine now.",
        }
    except Exception as exc:
        current_app.logger.warning(
            "ZKTeco enroll_user raised exception for uid=%s thumb_id=%s temp_id=%s: %s",
            uid, thumb_id, temp_id, exc
        )
        return {
            "success": True,
            "raw_result": str(exc),
            "message": f"Enrollment command sent. If machine shows an error, note it. Detail: {exc}",
        }


def register_or_enroll_customer_on_zkteco(customer):
    """
    Connect to machine first, assign a thumb_id free in DB and on device,
    create/update device user, clear old fingerprint if needed, then enroll.
    """
    conn = None
    try:
        # 1) Talk to machine BEFORE assigning any new ID
        conn = zk_connect()
        conn.disable_device()

        users = zk_get_device_users(conn)
        device_ids = zk_used_user_ids(users)

        def _names_match(device_name, customer_name):
            left = (device_name or "").strip().lower()[:24]
            right = (customer_name or "").strip().lower()[:24]
            return bool(left) and bool(right) and left == right

        previous_thumb_id = (
            str(customer.thumb_id).strip()
            if customer.thumb_id and str(customer.thumb_id).strip()
            else None
        )

        # 2) Pick / keep thumb_id only if free on machine (and DB)
        if previous_thumb_id:
            thumb_id = previous_thumb_id
            other_owner = (
                Customer.query
                .filter(
                    Customer.thumb_id == thumb_id,
                    Customer.id != customer.id,
                )
                .first()
            )
            device_owner = zk_find_user_by_user_id(conn, thumb_id, users=users)
            needs_new_id = bool(other_owner)
            if device_owner:
                device_name = (getattr(device_owner, "name", "") or "").strip()
                # ID already on machine under a different name -> assign a new free ID
                if device_name and not _names_match(device_name, customer.name):
                    needs_new_id = True
                # ID on machine with no/matching name: reuse for re-enroll
            elif thumb_id in device_ids:
                # Present in device id set but not found as owner object — still avoid collision
                needs_new_id = True

            if needs_new_id:
                thumb_id = generate_unique_thumb_id(extra_blocked_ids=device_ids)
                customer.thumb_id = thumb_id
                db.session.commit()
        else:
            thumb_id = generate_unique_thumb_id(extra_blocked_ids=device_ids)
            customer.thumb_id = thumb_id
            db.session.commit()

        # Keep existing attendance rows pointing at this customer in sync
        Attendance.query.filter_by(customer_id=customer.id).update(
            {"thumb_id": thumb_id}, synchronize_session=False
        )
        db.session.commit()

        # If we moved to a new ID, remove the old machine user so punches use the new ID
        if previous_thumb_id and previous_thumb_id != thumb_id:
            old_user = zk_find_user_by_user_id(conn, previous_thumb_id, users=users)
            if old_user:
                try:
                    conn.delete_user(
                        uid=getattr(old_user, "uid", 0) or 0,
                        user_id=str(previous_thumb_id),
                    )
                    current_app.logger.info(
                        "Deleted old device user thumb_id=%s after reassign to %s",
                        previous_thumb_id, thumb_id,
                    )
                except Exception as exc:
                    current_app.logger.warning(
                        "Could not delete old device user thumb_id=%s: %s",
                        previous_thumb_id, exc,
                    )

        # 3) Create user on machine only after ID is confirmed free / owned
        users = zk_get_device_users(conn)
        device_user = zk_create_or_get_user(
            conn, thumb_id, customer.name, users=users
        )
        uid = device_user.get("uid")

        if uid is None:
            raise Exception("Unable to determine device UID for enrollment.")

        # 4) Clear old finger template so machine does not say "already exists"
        zk_clear_fingerprint(conn, uid=uid, thumb_id=thumb_id, temp_id=0)

        enroll_result = zk_start_enrollment(conn, uid=uid, thumb_id=thumb_id, temp_id=0)

        # Keep connection alive so device can finish finger capture
        enroll_wait = int(os.getenv("ZK_ENROLL_WAIT_SECONDS", "15"))
        if enroll_wait > 0:
            time.sleep(enroll_wait)

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
