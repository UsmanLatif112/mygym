from flask import Flask, render_template, redirect, url_for, request, flash, abort, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from models import BillingHistory, db, User, Customer, Billing, Packages, Employee, Attendance, Expense, SalaryHistory, RemainingAmount
from forms import LoginForm, CustomerForm, EmployeeForm
from datetime import date, datetime, timedelta, timezone
import os,sys
import logging
import json
import time
import threading
import requests
from dotenv import load_dotenv
from math import ceil
from dateutil.relativedelta import relativedelta
from sqlalchemy import or_, text
from urllib.parse import urlparse
from helper import parse_float, get_billing_date, parse_tagify, get_customer_type, generate_membership_no, serialize_billing_history
from helper import (
    parse_float,
    get_billing_date,
    parse_tagify,
    get_customer_type,
    generate_membership_no,
    serialize_billing_history,
    register_or_enroll_customer_on_zkteco,
)

from utils import paginate_list
from attendance_utils import parse_check_in_at, should_skip_duplicate   
from zk import ZK


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

bundled_env = resource_path(".env")
if os.path.exists(bundled_env):
    load_dotenv(bundled_env)
else:
    load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'

# DB_BACKEND=sqlite  -> local app DB (default — all normal work)
# DB_BACKEND=mysql   -> only for cPanel hosted site if needed
from db_sync import (
    DATA_DIR,
    hours_since_last_push,
    load_sync_meta,
    mysql_uri_from_env,
    run_full_backup,
    seed_sqlite_from_dump,
    should_auto_push,
    sqlite_uri,
    sync_status_summary,
)

# Default SQLite so the app never talks to MySQL unless Backup push runs.
DB_BACKEND = os.getenv("DB_BACKEND", "sqlite").strip().lower()
SQLITE_DB_PATH = DATA_DIR / "mygym_local.db"
BACKUP_AUTO_PUSH_ENABLED = os.getenv("BACKUP_AUTO_PUSH", "1") == "1"
BACKUP_AUTO_PUSH_HOURS = float(os.getenv("BACKUP_AUTO_PUSH_HOURS", "24"))
BACKUP_CRON_CHECK_SECONDS = int(os.getenv("BACKUP_CRON_CHECK_SECONDS", "3600"))

if DB_BACKEND == "sqlite":
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = sqlite_uri(SQLITE_DB_PATH)
else:
    # cPanel / explicit mysql mode only
    app.config["SQLALCHEMY_DATABASE_URI"] = mysql_uri_from_env()

app.config["DB_BACKEND"] = DB_BACKEND
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

INGEST_SECRET = os.getenv("ATTENDANCE_INGEST_KEY", "")
ATTENDANCE_DEDUP_SECONDS = int(os.getenv("ATTENDANCE_DEDUP_SECONDS", "60"))
ATTENDANCE_INACTIVE_DAYS = int(os.getenv("ATTENDANCE_INACTIVE_DAYS", "30"))
ATTENDANCE_CRON_ENABLED = os.getenv("ATTENDANCE_CRON_ENABLED", "1") == "1"
ATTENDANCE_CRON_INTERVAL_SECONDS = int(os.getenv("ATTENDANCE_CRON_INTERVAL_SECONDS", "300"))
ATTENDANCE_PAGE_AUTO_SYNC_SECONDS = int(os.getenv("ATTENDANCE_PAGE_AUTO_SYNC_SECONDS", "5"))
ATTENDANCE_FETCH_URL = os.getenv("ATTENDANCE_FETCH_URL", "").strip()
ATTENDANCE_FETCH_API_KEY = os.getenv("ATTENDANCE_FETCH_API_KEY", "").strip()
ZK_IP = os.getenv("ZK_IP", "").strip()
ZK_PORT = int(os.getenv("ZK_PORT", "4370"))
ZK_TIMEOUT = int(os.getenv("ZK_TIMEOUT", "10"))
ZK_PASSWORD = int(os.getenv("ZK_PASSWORD", "0"))
app.logger.setLevel(logging.INFO)





def _table_columns(conn, table_name: str) -> set[str]:
    """Return existing column names for MySQL or SQLite."""
    dialect = db.engine.dialect.name
    if dialect == "sqlite":
        rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        # PRAGMA: cid, name, type, notnull, dflt_value, pk
        return {row[1] for row in rows}
    rows = conn.execute(text(f"SHOW COLUMNS FROM {table_name}")).fetchall()
    return {row[0] for row in rows}


def _add_column_if_missing(conn, table_name: str, column_name: str, column_sql: str, existing: set[str]) -> None:
    if column_name in existing:
        return
    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}"))
    existing.add(column_name)


def ensure_attendance_schema():
    """Best-effort schema patch for deployments without migration tooling."""
    with db.engine.begin() as conn:
        existing = _table_columns(conn, "attendance")

        _add_column_if_missing(conn, "attendance", "user_id", "user_id INTEGER", existing)
        _add_column_if_missing(conn, "attendance", "timestamp", "timestamp DATETIME", existing)
        _add_column_if_missing(conn, "attendance", "customer_id", "customer_id INTEGER", existing)
        _add_column_if_missing(conn, "attendance", "thumb_id", "thumb_id VARCHAR(100)", existing)
        _add_column_if_missing(conn, "attendance", "check_in_at", "check_in_at DATETIME", existing)
        _add_column_if_missing(conn, "attendance", "source", "source VARCHAR(50)", existing)
        _add_column_if_missing(conn, "attendance", "device_sn", "device_sn VARCHAR(100)", existing)
        _add_column_if_missing(conn, "attendance", "raw_uid", "raw_uid VARCHAR(100)", existing)
        _add_column_if_missing(conn, "attendance", "event_id", "event_id VARCHAR(120)", existing)

        index_statements = [
            "CREATE INDEX idx_attendance_thumb_id ON attendance (thumb_id)",
            "CREATE INDEX idx_attendance_check_in_at ON attendance (check_in_at)",
            "CREATE INDEX idx_attendance_customer_id ON attendance (customer_id)",
            "CREATE INDEX idx_attendance_event_id ON attendance (event_id)",
        ]
        for statement in index_statements:
            try:
                conn.execute(text(statement))
            except Exception:
                # Index likely already exists; this schema sync is intentionally best-effort.
                pass


def ensure_billing_history_schema():
    """Best-effort schema patch for billing_history table."""
    with db.engine.begin() as conn:
        existing = _table_columns(conn, "billing_history")

        _add_column_if_missing(conn, "billing_history", "customer_cnic", "customer_cnic VARCHAR(20)", existing)
        _add_column_if_missing(conn, "billing_history", "customer_name", "customer_name VARCHAR(120)", existing)
        _add_column_if_missing(conn, "billing_history", "membership_no", "membership_no VARCHAR(20)", existing)
        _add_column_if_missing(conn, "billing_history", "amount_to_be_paid", "amount_to_be_paid INTEGER", existing)
        _add_column_if_missing(conn, "billing_history", "paid_amount", "paid_amount INTEGER", existing)
        _add_column_if_missing(conn, "billing_history", "remaining_amount", "remaining_amount INTEGER", existing)
        _add_column_if_missing(conn, "billing_history", "payment_collected_by", "payment_collected_by VARCHAR(100)", existing)
        _add_column_if_missing(conn, "billing_history", "payment_date", "payment_date DATETIME", existing)
        _add_column_if_missing(conn, "billing_history", "payment_method", "payment_method VARCHAR(50)", existing)
        _add_column_if_missing(conn, "billing_history", "transaction_id", "transaction_id VARCHAR(50)", existing)
        _add_column_if_missing(conn, "billing_history", "created_at", "created_at DATETIME", existing)
        _add_column_if_missing(conn, "billing_history", "updated_at", "updated_at DATETIME", existing)


def ensure_salary_history_schema():
    """Best-effort schema patch for salary_history table."""
    with db.engine.begin() as conn:
        existing = _table_columns(conn, "salary_history")

        _add_column_if_missing(conn, "salary_history", "employee_id", "employee_id INTEGER", existing)
        _add_column_if_missing(conn, "salary_history", "employee_name", "employee_name VARCHAR(120)", existing)
        _add_column_if_missing(conn, "salary_history", "salary_amount", "salary_amount INTEGER", existing)
        _add_column_if_missing(conn, "salary_history", "payment_type", "payment_type VARCHAR(20)", existing)
        _add_column_if_missing(conn, "salary_history", "payment_method", "payment_method VARCHAR(50)", existing)
        _add_column_if_missing(conn, "salary_history", "transaction_id", "transaction_id VARCHAR(100)", existing)
        _add_column_if_missing(conn, "salary_history", "transaction_date", "transaction_date DATETIME", existing)
        _add_column_if_missing(conn, "salary_history", "created_at", "created_at DATETIME", existing)
        _add_column_if_missing(conn, "salary_history", "updated_at", "updated_at DATETIME", existing)


def initialize_local_sqlite_data():
    """Seed local SQLite from local .sql dump only — never contacts MySQL."""
    if DB_BACKEND != "sqlite":
        return {"success": True, "skipped": True, "message": "Not using SQLite backend."}
    from db_sync import resolve_seed_dump

    dump = resolve_seed_dump()
    return seed_sqlite_from_dump(
        sqlite_path=SQLITE_DB_PATH,
        force=False,
        dump_path=dump,
    )


