from flask import Flask, render_template, redirect, url_for, request, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from models import BillingHistory, db, User, Customer, Billing, Packages,Employee, Attendance
from models import db, User, Customer, Billing, Packages, Employee, Attendance, Expense, SalaryHistory

from forms import LoginForm, CustomerForm, EmployeeForm
from datetime import datetime
import json
from dateutil.relativedelta import relativedelta
from flask import redirect, url_for
from sqlalchemy import or_
from flask import request, jsonify

from datetime import datetime, timedelta

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


from flask import render_template, request, redirect, url_for, flash
from models import Employee
from forms import EmployeeForm
from app import db

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
            flash('Invalid username or password', 'error')
    return render_template('login.html', form=form)

@app.route('/customers')
@login_required
def customers():
    q = request.args.get('q', '').strip()
    query = Customer.query
    if q:
        query = query.filter(
            db.or_(
                Customer.name.ilike(f"%{q}%"),
                Customer.membership_no.ilike(f"%{q}%"),
                Customer.cnic.ilike(f"%{q}%"),
                Customer.phone.ilike(f"%{q}%")
            )
        )
    customers_list = query.all()
    from flask import get_flashed_messages
    messages = get_flashed_messages(with_categories=True)
    print("Flashed messages:", messages)   # <-- See in terminal
    return render_template("customers.html", customers=customers_list)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/edit_employee_by_cnic/<cnic>', methods=['POST'])
@login_required
def edit_employee_by_cnic(cnic):
    if str(current_user.role_id) != '1':
        return abort(403)
    employee = Employee.query.filter_by(cnic=cnic).first_or_404()
    form = EmployeeForm(request.form)
    # Set choices for SelectFields (as before)
    form.employment_type.choices = [('Owner', 'Owner'), ('Trainer', 'Trainer'), ('Office Boy', 'Office Boy')]
    form.shift.choices = [('Morning', 'Morning'), ('Evening', 'Evening'), ('Night', 'Night')]
    form.status.choices = [('Active', 'Active'), ('Inactive', 'Inactive')]
    form.cnic.data = employee.cnic
    form._current_employee = employee  # <-- This disables uniqueness check

    if form.validate_on_submit():
        employee.name = form.name.data
        employee.employment_type = form.employment_type.data
        employee.phone_number = form.phone_number.data
        employee.timing = form.timing.data
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

# @app.route('/delete_employee/<int:employee_id>', methods=['POST', 'GET'])
# @login_required
# def delete_employee(employee_id):
#     if str(current_user.role_id) != '1':
#         return abort(403)
#     # You may want to check permissions here (e.g. role_id)
#     employee = Employee.query.get_or_404(employee_id)
#     db.session.delete(employee)
#     db.session.commit()
#     flash('Employee deleted successfully!', 'success')
#     return redirect(url_for('employees'))


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


@app.route('/add_customer', methods=['GET', 'POST'])
@login_required
def add_customer():
    form = CustomerForm()
    membership_no = generate_membership_no()
    admission_date = datetime.now().date()
    billing_date = get_billing_date(admission_date, form.package.data)
    customer_type = get_customer_type(form.package.data)
    package = form.package.data
    trainers = Employee.query.filter_by(employment_type='Trainer').all()
    # Set trainer choices for the form
    form.trainer.choices = [(t.name, t.name) for t in trainers]
    
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
        trainers=trainers,
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
    trainers = Employee.query.filter_by(employment_type='Trainer').all()
    form.trainer.choices = [('', 'Select Trainer')] + [(t.name, t.name) for t in trainers]
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


    return render_template('edit_customer.html', form=form, customer=customer, trainers=trainers, edit_mode=True)



# @app.route('/delete_customer/<cnic>', methods=['POST', 'GET'])
# @login_required
# def delete_customer(cnic):
#     customer = Customer.query.filter_by(cnic=cnic).first_or_404()
#     db.session.delete(customer)
#     db.session.commit()
#     flash("Customer deleted successfully!", "success")
#     return redirect(url_for('customers'))


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

    package_obj = Packages.query.filter_by(package_name=customer.package).first()
    amount_to_be_paid = float(package_obj.package_price) if package_obj and package_obj.package_price else 0

    paid_amount = float(request.form.get('paid_amount', 0))
    remaining_amount = amount_to_be_paid - paid_amount
    payment_collected_by = request.form.get('collector_name')
    payment_method = request.form.get('payment_method', 'Unknown')
    transaction_id = request.form.get('transaction_id', None)

    # Save billing record
    billing = Billing(
        customer_name=customer.name,
        membership_no=customer.membership_no,
        customer_cnic=customer.cnic,
        paid_to_be_amount=amount_to_be_paid,
        paid_amount=paid_amount,
        remaining_amount=remaining_amount,
        payment_collected_by=payment_collected_by,
        payment_method=payment_method,
        transaction_id=transaction_id if transaction_id else None,
        payment_date=datetime.utcnow()
    )
    db.session.add(billing)

    # Save billing history record
    billing_history = BillingHistory(
        customer_cnic=customer.cnic,
        customer_name=customer.name,
        membership_no=customer.membership_no,
        amount_to_be_paid=amount_to_be_paid,
        paid_amount=paid_amount,
        remaining_amount=remaining_amount,
        payment_collected_by=payment_collected_by,
        payment_method=payment_method,
        transaction_id=transaction_id if transaction_id else None,
        payment_date=datetime.utcnow()
    )
    db.session.add(billing_history)

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



@app.route('/customer_billing/<cnic>')
@login_required
def customer_billing(cnic):
    billings = Billing.query.filter_by(membership_no=cnic).order_by(Billing.payment_date.desc()).all()
    return render_template('billing_history.html', billings=billings)

