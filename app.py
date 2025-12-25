from flask import Flask, render_template, redirect, url_for, request, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from models import db, User, Customer, Billing, Packages,Employee, Attendance
from models import db, User, Customer, Billing, Packages, Employee, Attendance

from forms import LoginForm, CustomerForm, EmployeeForm
from datetime import datetime
import json
from dateutil.relativedelta import relativedelta
from flask import redirect, url_for
from sqlalchemy import or_
from flask import request, jsonify

from helper import parse_float, get_billing_date, parse_tagify, get_customer_type, generate_membership_no

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///mygym.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'


@app.route('/check_employee_cnic', methods=['POST'])
@login_required
def check_employee_cnic():
    cnic = request.form.get('cnic')
    exists = Employee.query.filter_by(cnic=cnic).first() is not None
    return jsonify({'exists': exists})

@app.errorhandler(404)
def page_not_found(e):
    flash("Page not found. Redirected to home.", "warning")
    return redirect(url_for('dashboard'))

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@app.route('/')
@login_required
def dashboard():
    today = datetime.utcnow().date()

    # 1. Total customers
    total_customers = Customer.query.count()

    # 2. Active customers
    active_customers = Customer.query.filter_by(status='Active').count()

    # 3. Pending billing (billing_date < today)
    pending_billing_customers = Customer.query.filter(
        Customer.billing_date < today
    ).count()

    # 4. Total employees
    total_employees = Employee.query.count()

    # 5. Trainer count
    trainers_count = Employee.query.filter_by(employment_type='Trainer').count()

    # 6. Office boy count
    office_boy_count = Employee.query.filter_by(employment_type='Office Boy').count()

    # 7. Customers with Personal Training
    # (Assumes personal training is in the package or type field, adjust as needed)
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
        personal_training_customers=personal_training_customers
    )

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password')
    return render_template('login.html', form=form)

@app.route('/customers')
@login_required
def customers():
    customers_list = Customer.query.all()
    from flask import get_flashed_messages
    messages = get_flashed_messages(with_categories=True)
    print("Flashed messages:", messages)   # <-- See in terminal
    return render_template("customers.html", customers=customers_list)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

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

@app.route('/edit_employee/<int:employee_id>', methods=['GET', 'POST'])
@login_required
def edit_employee(employee_id):
    if str(current_user.role_id) != '1':
        return abort(403)
    # Add your edit logic here
    # For now, just show a placeholder
    return f"Edit employee with ID {employee_id}"

@app.route('/delete_employee/<int:employee_id>', methods=['POST', 'GET'])
@login_required
def delete_employee(employee_id):
    if str(current_user.role_id) != '1':
        return abort(403)
    # You may want to check permissions here (e.g. role_id)
    employee = Employee.query.get_or_404(employee_id)
    db.session.delete(employee)
    db.session.commit()
    flash('Employee deleted successfully!', 'success')
    return redirect(url_for('employees'))



@app.route('/add_customer', methods=['GET', 'POST'])
@login_required
def add_customer():
    form = CustomerForm()
    membership_no = generate_membership_no()
    admission_date = datetime.now().date()
    billing_date = get_billing_date(admission_date, form.package.data)
    customer_type = get_customer_type(form.package.data)
    package = form.package.data
    
    if package and package.startswith('Individual'):    
        trainer = None  # or '' if your DB prefers empty string
        personal_training_time = None
    else:
        trainer = form.trainer.data
        personal_training_time = form.personal_training_time.data

    if form.validate_on_submit():
        illnesses = parse_tagify(form.illnesses.data)
        join_reasons = parse_tagify(form.join_reasons.data)

        customer = Customer(
            membership_no=membership_no,
            status="Not Paid",
            type=customer_type, 
            admission_date=admission_date,
            billing_date=billing_date,
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
            package=package,
            personal_training_time=personal_training_time,
            trainer=trainer,
            bmi_test=form.bmi_test.data,
            bmi_value=parse_float(form.bmi_value.data),
            illnesses=illnesses,
            join_reasons=join_reasons,
            terms_accepted=form.terms_accepted.data
        )
        db.session.add(customer)
        db.session.commit()
        print(f"User {customer.name} added successfully!")
        flash("Customer added successfully!", "success")
        return redirect(url_for('customers'))

    return render_template(
        'add_customer.html',
        form=form,
        membership_no=membership_no,
        admission_date=admission_date
    )

@app.route('/terms')
def terms():
    return render_template('terms.html')

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
    return render_template('manage_employee.html', employee=employee)


@app.route('/customers/<cnic>')
@login_required
def manage_customer(cnic):
    customer = Customer.query.filter_by(cnic=cnic).first_or_404()
    employees = Employee.query.order_by(Employee.name).all()
    # Find the matching package price
    package_obj = Packages.query.filter_by(package_name=customer.package).first()
    amount_to_be_paid = int(package_obj.package_price) if package_obj else 0

    # (You can also calculate paid_amount and remaining_amount if you track payments)
    paid_amount = 0
    remaining_amount = amount_to_be_paid - paid_amount

    return render_template(
        "manage_customer.html",
        customer=customer,
        amount_to_be_paid=amount_to_be_paid,
        remaining_amount=remaining_amount,
        employees=employees,
        paid_amount=paid_amount
        
    )