def backup_cron_loop():
    """Every hour, full backup (local file + MySQL) if 24h have passed."""
    while True:
        try:
            if DB_BACKEND == "sqlite" and BACKUP_AUTO_PUSH_ENABLED and should_auto_push(BACKUP_AUTO_PUSH_HOURS):
                with app.app_context():
                    app.logger.info("Auto backup due — local file + MySQL push...")
                    result = run_full_backup(
                        sqlite_path=SQLITE_DB_PATH,
                        mysql_uri=mysql_uri_from_env(),
                        label="auto",
                    )
                    if result.get("success"):
                        app.logger.info("Auto backup OK: %s", result.get("message"))
                    else:
                        app.logger.warning("Auto backup failed: %s", result.get("message"))
        except Exception as exc:
            app.logger.warning("Auto backup cron error: %s", exc)
        time.sleep(max(300, BACKUP_CRON_CHECK_SECONDS))


def start_backup_cronjob():
    """Start 24h auto-push worker (desktop / SQLite mode only)."""
    if DB_BACKEND != "sqlite":
        return
    if not BACKUP_AUTO_PUSH_ENABLED:
        app.logger.info("Backup auto-push disabled by config.")
        return
    if app.config.get("_backup_cron_started"):
        return
    worker = threading.Thread(target=backup_cron_loop, name="backup-cron-worker", daemon=True)
    worker.start()
    app.config["_backup_cron_started"] = True
    app.logger.info(
        "Backup auto-push started (every %sh, check every %ss).",
        BACKUP_AUTO_PUSH_HOURS,
        BACKUP_CRON_CHECK_SECONDS,
    )

