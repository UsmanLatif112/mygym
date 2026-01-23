from app import app
from models import db, User


with app.app_context():
    db.create_all()  # Ensure tables exist

    # Change these values as you wish
    username = 'admin'
    password = 'admin123'
    role_id = 1

    if not User.query.filter_by(username=username).first():
        user = User(username=username, role_id=role_id)
        user.set_password(password)  # Or: user.password = generate_password_hash(password)
        db.session.add(user)
        db.session.commit()
        print(f'User created: {username} / {password} with role_id={role_id}')
    else:
        print('User already exists.')


# from app import app, db

# # Make sure this matches your new Billing model!
# from models import RemainingAmount

# with app.app_context():
#     # Drop the existing 'billing' table if it exists
#     RemainingAmount.__table__.drop(db.engine, checkfirst=True)
#     print("Dropped existing 'billing' table (if it existed).")

#     # Recreate the new 'billing' table
#     db.create_all()
#     print("Created new 'billing' table with updated schema.")

# from app import app, db
# from models import Billing

# with app.app_context():
#     # Drop the existing employee table if it exists
#     Billing.__table__.drop(db.engine, checkfirst=True)
#     print("Dropped existing Billing table.")

#     # Recreate the Billing table with the current model
#     db.create_all()
#     print("Created new Billing table with updated schema.")

# from app import app, db
# from models import Customer

# cnic = "12345-1234567-1"

# with app.app_context():
#     customer = Customer.query.filter_by(cnic=cnic).first()
#     if customer:
#         customer.status = "Active"
#         db.session.commit()
#         print(f"Status for CNIC {cnic} updated to Active.")
#     else:
#         print(f"Customer with CNIC {cnic} not found.")


# from app import app, db
# from models import Packages

# # --- Define all your packages ---
# package_data = [
#     # package_name, package_price, packgae_duration, registeration_fees
#     ("Individual_Monthly", "3500", "1 month", "2000"),
#     ("Individual_3Month", "9000", "3 month", "1000"),
#     ("Individual_6Month", "18000", "6 month", "0"),
#     ("Personal_Monthly", "13500", "1 month", "2000"),
#     ("Personal_3Month", "39000", "3 month", "1000"),
#     ("Personal_6Month", "68000", "6 month", "0")
# ]

# with app.app_context():
#     # Create the table if it doesn't exist
#     db.create_all()

#     # Clear out existing data (optional, only do if you want a fresh start)
#     Packages.query.delete()
#     db.session.commit()

#     # Insert the packages
#     for name, price, duration, fees in package_data:
#         # Check if package already exists to avoid duplicates
#         exists = Packages.query.filter_by(package_name=name).first()
#         if not exists:
#             pkg = Packages(
#                 package_name=name,
#                 package_price=price,
#                 packgae_duration=duration,
#                 registeration_fees=fees
#             )
#             db.session.add(pkg)
#     db.session.commit()
#     print("Packages table created and data inserted.")


# # from app import app, db
# # from models import Packages

# # with app.app_context():
# #     # Drop the table
# #     Packages.__table__.drop(db.engine)
# #     # Re-create it with the new column
# #     db.create_all()
# #     print("Table dropped and recreated!")



# from app import app, db

# class Employee(db.Model):
#     id = db.Column(db.Integer, primary_key=True)
#     name = db.Column(db.String(100), nullable=False)
#     status = db.Column(db.String(50), nullable=False)            # e.g. 'Active', 'Inactive'
#     employment_type = db.Column(db.String(50), nullable=False)   # e.g. 'Full Time', 'Part Time', 'Contract'
#     timing = db.Column(db.String(50), nullable=True)             # e.g. '09:00 - 17:00'
#     shift = db.Column(db.String(50), nullable=True)              # e.g. 'Morning', 'Evening'

#     def __repr__(self):
#         return f"<Employee {self.name}>"

# if __name__ == "__main__":
#     with app.app_context():
#         db.create_all()
#         print("Employee table created (if it didn't exist already)!")


# from app import app, db
# from models import employee

# with app.app_context():
#     # Drop the table
#     employee.__table__.drop(db.engine)
# #     # Re-create it with the new column
# #     db.create_all()
# #     print("Table dropped and recreated!")



# from app import app, db
# from models import Customer
# from datetime import datetime

# with app.app_context():
#     membership_no = '202512-002'
#     new_billing_date = datetime.strptime('2025-12-22', '%Y-%m-%d').date()
    
#     customer = Customer.query.filter_by(membership_no=membership_no).first()
#     if customer:
#         customer.billing_date = new_billing_date
#         db.session.commit()
#         print(f"Updated billing date for membership_no {membership_no} to {new_billing_date}")
#     else:
#         print(f"No customer found with membership_no {membership_no}")



#  @app.route('/update_status/<cnic>', methods=['POST'])
# @login_required
# def update_status(cnic):
#     customer = Customer.query.filter_by(cnic=cnic).first_or_404()
#     package_obj = Packages.query.get(customer.package_id)

#     package_price = float(package_obj.package_price) if package_obj and package_obj.package_price else 0
#     registration_fees = float(request.form.get('registration_fees', 0))
#     total_amount = package_price + registration_fees
#     paid_amount = float(request.form.get('paid_amount', 0))
#     remaining_amount = total_amount - paid_amount
#     next_billing_date = request.form.get('next_billing_date')
#     payment_collected_by = request.form.get('collector_name')
#     payment_method = request.form.get('payment_method', 'Unknown')
#     transaction_id = request.form.get('transaction_id', None)

#     # Update customer billing date and status
#     if next_billing_date:
#         customer.billing_date = datetime.strptime(next_billing_date, '%Y-%m-%d')
#     customer.status = 'Active'

#     # Update or create remaining amount
#     remaining_entry = RemainingAmount.query.filter_by(membership_no=customer.membership_no).first()
#     if not remaining_entry:
#         remaining_entry = RemainingAmount(membership_no=customer.membership_no, remaining_amount=remaining_amount)
#         db.session.add(remaining_entry)
#     else:
#         remaining_entry.remaining_amount = remaining_amount

#     # Save billing record
#     billing = Billing(
#         customer_name=customer.name,
#         membership_no=customer.membership_no,
#         customer_cnic=customer.cnic,
#         paid_to_be_amount=total_amount,
#         paid_amount=paid_amount,
#         remaining_amount=remaining_entry.remaining_amount,
#         payment_collected_by=payment_collected_by,
#         payment_method=payment_method,
#         transaction_id=transaction_id if transaction_id else None,
#         payment_date=datetime.utcnow()
#     )
#     db.session.add(billing)

#     # Save billing history record
#     billing_history = BillingHistory(
#         customer_cnic=customer.cnic,
#         customer_name=customer.name,
#         membership_no=customer.membership_no,
#         amount_to_be_paid=total_amount,
#         paid_amount=paid_amount,
#         remaining_amount=remaining_entry.remaining_amount,
#         payment_collected_by=payment_collected_by,
#         payment_method=payment_method,
#         transaction_id=transaction_id if transaction_id else None,
#         payment_date=datetime.utcnow()
#     )
#     db.session.add(billing_history)

#     db.session.commit()
#     flash('Status and payment updated successfully.', 'success')
#     return redirect(url_for('manage_customer', cnic=customer.cnic))
