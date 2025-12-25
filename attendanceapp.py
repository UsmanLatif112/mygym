from app import app, db
from models import Customer, Employee, Attendance
from flask import jsonify

with app.app_context():
    # --- For Customers ---
    customers = Customer.query.filter_by(status='Active').all()
    cust_inactive_count = 0
    for customer in customers:
        # If no attendance exists for this customer's thumb_id or cnic, mark as inactive
        attendance_exists = Attendance.query.filter(
            (Attendance.thumb_id == customer.thumb_id)  # assuming attendance has thumb_id field
        ).first()
        if not attendance_exists:
            customer.status = 'Inactive'
            cust_inactive_count += 1

    # --- For Employees ---
    employees = Employee.query.filter_by(status='Active').all()
    emp_inactive_count = 0
    for employee in employees:
        attendance_exists = Attendance.query.filter(
            (Attendance.thumb_id == employee.thumb_id)
        ).first()
        if not attendance_exists:
            employee.status = 'Inactive'
            emp_inactive_count += 1

    db.session.commit()
    print(f"Marked {cust_inactive_count} customers and {emp_inactive_count} employees as Inactive due to no attendance record.")
    