@app.route('/edit_customer/<cnic>', methods=['GET', 'POST'])
@login_required
def edit_customer(cnic):
    customer = Customer.query.filter_by(cnic=cnic).first_or_404()
    form = CustomerForm(obj=customer)
    form._current_customer = customer
    customer.package = form.package.data
    if customer.package.startswith('Individual'):
        customer.trainer = None
        customer.personal_training_time = None
    else:
        customer.trainer = form.trainer.data
        customer.personal_training_time = form.personal_training_time.data

    if form.validate_on_submit():
        customer.name = form.name.data
        customer.father_or_husband = form.father_or_husband.data
        # CNIC is read-only and unique, so we do NOT update it here
        customer.email = form.email.data
        customer.gender = form.gender.data
        customer.marital_status = form.marital_status.data
        customer.blood_group = form.blood_group.data
        customer.dob = form.dob.data

        # Float fields - always parse!
        customer.height = parse_float(form.height.data)
        customer.weight = parse_float(form.weight.data)
        customer.waist = parse_float(form.waist.data)
        customer.bmi_value = parse_float(form.bmi_value.data)

        customer.profession = form.profession.data
        customer.nationality = form.nationality.data
        customer.address = form.address.data
        customer.phone = form.phone.data
        customer.emergency_contact = form.emergency_contact.data
        customer.package = customer.package
        customer.personal_training_time = customer.personal_training_time
        customer.trainer = customer.trainer
        customer.bmi_test = form.bmi_test.data

        # Tagify fields - parse as comma-separated string
        customer.illnesses = parse_tagify(form.illnesses.data)
        customer.join_reasons = parse_tagify(form.join_reasons.data)

        # Terms accepted (checkbox)
        customer.terms_accepted = form.terms_accepted.data

        db.session.commit()
        flash("Customer updated successfully!", "success")
        return redirect(url_for('manage_customer', cnic=customer.cnic))


    return render_template('edit_customer.html', form=form, customer=customer, edit_mode=True)



@app.route('/delete_customer/<cnic>', methods=['POST', 'GET'])
@login_required
def delete_customer(cnic):
    customer = Customer.query.filter_by(cnic=cnic).first_or_404()
    db.session.delete(customer)
    db.session.commit()
    flash("Customer deleted successfully!", "success")
    return redirect(url_for('customers'))


@app.route('/update_status/<cnic>', methods=['POST'])
@login_required
def update_status(cnic):
    customer = Customer.query.filter_by(cnic=cnic).first_or_404()

    # Fetch the package price for this customer
    package_obj = Packages.query.filter_by(package_name=customer.package).first()
    amount_to_be_paid = float(package_obj.package_price) if package_obj and package_obj.package_price else 0

    paid_amount = float(request.form.get('paid_amount', 0))
    remaining_amount = amount_to_be_paid - paid_amount
    payment_collected_by = request.form.get('collector_name')
    payment_method = request.form.get('payment_method', 'Unknown')

    # Save billing record
    billing = Billing(
        customer_name=customer.name,
        membership_no=customer.membership_no,
        paid_to_be_amount=amount_to_be_paid,
        paid_amount=paid_amount,
        remaining_amount=remaining_amount,
        payment_collected_by=payment_collected_by,
        payment_method=payment_method,
        payment_date=datetime.utcnow()
    )
    db.session.add(billing)

    # Update customer status
    customer.status = 'Active'
    db.session.commit()

    flash('Status and payment updated successfully.', 'success')
    return redirect(url_for('manage_customer', cnic=customer.cnic))


@app.route('/mark_absent_inactive')
@login_required
def mark_absent_inactive():
    # Only allow admins
    if str(current_user.role_id) != '1':
        flash("Unauthorized", "danger")
        return redirect(url_for('dashboard'))

    cust_inactive_count = emp_inactive_count = 0

    # Customers
    customers = Customer.query.filter_by(status='Active').all()
    for customer in customers:
        attendance_exists = Attendance.query.filter(
            Attendance.thumb_id == customer.thumb_id
        ).first()
        if not attendance_exists:
            customer.status = 'Inactive'
            cust_inactive_count += 1

    # Employees
    employees = Employee.query.filter_by(status='Active').all()
    for employee in employees:
        attendance_exists = Attendance.query.filter(
            Attendance.thumb_id == employee.thumb_id
        ).first()
        if not attendance_exists:
            employee.status = 'Inactive'
            emp_inactive_count += 1

    db.session.commit()
    flash(f"Marked {cust_inactive_count} customers and {emp_inactive_count} employees as Inactive (no attendance on record).", "success")
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)