@app.route('/billing')
@login_required
def billing():
    if str(current_user.role_id) != '1':
        abort(403)
    billed_cnic = db.session.query(Billing.customer_cnic).distinct()
    billed_membership = db.session.query(Billing.membership_no).distinct()
    customers = Customer.query.filter(
        (Customer.cnic.in_(billed_cnic)) | (Customer.membership_no.in_(billed_membership))
    ).all()

    packages = Packages.query.all()
    packages_dict = {p.package_name: p for p in packages}

    # Fetch latest billing record for each customer
    billing_dict = {}
    for c in customers:
        billing = Billing.query.filter_by(customer_cnic=c.cnic).order_by(Billing.payment_date.desc()).first()
        billing_dict[c.cnic] = billing.remaining_amount if billing else 0

    return render_template(
        'billing.html',
        customers=customers,
        packages_dict=packages_dict,
        billing_dict=billing_dict
    )



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


@app.route('/billing_history/<cnic>', methods=['GET'])
@login_required
def billing_history(cnic):
    if str(current_user.role_id) != '1':
        abort(403)
    customer = Customer.query.filter_by(cnic=cnic).first_or_404()
    history = BillingHistory.query.filter_by(customer_cnic=cnic).order_by(BillingHistory.payment_date.desc()).all()
    employees = Employee.query.all()
    packages = Packages.query.all()
    packages_dict = {p.package_name: p for p in packages}

    # get last remain
    last_billing = history[0] if history else None
    prev_remain = last_billing.remaining_amount if last_billing else 0
    package_obj = packages_dict.get(customer.package)
    package_price = float(package_obj.package_price) if package_obj else 0
    amount_to_be_paid = package_price + prev_remain

    total_remaining = history[0].remaining_amount if history else 0

    return render_template(
        'billing_history.html',
        customer=customer,
        history=history,
        now=datetime.utcnow(),
        employees=employees,
        packages_dict=packages_dict,
        total_remaining=total_remaining,
        amount_to_be_paid=amount_to_be_paid
    )


@app.route('/delete_billing_history/<int:billing_id>/<cnic>', methods=['POST'])
@login_required
def delete_billing_history(billing_id, cnic):
    if str(current_user.role_id) != '1':
        abort(403)
    history = BillingHistory.query.get_or_404(billing_id)
    db.session.delete(history)
    db.session.commit()
    flash('Billing entry deleted.', 'success')
    return redirect(url_for('billing_history', cnic=cnic))

@app.route('/add_billing_history/<cnic>', methods=['POST'])
@login_required
def add_billing_history(cnic):
    if str(current_user.role_id) != '1':
        abort(403)
    customer = Customer.query.filter_by(cnic=cnic).first_or_404()

    # Get last remaining from BillingHistory
    last_billing = BillingHistory.query.filter_by(customer_cnic=customer.cnic).order_by(BillingHistory.payment_date.desc()).first()
    prev_remain = last_billing.remaining_amount if last_billing else 0

    # Get package price
    package_obj = Packages.query.filter_by(package_name=customer.package).first()
    package_price = float(package_obj.package_price) if package_obj else 0

    # Rolling amount to be paid
    amount_to_be_paid = package_price + prev_remain
    paid_amount = float(request.form.get('paid_amount', 0))
    remaining_amount = amount_to_be_paid - paid_amount

    payment_collected_by = request.form.get('payment_collected_by')
    payment_method = request.form.get('payment_method', 'Unknown')
    transaction_id = request.form.get('transaction_id', None)
    payment_date = datetime.utcnow()

    # 1. Add to BillingHistory
    billing_history = BillingHistory(
        customer_cnic=customer.cnic,
        customer_name=customer.name,
        membership_no=customer.membership_no,
        amount_to_be_paid=amount_to_be_paid,
        paid_amount=paid_amount,
        remaining_amount=remaining_amount,
        payment_collected_by=payment_collected_by,
        payment_method=payment_method,
        transaction_id=transaction_id if transaction_id else None,
        payment_date=payment_date
    )
    db.session.add(billing_history)

    # 2. Update or create Billing record
    billing = Billing.query.filter_by(customer_cnic=customer.cnic).first()
    if not billing:
        billing = Billing(
            customer_name=customer.name,
            membership_no=customer.membership_no,
            customer_cnic=customer.cnic,
            paid_to_be_amount=amount_to_be_paid,
            paid_amount=paid_amount,
            remaining_amount=remaining_amount,
            payment_collected_by=payment_collected_by,
            payment_method=payment_method,
            transaction_id=transaction_id if transaction_id else None,
            payment_date=payment_date
        )
        db.session.add(billing)
    else:
        billing.customer_name = customer.name
        billing.membership_no = customer.membership_no
        billing.paid_to_be_amount = amount_to_be_paid
        billing.paid_amount = paid_amount
        billing.remaining_amount = remaining_amount
        billing.payment_collected_by = payment_collected_by
        billing.payment_method = payment_method
        billing.transaction_id = transaction_id if transaction_id else None
        billing.payment_date = payment_date
        # No need to add to session, it's already tracked

    db.session.commit()
    flash('Payment added to billing history!', 'success')
    return redirect(url_for('billing_history', cnic=customer.cnic))


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
    amount = float(request.form.get('amount', 0))
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

@app.route('/pay_salary/<int:employee_id>', methods=['POST'])
@login_required
def pay_salary(employee_id):
    employee = Employee.query.get_or_404(employee_id)
    salary_amount = float(request.form.get('salary_amount', 0))
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



if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)

