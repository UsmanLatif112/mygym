from flask import Flask, render_template, redirect, url_for, request, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from models import BillingHistory, db, User, Customer, Billing, Packages,Employee, Attendance
from models import db, User, Customer, Billing, Packages, Employee, Attendance, Expense, SalaryHistory, RemainingAmount
from forms import LoginForm, CustomerForm, EmployeeForm
from datetime import datetime
import json
from dateutil.relativedelta import relativedelta
from flask import redirect, url_for
from sqlalchemy import or_
from flask import request, jsonify
from datetime import datetime, timedelta
from helper import parse_float, get_billing_date, parse_tagify, get_customer_type, generate_membership_no, serialize_billing_history



app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///mygym.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'


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
    # Fetch all packages and create a dict for quick lookup
    packages = Packages.query.all()
    packages_dict = {p.id: p for p in packages}
    from flask import get_flashed_messages
    messages = get_flashed_messages(with_categories=True)
    print("Flashed messages:", messages)
    # Pass packages_dict to the template
    return render_template("customers.html", customers=customers_list, packages_dict=packages_dict)

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

    # Determine if this registration is from a QR code
    is_qr = request.args.get('mode') == 'qr'

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
        billing_date = get_billing_date(admission_date, package_obj.package_duration)
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
        else:
            flash("Customer added successfully!", "success")
            return redirect(url_for('customers'))

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
        is_qr=is_qr
    )

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
    package_price = float(pkg.package_price) if pkg and pkg.package_price else 0
    registration_fees = float(pkg.registration_fees) if pkg and pkg.registration_fees else 0
    amount_to_be_paid = package_price + registration_fees

    return render_template(
        "manage_customer.html",
        customer=customer,
        packages_dict=packages_dict,
        package_name=package_name,
        package_price=package_price,
        registration_fees=registration_fees,
        amount_to_be_paid=amount_to_be_paid,
        employees=employees,
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

        # Update package and type
        customer.type = form.training_type.data
        customer.package_id = int(form.package.data)
        customer.admission_date = form.admission_date.data
        customer.billing_date = get_billing_date(customer.admission_date, package_obj.package_duration)

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
    package_obj = Packages.query.get(customer.package_id)

    package_price = float(package_obj.package_price) if package_obj and package_obj.package_price else 0
    registration_fees = float(request.form.get('registration_fees', 0))
    total_amount = package_price + registration_fees
    paid_amount = float(request.form.get('paid_amount', 0))
    remaining_amount = total_amount - paid_amount
    next_billing_date = request.form.get('next_billing_date')
    payment_collected_by = request.form.get('collector_name')
    payment_method = request.form.get('payment_method', 'Unknown')
    transaction_id = request.form.get('transaction_id', None)

    # Update customer billing date and status
    if next_billing_date:
        customer.billing_date = datetime.strptime(next_billing_date, '%Y-%m-%d')
    customer.status = 'Active'

    # Update or create remaining amount
    remaining_entry = RemainingAmount.query.filter_by(membership_no=customer.membership_no).first()
    if not remaining_entry:
        remaining_entry = RemainingAmount(membership_no=customer.membership_no, remaining_amount=remaining_amount)
        db.session.add(remaining_entry)
    else:
        remaining_entry.remaining_amount = remaining_amount

    # Save billing record
    billing = Billing(
        customer_name=customer.name,
        membership_no=customer.membership_no,
        customer_cnic=customer.cnic,
        paid_to_be_amount=total_amount,
        paid_amount=paid_amount,
        remaining_amount=remaining_entry.remaining_amount,
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
        amount_to_be_paid=total_amount,
        paid_amount=paid_amount,
        remaining_amount=remaining_entry.remaining_amount,
        payment_collected_by=payment_collected_by,
        payment_method=payment_method,
        transaction_id=transaction_id if transaction_id else None,
        payment_date=datetime.utcnow()
    )
    db.session.add(billing_history)

    db.session.commit()
    flash('Status and payment updated successfully.', 'success')
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
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'error')
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
        billing_dict[c.cnic] = billing.remaining_amount if billing else 0

    return render_template(
        'billing.html',
        customers=customers,
        packages_dict=packages_dict,
        billing_dict=billing_dict
    )

@app.route('/billing_history/<cnic>', methods=['GET'])
@login_required
def billing_history(cnic):
    customer = Customer.query.filter_by(cnic=cnic).first_or_404()
    employees = Employee.query.all()
    pkg = Packages.query.get(customer.package_id)
    package_price = float(pkg.package_price) if pkg and pkg.package_price else 0

    billing = Billing.query.filter_by(customer_cnic=customer.cnic).order_by(Billing.payment_date.desc()).first()
    previous_remaining = billing.remaining_amount if billing else 0
    current_balance = billing.remaining_amount if billing else 0
    amount_to_be_paid = package_price + previous_remaining

    history = BillingHistory.query.filter_by(customer_cnic=cnic).order_by(BillingHistory.payment_date.desc()).all()
    serialized_history = [serialize_billing_history(b) for b in history]

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
    package_price = float(pkg.package_price) if pkg and pkg.package_price else 0
    paid_amount = float(request.form.get('paid_amount', 0))
    payment_collected_by = request.form.get('payment_collected_by')
    payment_method = request.form.get('payment_method', 'Unknown')
    transaction_id = request.form.get('transaction_id', None)

    # Fetch the most recent remaining amount
    last_remaining_entry = RemainingAmount.query.filter_by(membership_no=customer.membership_no).order_by(RemainingAmount.created_at.desc()).first()
    last_remaining = last_remaining_entry.remaining_amount if last_remaining_entry else 0

    # Calculate new remaining amount
    amount_to_be_paid = package_price + last_remaining
    new_remaining = max(amount_to_be_paid - paid_amount, 0)

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
    flash('Payment added to billing history!', 'success')
    return redirect(url_for('billing_history', cnic=customer.cnic))

# expense routes ==============

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
            price = float(price)
            registration_fees = float(registration_fees)
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

# salary routes ==============

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

# registration success page =======

@app.route('/registration_success')
def registration_success():
    is_qr = request.args.get('mode') == 'qr'
    return render_template('registration_success.html', is_qr=is_qr)

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

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)