def extract_attendance_events(payload):
    """Normalize attendance payload into an events list."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        events = payload.get("events")
        if events is not None:
            return events
        if payload.get("thumb_id"):
            return [payload]
    return []


def thumb_id_has_attendance_on_day(thumb_id, attendance_day):
    """Return True if thumb_id already has attendance on the given date."""
    if not thumb_id or not attendance_day:
        return False

    return Attendance.query.filter(
        Attendance.thumb_id == thumb_id,
        db.func.date(Attendance.check_in_at) == attendance_day,
    ).first() is not None


def process_attendance_events(
    events,
    source_fallback="zkteco_bridge",
    limit_to_today=False,
    one_per_day=True,
):
    """Insert attendance events and return ingestion summary."""
    if not isinstance(events, list) or not events:
        return {
            "success": False,
            "inserted": 0,
            "duplicates": 0,
            "invalid": 0,
            "unknown_ids": [],
            "error": "invalid_payload",
        }

    normalized_events = []
    for event in events:
        check_in_at = parse_check_in_at(event.get("check_in_at"))
        if not check_in_at:
            continue
        if limit_to_today and check_in_at.date() != date.today():
            continue
        normalized_events.append((event, check_in_at))

    if one_per_day:
        normalized_events.sort(key=lambda item: item[1])

    inserted = 0
    duplicates = 0
    unknown_ids = []
    invalid = 0
    batch_seen_days = set()

    for event, check_in_at in normalized_events:
        thumb_id = str(event.get("thumb_id", "")).strip()
        event_id = str(event.get("event_id", "")).strip() or None
        attendance_day = check_in_at.date()

        if not thumb_id:
            invalid += 1
            continue

        customer = Customer.query.filter_by(thumb_id=thumb_id).first()
        if not customer:
            unknown_ids.append(thumb_id)
            continue

        existing_log = Attendance.query.filter_by(customer_id=customer.id).first()
        if existing_log:
            existing_log.check_in_at = check_in_at
            existing_log.updated_at = datetime.utcnow()
            existing_log.source = str(event.get("source", source_fallback)).strip() or source_fallback
            existing_log.device_sn = str(event.get("device_sn", "")).strip() or None
            existing_log.raw_uid = str(event.get("raw_uid", "")).strip() or None
            existing_log.event_id = event_id
            db.session.add(existing_log)
            duplicates += 1
            continue

        attendance = Attendance(
            customer_id=customer.id,
            thumb_id=thumb_id,
            check_in_at=check_in_at,
            source=str(event.get("source", source_fallback)).strip() or source_fallback,
            device_sn=str(event.get("device_sn", "")).strip() or None,
            raw_uid=str(event.get("raw_uid", "")).strip() or None,
            event_id=event_id
        )
        db.session.add(attendance)
        inserted += 1

    db.session.commit()
    if unknown_ids:
        app.logger.warning("Unknown thumb IDs in attendance ingest: %s", ",".join(sorted(set(unknown_ids))))

    return {
        "success": True,
        "inserted": inserted,
        "duplicates": duplicates,
        "invalid": invalid,
        "unknown_ids": sorted(set(unknown_ids)),
    }


def fetch_attendance_events_from_url():
    """Fetch attendance payload from remote HTTP endpoint."""
    if not ATTENDANCE_FETCH_URL:
        return []

    headers = {}
    if ATTENDANCE_FETCH_API_KEY:
        headers["X-API-KEY"] = ATTENDANCE_FETCH_API_KEY

    response = requests.get(ATTENDANCE_FETCH_URL, headers=headers, timeout=20)
    response.raise_for_status()
    payload = response.json()
    events = extract_attendance_events(payload)
    return events if isinstance(events, list) else []


def fetch_attendance_events_from_zkteco():
    """Fetch attendance directly from ZKTeco device using pyzk."""
    if not ZK_IP:
        return []

    from zkteco_fetcher import fetch_zkteco_attendance_events

    return fetch_zkteco_attendance_events(
        ip=ZK_IP,
        port=ZK_PORT,
        timeout=ZK_TIMEOUT,
        password=ZK_PASSWORD,
    )


def attendance_source_configured():
    return bool(ZK_IP) or bool(ATTENDANCE_FETCH_URL)


def fetch_attendance_events_for_cron():
    """Fetch attendance from ZKTeco device first, otherwise HTTP URL."""
    if ZK_IP:
        return fetch_attendance_events_from_zkteco()
    return fetch_attendance_events_from_url()


def sync_attendance_now(source_fallback="manual_sync"):
    """Fetch attendance once and ingest into attendance table."""
    if not attendance_source_configured():
        return {
            "success": False,
            "inserted": 0,
            "duplicates": 0,
            "invalid": 0,
            "unknown_ids": [],
            "error": "fetch_not_configured",
        }

    events = fetch_attendance_events_for_cron()
    if not events:
        return {
            "success": True,
            "inserted": 0,
            "duplicates": 0,
            "invalid": 0,
            "unknown_ids": [],
            "message": "no_events",
        }

    return process_attendance_events(
        events,
        source_fallback=source_fallback,
        limit_to_today=True,
        one_per_day=True,
    )


def attendance_cron_loop():
    """Background polling loop to fetch and ingest attendance."""
    while True:
        try:
            with app.app_context():
                result = sync_attendance_now(source_fallback="cron_pull")
                if result.get("success") and (
                    result.get("inserted")
                    or result.get("duplicates")
                    or result.get("invalid")
                    or result.get("unknown_ids")
                ):
                    app.logger.info(
                        "Attendance cron sync: inserted=%s duplicates=%s invalid=%s unknown=%s",
                        result["inserted"],
                        result["duplicates"],
                        result["invalid"],
                        len(result["unknown_ids"])
                    )
        except Exception as exc:
            app.logger.warning("Attendance cron sync failed: %s", exc)

        time.sleep(max(30, ATTENDANCE_CRON_INTERVAL_SECONDS))


def start_attendance_cronjob():
    """Start daemon cron-like worker thread for attendance sync."""
    if not ATTENDANCE_CRON_ENABLED:
        app.logger.info("Attendance cron disabled by config.")
        return
    if not attendance_source_configured():
        app.logger.info("Attendance cron enabled but ZK_IP / ATTENDANCE_FETCH_URL is not configured; skipping startup.")
        return
    if app.config.get("_attendance_cron_started"):
        return

    worker = threading.Thread(target=attendance_cron_loop, name="attendance-cron-worker", daemon=True)
    worker.start()
    app.config["_attendance_cron_started"] = True
    source = f"zkteco://{ZK_IP}:{ZK_PORT}" if ZK_IP else ATTENDANCE_FETCH_URL
    app.logger.info(
        "Attendance cron started. interval=%ss source=%s",
        max(30, ATTENDANCE_CRON_INTERVAL_SECONDS),
        source
    )


# Flash route =====================================

@app.errorhandler(404)
def page_not_found(e):
    flash("Page not found. Redirected to home.", "warning")
    return redirect(url_for('dashboard'))

@app.route('/')
@login_required
def dashboard():
    today = datetime.utcnow().date()
    total_customers = Customer.query.count()
    active_customers = Customer.query.filter_by(status='Active').count()
    pending_billing_customers = Customer.query.filter(
        Customer.billing_date < today
    ).count()
    total_employees = Employee.query.count()
    trainers_count = Employee.query.filter_by(employment_type='Trainer').count()
    total_expense = db.session.query(db.func.sum(Expense.amount)).scalar() or 0
    office_boy_count = Employee.query.filter_by(employment_type='Office Boy').count()
    active_employees = Employee.query.filter_by(status='Active').count()
    personal_training_customers = Customer.query.filter(
    Customer.status == 'Active',
    or_(
        Customer.package.ilike('%personal%'),
        Customer.type.ilike('%personal%')
    )
).count()

    return render_template(
        'dashboard.html',
        total_customers=total_customers,
        active_customers=active_customers,
        pending_billing_customers=pending_billing_customers,
        total_employees=total_employees,
        trainers_count=trainers_count,
        office_boy_count=office_boy_count,
        personal_training_customers=personal_training_customers,
        total_expense=total_expense,
        active_employees=active_employees
    )

# Customer routes ==========================

@app.route('/customers')
@login_required
def customers():
    customers_list = Customer.query.all()
    
    # Fetch all packages and create a dict for quick lookup
    packages = Packages.query.all()
    packages_dict = {p.id: p for p in packages}
    from flask import get_flashed_messages
    messages = get_flashed_messages(with_categories=True)
    print("Flashed messages:", messages)
    # Pass packages_dict to the template
    today = date.today()
    
    def sort_key(c):
        if not c.billing_date:
            return (2, date.max)
        days_until = (c.billing_date - today).days
        is_active = c.status and c.status.lower() == 'active'
        is_due_soon = is_active and 0 <= days_until <= 2
        # Group 0: Active + billing within next 2 days -> top, soonest first
        # Group 1: everyone else -> sorted by billing date
        return (0 if is_due_soon else 1, c.billing_date)
    customers = sorted(customers_list, key=sort_key)
    return render_template(
        "customers.html",
        customers=customers,
        packages_dict=packages_dict,
        today=today
    )


def dedupe_attendance_by_membership(rows):
    """Keep only the latest attendance row per membership number per day."""
    seen = set()
    unique_rows = []
    for log, customer in rows:
        check_in_date = log.check_in_at.date() if log.check_in_at else None
        if customer and customer.membership_no:
            key = (customer.membership_no, check_in_date)
        else:
            key = (f"thumb:{log.thumb_id or log.id}", check_in_date)
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append((log, customer))
    return unique_rows


def build_attendance_query(q):
    query = db.session.query(Attendance, Customer).outerjoin(
        Customer, Attendance.thumb_id == Customer.thumb_id
    )

    if q:
        query = query.filter(
            db.or_(
                Customer.name.ilike(f"%{q}%"),
                Customer.membership_no.ilike(f"%{q}%"),
                Customer.cnic.ilike(f"%{q}%"),
                Customer.phone.ilike(f"%{q}%"),
                Attendance.thumb_id.ilike(f"%{q}%")
            )
        )

    return query.order_by(Attendance.check_in_at.desc())

def serialize_attendance_row(log, customer, today):
    pending_class = None
    pending_text = "N/A"

    if customer and customer.billing_date:
        days_left = (customer.billing_date - today).days
        if days_left < 0:
            pending_class = "pending-overdue"
            pending_text = f"Overdue by {-days_left} day{'s' if -days_left != 1 else ''}"
        elif days_left == 0:
            pending_class = "pending-due-today"
            pending_text = "Due today"
        elif days_left <= 2:
            pending_class = "pending-due-soon"
            pending_text = f"{days_left} day{'s' if days_left != 1 else ''} left"
        else:
            pending_class = "pending-ok"
            pending_text = f"{days_left} day{'s' if days_left != 1 else ''} left"

    return {
        "member_name": customer.name if customer else "Unknown (thumb not mapped)",
        "membership_no": customer.membership_no if customer else "N/A",
        "cnic": customer.cnic if customer else None,
        "thumb_id": log.thumb_id or "N/A",
        "check_in_at": log.check_in_at.strftime("%Y-%m-%d %H:%M:%S") if log.check_in_at else "N/A",
        "pending_class": pending_class,
        "pending_text": pending_text,
        # Show $ billing button for overdue, due today, or due within 2 days
        "billing_due": pending_class in (
            "pending-overdue",
            "pending-due-today",
            "pending-due-soon",
        ),
    }


# def serialize_attendance_row(log, customer, today):
#     pending_class = None
#     pending_text = "N/A"

#     if customer and customer.billing_date:
#         days_left = (customer.billing_date - today).days
#         if days_left < 0:
#             pending_class = "pending-overdue"
#             pending_text = f"Overdue by {-days_left} day{'s' if -days_left != 1 else ''}"
#         elif days_left <= 2:
#             pending_class = "pending-due-soon"
#             pending_text = "Due today" if days_left == 0 else f"{days_left} day{'s' if days_left != 1 else ''} left"
#         else:
#             pending_class = "pending-ok"
#             pending_text = f"{days_left} day{'s' if days_left != 1 else ''} left"

#     return {
#         "member_name": customer.name if customer else "Unknown (thumb not mapped)",
#         "membership_no": customer.membership_no if customer else "N/A",
#         "thumb_id": log.thumb_id or "N/A",
#         "check_in_at": log.check_in_at.strftime("%Y-%m-%d %H:%M:%S") if log.check_in_at else "N/A",
#         "pending_class": pending_class,
#         "pending_text": pending_text,
#     }


def get_attendance_page_data(q="", page=1, per_page=20):
    today = date.today()
    logs = build_attendance_query(q).all()
    logs = dedupe_attendance_by_membership(logs)

    total = len(logs)
    total_pages = max(1, ceil(total / per_page))
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    page_items = logs[start:start + per_page]

    rows = [
        serialize_attendance_row(log, customer, today)
        for log, customer in page_items
    ]
    return {
        "rows": rows,
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "per_page": per_page,
    }


@app.route('/attendance')
@login_required
def attendance():
    q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    page_data = get_attendance_page_data(q=q, page=page)

    return render_template(
        "attendance.html",
        page=page_data["page"],
        total_pages=page_data["total_pages"],
        total=page_data["total"],
        per_page=page_data["per_page"],
        q=q,
        auto_sync_seconds=ATTENDANCE_PAGE_AUTO_SYNC_SECONDS,
        initial_rows=page_data["rows"],
    )


@app.route('/attendance/data')
@login_required
def attendance_data():
    q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    should_sync = request.args.get('sync', '0') == '1'
    sync_result = None

    if should_sync and attendance_source_configured():
        try:
            sync_result = sync_attendance_now(source_fallback="auto_sync")
        except Exception as exc:
            app.logger.warning("Attendance auto sync failed: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    page_data = get_attendance_page_data(q=q, page=page)
    return jsonify({
        "success": True,
        "sync": sync_result,
        **page_data,
    })


@app.route('/attendance/sync', methods=['POST'])
@login_required
def attendance_sync_now():
    q = request.form.get('q', '').strip()
    page = request.form.get('page', '1').strip()
    auto_sync = (
        request.form.get('auto_sync') == '1'
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    )
    try:
        result = sync_attendance_now(source_fallback="auto_sync" if auto_sync else "manual_sync")
        if auto_sync:
            status_code = 200 if result.get("success") else 400
            return jsonify(result), status_code

        if not result.get("success"):
            if result.get("error") == "fetch_not_configured":
                flash("Attendance sync is not configured. Set ZK_IP or ATTENDANCE_FETCH_URL.", "error")
            else:
                flash("Attendance sync failed.", "error")
        elif result.get("message") == "no_events":
            flash("Sync completed. No new attendance events were returned.", "success")
        else:
            flash(
                (
                    f"Sync completed. Inserted: {result['inserted']}, "
                    f"Duplicates: {result['duplicates']}, Invalid: {result['invalid']}, "
                    f"Unknown thumb IDs: {len(result['unknown_ids'])}"
                ),
                "success"
            )
    except Exception as exc:
        app.logger.warning("Manual attendance sync failed: %s", exc)
        if auto_sync:
            return jsonify({"success": False, "error": str(exc)}), 500
        flash(f"Attendance sync failed: {exc}", "error")

    redirect_kwargs = {"q": q} if q else {}
    if page.isdigit() and int(page) > 1:
        redirect_kwargs["page"] = int(page)
    return redirect(url_for('attendance', **redirect_kwargs))


@app.route('/api/attendance/ingest', methods=['POST'])
def ingest_attendance():
    ingest_key = request.headers.get("X-INGEST-KEY", "")
    if not INGEST_SECRET:
        app.logger.error("ATTENDANCE_INGEST_KEY is not configured.")
        return jsonify({"success": False, "error": "ingest_not_configured"}), 500
    if ingest_key != INGEST_SECRET:
        return jsonify({"success": False, "error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    events = extract_attendance_events(payload)
    if not isinstance(events, list) or not events:
        return jsonify({"success": False, "error": "invalid_payload"}), 400

    result = process_attendance_events(
        events,
        source_fallback="zkteco_bridge",
        one_per_day=True,
    )
    app.logger.info(
        "Attendance ingest completed: inserted=%s duplicates=%s invalid=%s unknown=%s",
        result["inserted"],
        result["duplicates"],
        result["invalid"],
        len(result["unknown_ids"])
    )
    return jsonify(result), 200

@app.route('/update_customer_status/<int:customer_id>', methods=['POST'])
def update_customer_status(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    new_status = request.json.get('status')
    if new_status in ['active', 'inactive']:
        customer.status = new_status
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'success': False}), 400

@app.route('/check_cnic', methods=['POST'])
def check_cnic():
    cnic = request.form.get('cnic')
    exists = Customer.query.filter_by(cnic=cnic).first() is not None
    return jsonify({'exists': exists})


@app.route('/add_customer', methods=['GET', 'POST'])
def add_customer():
    form = CustomerForm()
    membership_no = generate_membership_no()
    referrer = request.referrer 


    # Determine if this registration is from a QR code
    is_qr = request.args.get('mode') == 'qr'

    if request.method == 'GET':
        # Detect if came from main site (not app subdomain)
        is_from_our_domain = referrer and 'usmanlateef.com' in referrer and not referrer.startswith('https://app.')
    else:
        # On POST, read from hidden field
        is_from_our_domain = request.form.get('from_domain') == '1'
    
        
    # Fetch packages and trainers as before
    all_packages = Packages.query.all()
    individual_packages = [(str(p.id), p.package_name) for p in all_packages if p.package_type == 'Individual']
    personal_packages = [(str(p.id), p.package_name) for p in all_packages if p.package_type == 'Personal Training']

    trainers = Employee.query.filter_by(employment_type='Trainer').all()
    form.trainer.choices = [(t.name, t.name) for t in trainers]

    # Set package choices based on training type
    if request.method == 'GET':
        form.training_type.data = 'Individual'
        if individual_packages:
            form.package.data = individual_packages[0][0]
    elif request.method == 'POST':
        if form.training_type.data == 'Personal':
            form.package.choices = personal_packages
        else:
            form.package.choices = individual_packages

    if form.training_type.data == 'Personal':
        form.package.choices = personal_packages
    else:
        form.package.choices = individual_packages

    if form.validate_on_submit():
        admission_date = form.admission_date.data
        package_id = int(form.package.data)
        package_obj = Packages.query.get(package_id)
        billing_date = admission_date
        customer_type = form.training_type.data

        if customer_type == 'Individual':
            trainer = None
            personal_training_time = None
        else:
            trainer = form.trainer.data
            personal_training_time = form.personal_training_time.data

        customer = Customer(
            membership_no=membership_no,
            status="Not Paid",
            type=customer_type,
            admission_date=admission_date,
            billing_date=billing_date,
            package_id=package_id,
            name=form.name.data,
            father_or_husband=form.father_or_husband.data,
            cnic=form.cnic.data,
            email=form.email.data,
            gender=form.gender.data,
            marital_status=form.marital_status.data,
            blood_group=form.blood_group.data,
            dob=form.dob.data,
            height=parse_float(form.height.data),
            weight=parse_float(form.weight.data),
            waist=parse_float(form.waist.data),
            profession=form.profession.data,
            nationality=form.nationality.data,
            address=form.address.data,
            phone=form.phone.data,
            emergency_contact=form.emergency_contact.data,
            personal_training_time=personal_training_time,
            trainer=trainer,
            bmi_test=form.bmi_test.data,
            bmi_value=parse_float(form.bmi_value.data),
            illnesses=parse_tagify(form.illnesses.data),
            join_reasons=parse_tagify(form.join_reasons.data),
            terms_accepted=form.terms_accepted.data
        )
        db.session.add(customer)
        db.session.commit()
        
        if is_qr:
            return redirect(url_for('registration_success', mode='qr'))
        elif is_from_our_domain:
            return redirect(url_for('registration_success', is_from_our_domain=1))
        elif referrer and 'app.usmanlateef.com/customers' in referrer:
            flash("Customer added successfully!", "success")
            return redirect(url_for('customers'))
        else:
            flash("Customer added successfully!", "success")
            return redirect(url_for('customers'))
        
    if is_qr:
        back_url = None  # Hide back button in QR mode
    elif is_from_our_domain:
        back_url = 'https://usmanlateef.com'
    else:
        back_url = url_for('customers')

    if not form.admission_date.data:
        form.admission_date.data = datetime.now().date()

    return render_template(
        'add_customer.html',
        form=form,
        membership_no=membership_no,
        trainers=trainers,
        admission_date=form.admission_date.data,
        individual_packages=individual_packages,
        personal_packages=personal_packages,
        is_qr=is_qr,
        is_from_our_domain=is_from_our_domain,
        back_url=back_url  # <--- Add this
    )
    
    
@app.route('/registration_success')
def registration_success():
    is_qr = request.args.get('mode') == 'qr'
    is_from_our_domain = request.args.get('is_from_our_domain') == '1'
    redirect_to = None
    if is_from_our_domain:
        redirect_to = 'https://usmanlateef.com'
    return render_template('registration_success.html', is_qr=is_qr, redirect_to=redirect_to)

@app.route('/customers/<cnic>')
@login_required
def manage_customer(cnic):
    customer = Customer.query.filter_by(cnic=cnic).first_or_404()
    employees = Employee.query.order_by(Employee.name).all()
    packages = Packages.query.all()
    packages_dict = {p.id: p for p in packages}

    # Get the actual package object for this customer (using package_id)
    pkg = packages_dict.get(customer.package_id)
    package_name = pkg.package_name if pkg else ''
    package_price = int(pkg.package_price) if pkg and pkg.package_price else 0
    registration_fees = int(pkg.registration_fees) if pkg and pkg.registration_fees else 0
    amount_to_be_paid = package_price + registration_fees

    # Preview next billing date: current billing (or admission) + package duration
    base_billing_date = customer.billing_date or customer.admission_date
    package_duration = pkg.package_duration if pkg else '1 Month'
    next_billing_date = get_billing_date(base_billing_date, package_duration) if base_billing_date else None

    return render_template(
        "manage_customer.html",
        customer=customer,
        packages_dict=packages_dict,
        package_name=package_name,
        package_price=package_price,
        registration_fees=registration_fees,
        amount_to_be_paid=amount_to_be_paid,
        employees=employees,
        next_billing_date=next_billing_date,
    )

@app.route('/edit_customer/<cnic>', methods=['GET', 'POST'])
@login_required
def edit_customer(cnic):
    customer = Customer.query.filter_by(cnic=cnic).first_or_404()
    form = CustomerForm(obj=customer)
    trainers = Employee.query.filter_by(employment_type='Trainer').all()
    form.trainer.choices = [(t.name, t.name) for t in trainers]

    # Fetch all packages for dropdowns (by type)
    all_packages = Packages.query.all()
    individual_packages = [(str(p.id), p.package_name) for p in all_packages if p.package_type == 'Individual']
    personal_packages = [(str(p.id), p.package_name) for p in all_packages if p.package_type == 'Personal Training']
    form._current_customer = customer

    # Determine type for initial render (GET or POST with errors)
    training_type = form.training_type.data or customer.type or 'Individual'
    if training_type == 'Personal':
        form.package.choices = personal_packages
    else:
        form.package.choices = individual_packages

    # On POST, update package choices based on selected type
    if request.method == 'POST':
        if form.training_type.data == 'Personal':
            form.package.choices = personal_packages
        else:
            form.package.choices = individual_packages

    if form.validate_on_submit():
        customer.name = form.name.data
        customer.father_or_husband = form.father_or_husband.data
        # CNIC is read-only and unique, so we do NOT update it here
        customer.email = form.email.data
        customer.gender = form.gender.data
        customer.marital_status = form.marital_status.data
        customer.blood_group = form.blood_group.data
        customer.dob = form.dob.data
        # Fetch the selected package object
        package_id = int(form.package.data)
        package_obj = Packages.query.get(package_id)

        # int fields - always parse!
        customer.height = parse_float(form.height.data)
        customer.weight = parse_float(form.weight.data)
        customer.waist = parse_float(form.waist.data)
        customer.bmi_value = parse_float(form.bmi_value.data)

        customer.profession = form.profession.data
        customer.nationality = form.nationality.data
        customer.address = form.address.data
        customer.phone = form.phone.data
        customer.emergency_contact = form.emergency_contact.data

        # Update package and type
        customer.type = form.training_type.data
        customer.package_id = int(form.package.data)
        customer.admission_date = form.admission_date.data
        if not customer.billing_date:
            customer.billing_date = customer.admission_date

        # Trainer logic
        if customer.type == 'Individual':
            customer.trainer = None
            customer.personal_training_time = None
        else:
            customer.trainer = form.trainer.data
            customer.personal_training_time = form.personal_training_time.data

        customer.bmi_test = form.bmi_test.data
        customer.illnesses = parse_tagify(form.illnesses.data)
        customer.join_reasons = parse_tagify(form.join_reasons.data)
        customer.terms_accepted = form.terms_accepted.data

        db.session.commit()
        flash("Customer updated successfully!", "success")
        return redirect(url_for('manage_customer', cnic=customer.cnic))

    # Pass package lists for JS
    return render_template(
        'edit_customer.html',
        form=form,
        customer=customer,
        trainers=trainers,
        individual_packages=individual_packages,
        personal_packages=personal_packages,
        edit_mode=True
    )

@app.route('/customers/<cnic>/register-fingerprint', methods=['POST'])
@login_required
def register_customer_fingerprint(cnic):
    customer = Customer.query.filter_by(cnic=cnic).first_or_404()

    try:
        result = register_or_enroll_customer_on_zkteco(customer)

        return jsonify({
            "success": True,
            "thumb_id": result["thumb_id"],
            "uid": result["uid"],
            "created": result["created"],
            "message": f"{result['message']} Thumb ID: {result['thumb_id']}"
        }), 200

    except Exception as exc:
        db.session.rollback()
        app.logger.exception("Fingerprint registration failed for customer cnic=%s", cnic)
        return jsonify({
            "success": False,
            "error": str(exc)
        }), 500



@app.route('/update_billing_date/<cnic>', methods=['POST'])
@login_required
def update_billing_date(cnic):
    customer = Customer.query.filter_by(cnic=cnic).first_or_404()
    new_billing_date = request.form.get('billing_date')
    
    if new_billing_date:
        customer.billing_date = datetime.strptime(new_billing_date, '%Y-%m-%d')
        customer.status = 'Active'  # Update status to Active
        db.session.commit()
        flash('Billing date updated and status set to active.', 'success')
    else:
        flash('Invalid billing date.', 'error')
    
    return redirect(url_for('manage_customer', cnic=cnic))



@app.route('/delete_customer/<cnic>', methods=['POST', 'GET'])
@login_required
def delete_customer(cnic):
    customer = Customer.query.filter_by(cnic=cnic).first_or_404()
    db.session.delete(customer)
    db.session.commit()
    flash("Customer deleted successfully!", "success")
    return redirect(url_for('customers'))

# @app.route('/update_status/<cnic>', methods=['POST'])
# @login_required
# def update_status(cnic):
#     customer = Customer.query.filter_by(cnic=cnic).first_or_404()

#     try:
#         package_obj = Packages.query.get(customer.package_id)

#         package_price = int(package_obj.package_price) if package_obj and package_obj.package_price else 0
#         registration_fees = int(float(request.form.get('registration_fees', 0) or 0))
#         discount_amount = int(float(request.form.get('discount_amount', 0) or 0))
#         paid_amount = int(float(request.form.get('paid_amount', 0) or 0))

#         total_amount = package_price + registration_fees
#         amount_after_discount = total_amount - discount_amount
#         remaining_amount = amount_after_discount - paid_amount
#         if remaining_amount < 0:
#             remaining_amount = 0

#         payment_collected_by = (request.form.get('collector_name') or '').strip()
#         payment_method = (request.form.get('payment_method') or '').strip()
#         transaction_id = (request.form.get('transaction_id') or '').strip()

#         # Preserve existing thumb_id unless a new non-empty one is explicitly submitted
#         submitted_thumb_id = (request.form.get('thumb_id') or '').strip()
#         if submitted_thumb_id:
#             duplicate = Customer.query.filter(
#                 Customer.thumb_id == submitted_thumb_id,
#                 Customer.id != customer.id
#             ).first()
#             if duplicate:
#                 flash('Thumb ID is already assigned to another customer.', 'error')
#                 return redirect(url_for('manage_customer', cnic=customer.cnic))
#             customer.thumb_id = submitted_thumb_id

#         customer.discount_amount = discount_amount

#         # Move billing date to same day next month
#         base_billing_date = customer.billing_date or datetime.today().date()
#         customer.billing_date = base_billing_date + relativedelta(months=1)

#         # Update customer status
#         if remaining_amount <= 0:
#             customer.status = 'active'
#         else:
#             customer.status = 'inactive'

#         # Update or create remaining amount entry
#         remaining_entry = RemainingAmount.query.filter_by(
#             membership_no=customer.membership_no
#         ).first()

#         if not remaining_entry:
#             remaining_entry = RemainingAmount(
#                 membership_no=customer.membership_no,
#                 remaining_amount=remaining_amount
#             )
#             db.session.add(remaining_entry)
#         else:
#             remaining_entry.remaining_amount = remaining_amount

#         # Create billing entry
#         billing = Billing(
#             customer_name=customer.name,
#             membership_no=customer.membership_no,
#             customer_cnic=customer.cnic,
#             paid_to_be_amount=amount_after_discount,
#             paid_amount=paid_amount,
#             remaining_amount=remaining_amount,
#             payment_collected_by=payment_collected_by,
#             payment_method=payment_method,
#             transaction_id=transaction_id if transaction_id else None,
#             discount_amount=discount_amount,
#             payment_date=datetime.utcnow()
#         )
#         db.session.add(billing)

#         # Create billing history entry
#         billing_history = BillingHistory(
#             customer_cnic=customer.cnic,
#             customer_name=customer.name,
#             membership_no=customer.membership_no,
#             amount_to_be_paid=amount_after_discount,
#             paid_amount=paid_amount,
#             remaining_amount=remaining_amount,
#             payment_collected_by=payment_collected_by,
#             payment_method=payment_method,
#             transaction_id=transaction_id if transaction_id else None,
#             payment_date=datetime.utcnow()
#         )
#         db.session.add(billing_history)

#         db.session.commit()
#         flash('Status and payment updated successfully.', 'success')
#         return redirect(url_for('manage_customer', cnic=customer.cnic))

#     except Exception as exc:
#         db.session.rollback()
#         flash(f'Failed to update customer status: {str(exc)}', 'error')
#         return redirect(url_for('manage_customer', cnic=customer.cnic))


@app.route('/update_status/<cnic>', methods=['POST'])
@login_required
def update_status(cnic):
    customer = Customer.query.filter_by(cnic=cnic).first_or_404()

    try:
        package_obj = Packages.query.get(customer.package_id)

        package_price = int(package_obj.package_price) if package_obj and package_obj.package_price else 0
        registration_fees = int(float(request.form.get('registration_fees', 0) or 0))
        discount_amount = int(float(request.form.get('discount_amount', 0) or 0))
        paid_amount = int(float(request.form.get('paid_amount', 0) or 0))

        total_amount = package_price + registration_fees
        amount_after_discount = total_amount - discount_amount
        remaining_amount = amount_after_discount - paid_amount
        if remaining_amount < 0:
            remaining_amount = 0

        payment_collected_by = (request.form.get('collector_name') or '').strip()
        payment_method = (request.form.get('payment_method') or '').strip()
        transaction_id = (request.form.get('transaction_id') or '').strip()

        submitted_thumb_id = (request.form.get('thumb_id') or '').strip()
        if submitted_thumb_id:
            duplicate = Customer.query.filter(
                Customer.thumb_id == submitted_thumb_id,
                Customer.id != customer.id
            ).first()
            if duplicate:
                flash('Thumb ID is already assigned to another customer.', 'error')
                return redirect(url_for('manage_customer', cnic=customer.cnic))
            customer.thumb_id = submitted_thumb_id

        customer.discount_amount = discount_amount

        # Billing date: use staff value if provided, otherwise auto-calculate
        # from current billing/admission + package duration.
        package_duration = package_obj.package_duration if package_obj else '1 Month'
        base_billing_date = customer.billing_date or customer.admission_date or datetime.today().date()
        auto_billing_date = get_billing_date(base_billing_date, package_duration)

        submitted_billing = (request.form.get('next_billing_date') or '').strip()
        if submitted_billing:
            customer.billing_date = datetime.strptime(submitted_billing, '%Y-%m-%d').date()
        else:
            customer.billing_date = auto_billing_date

        # Payment from Not Paid is a manual unpaid → active transition.
        # Remaining amount must not force inactive.
        customer.status = 'active'

        remaining_entry = RemainingAmount.query.filter_by(
            membership_no=customer.membership_no
        ).first()

        if not remaining_entry:
            remaining_entry = RemainingAmount(
                membership_no=customer.membership_no,
                remaining_amount=remaining_amount
            )
            db.session.add(remaining_entry)
        else:
            remaining_entry.remaining_amount = remaining_amount

        billing = Billing(
            customer_name=customer.name,
            membership_no=customer.membership_no,
            customer_cnic=customer.cnic,
            paid_to_be_amount=amount_after_discount,
            paid_amount=paid_amount,
            remaining_amount=remaining_amount,
            payment_collected_by=payment_collected_by,
            payment_method=payment_method,
            transaction_id=transaction_id if transaction_id else None,
            discount_amount=discount_amount,
            payment_date=datetime.utcnow()
        )
        db.session.add(billing)

        billing_history = BillingHistory(
            customer_cnic=customer.cnic,
            customer_name=customer.name,
            membership_no=customer.membership_no,
            amount_to_be_paid=amount_after_discount,
            paid_amount=paid_amount,
            remaining_amount=remaining_amount,
            payment_collected_by=payment_collected_by,
            payment_method=payment_method,
            transaction_id=transaction_id if transaction_id else None,
            payment_date=datetime.utcnow()
        )
        db.session.add(billing_history)

        db.session.commit()
        flash('Status and payment updated successfully.', 'success')
        return redirect(url_for('manage_customer', cnic=customer.cnic))

    except Exception as exc:
        db.session.rollback()
        flash(f'Failed to update customer status: {str(exc)}', 'error')
        return redirect(url_for('manage_customer', cnic=customer.cnic))

@app.route('/customer_billing/<cnic>')
@login_required
def customer_billing(cnic):
    billings = Billing.query.filter_by(membership_no=cnic).order_by(Billing.payment_date.desc()).all()
    return render_template('billing_history.html', billings=billings)

# login routes ========================

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        username = (form.username.data or "").strip()
        password = form.password.data or ""
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Incorrect credentials', 'error')
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# employee routes ==============

@app.route('/check_employee_cnic', methods=['POST'])
@login_required
def check_employee_cnic():
    cnic = request.form.get('cnic')
    exists = Employee.query.filter_by(cnic=cnic).first() is not None
    return jsonify({'exists': exists})

@app.route('/edit_employee/<int:employee_id>', methods=['POST'])
@login_required
def edit_employee(employee_id):
    if str(current_user.role_id) != '1':
        return abort(403)
    employee = Employee.query.get_or_404(employee_id)
    form = EmployeeForm(obj=employee)

    # Make sure CNIC is not edited
    form.cnic.data = employee.cnic

    if form.validate_on_submit():
        form.populate_obj(employee)
        employee.cnic = employee.cnic
        db.session.commit()
        flash('Employee updated successfully!', 'success')
    else:
        flash('There was an error updating the employee.', 'danger')
    return redirect(url_for('manage_employee', employee_id=employee.id))

@app.route('/edit_employee_by_cnic/<cnic>', methods=['POST'])
@login_required
def edit_employee_by_cnic(cnic):
    if str(current_user.role_id) != '1':
        return abort(403)
    employee = Employee.query.filter_by(cnic=cnic).first_or_404()
    form = EmployeeForm(request.form)
    form.employment_type.choices = [('Owner', 'Owner'), ('Trainer', 'Trainer'), ('Office Boy', 'Office Boy')]
    form.shift.choices = [('Morning', 'Morning'), ('Evening', 'Evening'), ('Night', 'Night')]
    form.status.choices = [('Active', 'Active'), ('Inactive', 'Inactive')]
    form.cnic.data = employee.cnic
    form._current_employee = employee

    if form.validate_on_submit():
        employee.name = form.name.data
        employee.employment_type = form.employment_type.data
        employee.phone_number = form.phone_number.data
        employee.timing = request.form.get('timing', '')  # Ensure this retrieves the correct value
        employee.shift = form.shift.data
        employee.salary = form.salary.data
        employee.status = form.status.data
        db.session.commit()
        flash('Employee updated successfully!', 'success')
    else:
        print("Form errors:", form.errors)
        flash('There was an error updating the employee.', 'danger')
    return redirect(url_for('manage_employee', employee_id=employee.id))


@app.route('/add_employee', methods=['POST'])
@login_required
def add_employee():
    if str(current_user.role_id) != '1':
        return abort(403)
    form = EmployeeForm()
    if form.validate_on_submit():
        new_employee = Employee(
            name=form.name.data,
            cnic=form.cnic.data,
            employment_type=form.employment_type.data,
            phone_number=form.phone_number.data,
            timing=form.timing.data,
            shift=form.shift.data,
            status=form.status.data,
            salary=form.salary.data
        )
        db.session.add(new_employee)
        db.session.commit()
        flash('Employee added successfully!', 'success')
    else:
        flash('Error adding employee. Please check your input.', 'danger')
    return redirect(url_for('employees'))

@app.route('/delete_employee/<int:employee_id>', methods=['POST', 'GET'])
@login_required
def delete_employee(employee_id):
    if str(current_user.role_id) != '1':
        return abort(403)
    employee = Employee.query.get_or_404(employee_id)
    db.session.delete(employee)
    db.session.commit()
    flash('Employee deleted successfully!', 'success')
    return redirect(url_for('employees'))

@app.route('/delete_salary_entry/<int:entry_id>', methods=['GET', 'POST'])
def delete_salary_entry(entry_id):
    entry = SalaryHistory.query.get_or_404(entry_id)
    db.session.delete(entry)
    db.session.commit()
    flash('Salary entry deleted successfully!', 'success')
    return redirect(url_for('manage_employee', employee_id=entry.employee_id))

@app.route('/employees')
@login_required
def employees():
    if str(current_user.role_id) != '1':
        abort(403)
    all_employees = Employee.query.all()
    form = EmployeeForm()  # create the form instance
    return render_template('employees.html', employees=all_employees, form=form)

@app.route('/employees/<int:employee_id>')
@login_required
def manage_employee(employee_id):
    if str(current_user.role_id) != '1':
        abort(403)
    employee = Employee.query.get_or_404(employee_id)
    form = EmployeeForm(obj=employee)
    salary_history = SalaryHistory.query.filter_by(employee_id=employee.id).order_by(SalaryHistory.transaction_date.desc()).all()
    # Now salary_history is defined, so this works:
    total_advance = sum(s.salary_amount for s in salary_history if s.payment_type == 'Advance')
    return render_template(
        'manage_employee.html',
        employee=employee,
        form=form,
        salary_history=salary_history,
        total_advance=total_advance
    )

# accounts page ===============

@app.route('/accounts')
@login_required
def accounts():
    period = request.args.get('period', '1m')
    custom_start = request.args.get('start')
    custom_end = request.args.get('end')

    today = datetime.utcnow()
    # Default values
    start_dt = today - timedelta(days=30)
    end_dt = today

    if period == '1m':
        start_dt = today - timedelta(days=30)
        end_dt = today
    elif period == '2m':
        start_dt = today - timedelta(days=60)
        end_dt = today
    elif period == '6m':
        start_dt = today - timedelta(days=180)
        end_dt = today
    elif period == '1y':
        start_dt = today - timedelta(days=365)
        end_dt = today
    elif period == 'custom':
        # Only use custom if both dates are given and valid
        try:
            if custom_start and custom_end:
                start_dt = datetime.strptime(custom_start, '%Y-%m-%d')
                end_dt = datetime.strptime(custom_end, '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
            else:
                # If missing, fallback to last 30 days
                start_dt = today - timedelta(days=30)
                end_dt = today
        except Exception:
            # If parsing fails, fallback to last 30 days
            start_dt = today - timedelta(days=30)
            end_dt = today

    # Filters
    bh_filter = (BillingHistory.payment_date >= start_dt) & (BillingHistory.payment_date <= end_dt)
    eh_filter = (Expense.date >= start_dt) & (Expense.date <= end_dt)
    sh_filter = (SalaryHistory.transaction_date >= start_dt) & (SalaryHistory.transaction_date <= end_dt)

    # Transaction-based, filtered stats
    total_sale = db.session.query(db.func.sum(BillingHistory.paid_amount)).filter(bh_filter).scalar() or 0
    total_expense = db.session.query(db.func.sum(Expense.amount)).filter(eh_filter).scalar() or 0
    total_salary = db.session.query(db.func.sum(SalaryHistory.salary_amount)).filter(sh_filter).scalar() or 0
    profit = total_sale - total_expense - total_salary

    online_payments = BillingHistory.query.filter(bh_filter, BillingHistory.payment_method=='Online').count()
    cash_payments = BillingHistory.query.filter(bh_filter, BillingHistory.payment_method=='Cash').count()
    cash_collected = db.session.query(db.func.sum(BillingHistory.paid_amount)).filter(bh_filter, BillingHistory.payment_method=='Cash').scalar() or 0
    cash_expense = db.session.query(db.func.sum(Expense.amount)).filter(eh_filter, Expense.payment_method=='Cash').scalar() or 0
    cash_salary = db.session.query(db.func.sum(SalaryHistory.salary_amount)).filter(sh_filter, SalaryHistory.payment_method=='Cash').scalar() or 0
    cash_in_hand = cash_collected - cash_expense - cash_salary

    # Snapshot stats (NOT filtered)
    active_customers = Customer.query.filter_by(status='Active').count()
    active_trainers = Employee.query.filter_by(employment_type='Trainer', status='Active').count()
    pt_customers = Customer.query.filter(
        Customer.status == 'Active',
        (Customer.package.ilike('%personal%') | Customer.type.ilike('%personal%'))
    ).count()
    total_remain = db.session.query(db.func.sum(Billing.remaining_amount)).scalar() or 0
    remain_customers = Billing.query.filter(Billing.remaining_amount > 0).count()

    return render_template(
        'accounts.html',
        active_customers=active_customers,
        active_trainers=active_trainers,
        total_sale=total_sale,
        pt_customers=pt_customers,
        total_expense=total_expense,
        total_salary=total_salary,
        profit=profit,
        online_payments=online_payments,
        cash_payments=cash_payments,
        total_remain=total_remain,
        remain_customers=remain_customers,
        cash_in_hand=cash_in_hand,
        start_date=start_dt.date(),
        end_date=end_dt.date(),
        period=period,
        custom_start=custom_start,
        custom_end=custom_end
    )

# Billing route ================

@app.route('/billing')
@login_required
def billing():
    billed_cnic = db.session.query(Billing.customer_cnic).distinct()
    billed_membership = db.session.query(Billing.membership_no).distinct()
    customers = Customer.query.filter(
        (Customer.cnic.in_(billed_cnic)) | (Customer.membership_no.in_(billed_membership))
    ).all()

    packages = Packages.query.all()
    packages_dict = {p.id: p for p in packages}

    billing_dict = {}
    for c in customers:
        billing = Billing.query.filter_by(customer_cnic=c.cnic).order_by(Billing.payment_date.desc()).first()
        billing_dict[c.cnic] = {
            'remaining_amount': billing.remaining_amount if billing else 0,
            'discount_amount': billing.discount_amount if billing else 0,
            'paid_to_be_amount': billing.paid_to_be_amount if billing else 0  # Fetch paid_to_be_amount
        }
    return render_template(
        'billing.html',
        customers=customers,
        packages_dict=packages_dict,
        billing_dict=billing_dict
    )

@app.route('/billing_payment_info/<cnic>', methods=['GET'])
@login_required
def billing_payment_info(cnic):
    """JSON payload for Add Payment modal (billing history logic)."""
    customer = Customer.query.filter_by(cnic=cnic).first_or_404()
    pkg = Packages.query.get(customer.package_id)
    package_price = int(pkg.package_price) if pkg and pkg.package_price else 0
    discount_amount = customer.discount_amount or 0

    billing = Billing.query.filter_by(customer_cnic=customer.cnic).order_by(Billing.payment_date.desc()).first()
    previous_remaining = billing.remaining_amount if billing else 0
    amount_to_be_paid = package_price - discount_amount + previous_remaining

    base_billing_date = customer.billing_date or customer.admission_date
    package_duration = pkg.package_duration if pkg else '1 Month'
    next_billing_date = get_billing_date(base_billing_date, package_duration) if base_billing_date else None

    employees = Employee.query.order_by(Employee.name).all()

    return jsonify({
        "success": True,
        "cnic": customer.cnic,
        "name": customer.name,
        "membership_no": customer.membership_no,
        "package_name": pkg.package_name if pkg else "",
        "package_price": package_price,
        "discount_amount": discount_amount,
        "previous_remaining": previous_remaining,
        "amount_to_be_paid": amount_to_be_paid,
        "current_billing_date": customer.billing_date.strftime("%Y-%m-%d") if customer.billing_date else "",
        "next_billing_date": next_billing_date.strftime("%Y-%m-%d") if next_billing_date else "",
        "submit_url": url_for("add_billing_history", cnic=customer.cnic),
        "employees": [{"name": e.name} for e in employees],
    })


@app.route('/billing_history/<cnic>', methods=['GET'])
@login_required
def billing_history(cnic):
    customer = Customer.query.filter_by(cnic=cnic).first_or_404()
    employees = Employee.query.all()
    pkg = Packages.query.get(customer.package_id)
    package_price = int(pkg.package_price) if pkg and pkg.package_price else 0
    discount_amount = customer.discount_amount or 0

    billing = Billing.query.filter_by(customer_cnic=customer.cnic).order_by(Billing.payment_date.desc()).first()
    previous_remaining = billing.remaining_amount if billing else 0
    current_balance = billing.remaining_amount if billing else 0
    amount_to_be_paid = package_price - discount_amount + previous_remaining

    history = BillingHistory.query.filter_by(customer_cnic=cnic).order_by(BillingHistory.payment_date.desc()).all()
    serialized_history = [serialize_billing_history(b) for b in history]

    # Preview next billing date for Add Payment form
    base_billing_date = customer.billing_date or customer.admission_date
    package_duration = pkg.package_duration if pkg else '1 Month'
    next_billing_date = get_billing_date(base_billing_date, package_duration) if base_billing_date else None

    return render_template(
        'billing_history.html',
        customer=customer,
        history=serialized_history,
        employees=employees,
        current_balance=current_balance,
        package_name=pkg.package_name if pkg else '',
        package_price=package_price,
        previous_remaining=previous_remaining,
        amount_to_be_paid=amount_to_be_paid,
        next_billing_date=next_billing_date,
    )


@app.route('/delete_billing_history/<int:billing_id>/<cnic>', methods=['POST'])
@login_required
def delete_billing_history(billing_id, cnic):
    # Fetch the billing history entry
    history = BillingHistory.query.get_or_404(billing_id)

    # Delete the billing history entry
    db.session.delete(history)
    db.session.commit()

    # Fetch and delete the corresponding entry from RemainingAmount
    remaining_entry = RemainingAmount.query.filter_by(membership_no=history.membership_no, remaining_amount=history.remaining_amount).first()
    if remaining_entry:
        db.session.delete(remaining_entry)
        db.session.commit()

    # Fetch the most recent remaining amount entry
    recent_remaining_entry = RemainingAmount.query.filter_by(membership_no=history.membership_no).order_by(RemainingAmount.created_at.desc()).first()

    # Update the billing record with the most recent remaining amount
    billing = Billing.query.filter_by(customer_cnic=cnic).first()
    if billing and recent_remaining_entry:
        billing.remaining_amount = recent_remaining_entry.remaining_amount
        db.session.commit()

    flash('Billing entry and corresponding remaining amount entry deleted.', 'success')
    return redirect(url_for('billing_history', cnic=cnic))

@app.route('/add_billing_history/<cnic>', methods=['POST'])
@login_required
def add_billing_history(cnic):
    customer = Customer.query.filter_by(cnic=cnic).first_or_404()
    pkg = Packages.query.get(customer.package_id)
    package_price = int(pkg.package_price) if pkg and pkg.package_price else 0
    discount_amount = customer.discount_amount or 0
    paid_amount = int(request.form.get('paid_amount', 0))
    payment_collected_by = request.form.get('payment_collected_by')
    payment_method = request.form.get('payment_method', 'Unknown')
    transaction_id = request.form.get('transaction_id', None)

    # Fetch the most recent remaining amount
    last_remaining_entry = RemainingAmount.query.filter_by(membership_no=customer.membership_no).order_by(RemainingAmount.created_at.desc()).first()
    last_remaining = last_remaining_entry.remaining_amount if last_remaining_entry else 0

    # Calculate new remaining amount
    amount_to_be_paid = package_price - discount_amount + last_remaining
    new_remaining = amount_to_be_paid - paid_amount  # Allow negative values

    # Billing date: use set date if provided, otherwise auto-calculate
    # from current billing/admission + package duration.
    package_duration = pkg.package_duration if pkg else '1 Month'
    base_billing_date = customer.billing_date or customer.admission_date or datetime.today().date()
    auto_billing_date = get_billing_date(base_billing_date, package_duration)
    submitted_billing = (request.form.get('billing_date') or '').strip()
    if submitted_billing:
        customer.billing_date = datetime.strptime(submitted_billing, '%Y-%m-%d').date()
    else:
        customer.billing_date = auto_billing_date

    # Do not change status from remaining amount.
    # Status only changes manually or via 7-day no-attendance rule.

    # Add new entry to RemainingAmount
    new_remaining_entry = RemainingAmount(
        membership_no=customer.membership_no,
        remaining_amount=new_remaining
    )
    db.session.add(new_remaining_entry)

    # Save new BillingHistory entry
    billing_history = BillingHistory(
        customer_cnic=customer.cnic,
        customer_name=customer.name,
        membership_no=customer.membership_no,
        amount_to_be_paid=amount_to_be_paid,
        paid_amount=paid_amount,
        remaining_amount=new_remaining,
        payment_collected_by=payment_collected_by,
        payment_method=payment_method,
        transaction_id=transaction_id,
        payment_date=datetime.utcnow()
    )
    db.session.add(billing_history)

    # Update or create Billing entry (for statement/balance)
    billing = Billing.query.filter_by(customer_cnic=customer.cnic).first()
    if not billing:
        billing = Billing(
            customer_name=customer.name,
            membership_no=customer.membership_no,
            customer_cnic=customer.cnic,
            paid_to_be_amount=amount_to_be_paid,
            paid_amount=paid_amount,
            remaining_amount=new_remaining,
            payment_collected_by=payment_collected_by,
            payment_method=payment_method,
            transaction_id=transaction_id,
            payment_date=datetime.utcnow()
        )
        db.session.add(billing)
    else:
        billing.paid_to_be_amount = amount_to_be_paid
        billing.paid_amount = paid_amount
        billing.remaining_amount = new_remaining
        billing.payment_collected_by = payment_collected_by
        billing.payment_method = payment_method
        billing.transaction_id = transaction_id
        billing.payment_date = datetime.utcnow()

    db.session.commit()

    wants_json = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.best == 'application/json'
        or request.args.get('format') == 'json'
    )
    if wants_json:
        return jsonify({
            "success": True,
            "message": "Payment added to billing history!",
            "billing_date": customer.billing_date.strftime("%Y-%m-%d") if customer.billing_date else None,
            "remaining_amount": new_remaining,
        })

    flash('Payment added to billing history!', 'success')
    next_url = (request.form.get('next') or '').strip()
    if next_url:
        return redirect(next_url)
    return redirect(url_for('billing_history', cnic=customer.cnic))

# # expense routes ==============

@app.route('/expenses', methods=['GET', 'POST'])
@login_required
def expenses():
    employees = Employee.query.all()
    expenses = Expense.query.order_by(Expense.date.desc()).all()
    total_expense = sum(e.amount for e in expenses)
    return render_template('expenses.html', expenses=expenses, employees=employees, total_expense=total_expense)

@app.route('/add_expense', methods=['POST'])
@login_required
def add_expense():
    name = request.form.get('name')
    description = request.form.get('description')
    amount = int(request.form.get('amount', 0))
    paid_by = request.form.get('paid_by')
    payment_method = request.form.get('payment_method')
    transaction_id = request.form.get('transaction_id') if payment_method == 'Online' else None

    expense = Expense(
        name=name,
        description=description,
        amount=amount,
        paid_by=paid_by,
        payment_method=payment_method,
        transaction_id=transaction_id
    )
    db.session.add(expense)
    db.session.commit()
    flash('Expense added successfully!', 'success')
    return redirect(url_for('expenses'))

@app.route('/delete_expense/<int:expense_id>', methods=['POST'])
@login_required
def delete_expense(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    db.session.delete(expense)
    db.session.commit()
    flash('Expense deleted.', 'success')
    return redirect(url_for('expenses'))

# package routes ==============

@app.route('/packages', methods=['GET', 'POST'])
@login_required
def packages():
    all_packages = Packages.query.order_by(Packages.id.desc()).all()

    if request.method == 'POST':
        mode = request.form.get('mode')
        name = request.form.get('package_name')
        package_type = request.form.get('package_type')
        duration = request.form.get('package_duration')
        price = request.form.get('package_price')
        registration_fees = request.form.get('registration_fees')

        if not (name and package_type and duration and price and registration_fees):
            return jsonify({'success': False, 'message': 'All fields are required.'})

        try:
            price = int(price)
            registration_fees = int(registration_fees)
        except ValueError:
            return jsonify({'success': False, 'message': 'Price and Registration Fees must be valid numbers.'})

        if mode == 'add':
            new_package = Packages(
                package_name=name,
                package_type=package_type,
                package_duration=duration,
                package_price=price,
                registration_fees=registration_fees
            )
            db.session.add(new_package)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Package added successfully.'})

        elif mode == 'update':
            package_id = request.form.get('package_id')
            package = Packages.query.get(package_id)
            if not package:
                return jsonify({'success': False, 'message': 'Package not found.'})
            package.package_name = name
            package.package_type = package_type
            package.package_duration = duration
            package.package_price = price
            package.registration_fees = registration_fees
            db.session.commit()
            return jsonify({'success': True, 'message': 'Package updated successfully.'})

    return render_template('packages.html', packages=all_packages)

@app.route('/delete_package/<int:package_id>', methods=['POST'])
@login_required
def delete_package(package_id):
    package = Packages.query.get_or_404(package_id)
    db.session.delete(package)
    db.session.commit()
    return jsonify({'success': True})

# terms and conditions route===========

@app.route('/terms')
def terms():
    return render_template('terms.html')

# customer management =========

@app.route('/mark_absent_inactive')
@login_required
def mark_absent_inactive():
    # Only allow admins
    if str(current_user.role_id) != '1':
        flash("Unauthorized", "danger")
        return redirect(url_for('dashboard'))

    cust_inactive_count = 0
    threshold_dt = datetime.utcnow() - timedelta(days=ATTENDANCE_INACTIVE_DAYS)

    # Customers
    customers = Customer.query.filter_by(status='Active').all()
    for customer in customers:
        latest_log = Attendance.query.filter(
            Attendance.customer_id == customer.id
        ).order_by(Attendance.check_in_at.desc()).first()
        if (not latest_log) or (latest_log.check_in_at < threshold_dt):
            customer.status = 'Inactive'
            cust_inactive_count += 1

    db.session.commit()
    flash(
        f"Marked {cust_inactive_count} customers as Inactive (no attendance in last {ATTENDANCE_INACTIVE_DAYS} days).",
        "success"
    )
    return redirect(url_for('dashboard'))

# salary routes ==============

@app.route('/pay_salary/<int:employee_id>', methods=['POST'])
@login_required
def pay_salary(employee_id):
    employee = Employee.query.get_or_404(employee_id)
    salary_amount = int(request.form.get('salary_amount', 0))
    payment_type = request.form.get('payment_type', 'Salary')
    payment_method = request.form.get('payment_method', 'Cash')
    transaction_id = request.form.get('transaction_id', None)
    salary_entry = SalaryHistory(
        employee_id=employee.id,
        employee_name=employee.name,
        salary_amount=salary_amount,
        payment_type=payment_type,
        payment_method=payment_method,
        transaction_id=transaction_id if payment_method == 'Online' else None,
        transaction_date=datetime.utcnow()
    )
    db.session.add(salary_entry)
    db.session.commit()
    flash('Salary record added!', 'success')
    return redirect(url_for('manage_employee', employee_id=employee.id))


# user loader for login manager =======

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# List users
@app.route('/users')
def users():
    all_users = User.query.all()
    return render_template('user_management.html', users=all_users)

# Add user
@app.route('/add_user', methods=['POST'])
def add_user():
    username = request.form.get('username').strip()
    role_id = request.form.get('role_id')
    password = request.form.get('password')
    confirm = request.form.get('confirm_password')

    # Validate role
    if role_id not in ['1', '2']:
        flash('Invalid role selected.', 'error')
        return redirect(url_for('users'))

    # Validate password
    if password != confirm:
        flash('Passwords do not match.', 'error')
        return redirect(url_for('users'))

    # Check existing username
    if User.query.filter_by(username=username).first():
        flash('Username already exists.', 'error')
        return redirect(url_for('users'))

    user = User(username=username, role_id=role_id)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    flash('User added successfully.', 'success')
    return redirect(url_for('users'))

# Edit user
@app.route('/edit_user/<int:user_id>', methods=['POST'])
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    username = request.form.get('username').strip()
    role_id = request.form.get('role_id')
    password = request.form.get('password')

    # Validate role
    if role_id not in ['1', '2']:
        flash('Invalid role selected.', 'error')
        return redirect(url_for('users'))

    user.username = username
    user.role_id = role_id
    if password:
        user.set_password(password)

    db.session.commit()
    flash('User updated successfully.', 'success')
    return redirect(url_for('users'))

# Delete user
@app.route('/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash('User deleted successfully.', 'success')
    return redirect(url_for('users'))

# Optional: Check username availability (AJAX)
@app.route('/check_username', methods=['POST'])
def check_username():
    username = request.form.get('username').strip()
    exists = User.query.filter_by(username=username).first() is not None
    return jsonify({'exists': exists})


# ========================
# Backup / Cloud sync (SQLite -> MySQL)
# ========================
@app.route('/backup')
@login_required
def backup_page():
    if str(current_user.role_id) != '1':
        flash('Access denied. Admins only.', 'error')
        return redirect(url_for('dashboard'))
    status = sync_status_summary(sqlite_path=SQLITE_DB_PATH) if DB_BACKEND == "sqlite" else {
        "meta": load_sync_meta(),
        "hours_since_last_push": hours_since_last_push(),
        "due_for_auto_push": False,
        "local_counts": {},
        "sqlite_path": None,
    }
    return render_template(
        'backup.html',
        db_backend=DB_BACKEND,
        auto_push_hours=BACKUP_AUTO_PUSH_HOURS,
        auto_push_enabled=BACKUP_AUTO_PUSH_ENABLED,
        status=status,
    )


@app.route('/backup/push', methods=['POST'])
@login_required
def backup_push_now():
    if str(current_user.role_id) != '1':
        return jsonify({"success": False, "message": "Access denied."}), 403
    if DB_BACKEND != "sqlite":
        return jsonify({
            "success": False,
            "message": "Backup is only available when the app runs on local SQLite.",
        }), 400

    # 1) Save local .sql + .db  2) Push to live MySQL
    result = run_full_backup(
        sqlite_path=SQLITE_DB_PATH,
        mysql_uri=mysql_uri_from_env(),
        label="manual",
    )
    code = 200 if result.get("success") else 500
    return jsonify(result), code


@app.route('/backup/reload-dump', methods=['POST'])
@login_required
def backup_reload_dump():
    """Re-import local .sql dump into SQLite (no MySQL connection)."""
    if str(current_user.role_id) != '1':
        return jsonify({"success": False, "message": "Access denied."}), 403
    if DB_BACKEND != "sqlite":
        return jsonify({
            "success": False,
            "message": "Reload dump is only available in SQLite mode.",
        }), 400

    from db_sync import resolve_seed_dump

    dump = resolve_seed_dump()
    result = seed_sqlite_from_dump(
        sqlite_path=SQLITE_DB_PATH,
        force=True,
        dump_path=dump,
    )
    code = 200 if result.get("success") else 500
    return jsonify(result), code


@app.route('/backup/status')
@login_required
def backup_status():
    if str(current_user.role_id) != '1':
        return jsonify({"success": False, "message": "Access denied."}), 403
    return jsonify({"success": True, **sync_status_summary(sqlite_path=SQLITE_DB_PATH)})


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        try:
            ensure_attendance_schema()
        except Exception as exc:
            app.logger.warning("Attendance schema sync skipped: %s", exc)
        try:
            ensure_billing_history_schema()
        except Exception as exc:
            app.logger.warning("Billing history schema sync skipped: %s", exc)
        try:
            ensure_salary_history_schema()
        except Exception as exc:
            app.logger.warning("Salary history schema sync skipped: %s", exc)
        try:
            seed_result = initialize_local_sqlite_data()
            if seed_result and not seed_result.get("skipped"):
                app.logger.info("SQLite seed: %s", seed_result.get("message"))
        except Exception as exc:
            app.logger.warning("SQLite seed skipped: %s", exc)
    start_attendance_cronjob()
    start_backup_cronjob()
    app.run(debug=True)

