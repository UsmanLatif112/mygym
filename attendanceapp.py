from app import app, db
from models import Customer, Attendance
from datetime import datetime, timedelta

with app.app_context():
    inactive_days = 30
    threshold_dt = datetime.utcnow() - timedelta(days=inactive_days)

    # --- For Customers only ---
    customers = Customer.query.filter_by(status='Active').all()
    cust_inactive_count = 0
    for customer in customers:
        latest_log = Attendance.query.filter(
            Attendance.customer_id == customer.id
        ).order_by(Attendance.check_in_at.desc()).first()
        if (not latest_log) or (latest_log.check_in_at < threshold_dt):
            customer.status = 'Inactive'
            cust_inactive_count += 1

    db.session.commit()
    print(f"Marked {cust_inactive_count} customers as Inactive due to no attendance in the last {inactive_days} days.")
    