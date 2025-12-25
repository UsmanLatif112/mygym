from flask_wtf import FlaskForm
from wtforms import StringField, StringField, PasswordField, SubmitField, FloatField, SelectField, DateField, BooleanField, SelectMultipleField, TextAreaField, RadioField
from wtforms.validators import DataRequired, Email, Length, Optional, Regexp,  ValidationError
import re
from models import Customer,Employee


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class CustomerForm(FlaskForm):
    name = StringField('Full Name', validators=[DataRequired(), Length(min=2, max=120)])
    father_or_husband = StringField('Father/Husband Name', validators=[DataRequired(), Length(min=2, max=120)])
    # cnic = StringField('CNIC', validators=[DataRequired(), Regexp(r'^[0-9]{14}$', message="Please enter a valid 13-digit CNIC"),Length(min=14, max=16)])
    cnic = StringField('CNIC', validators=[DataRequired()])

    def validate_cnic(self, field):
        cnic = field.data.strip()
        # CNIC with dashes: 12345-1234567-1 (16 chars)
        if '-' in cnic:
            if len(cnic) != 15 and len(cnic) != 16:  # Some users copy with/without extra dash
                raise ValidationError('CNIC with dashes must be 15-16 characters long.')
            if not re.match(r'^\d{5}-\d{7}-\d$', cnic):
                raise ValidationError('CNIC format should be 12345-1234567-1')
        else:
            if len(cnic) != 13:
                raise ValidationError('CNIC without dashes must be 13 digits.')
            if not cnic.isdigit():
                raise ValidationError('CNIC without dashes must be all digits.')
        # Uniqueness check
        existing = Customer.query.filter_by(cnic=cnic).first()
        # Only raise error if the CNIC belongs to a different customer
        if existing and (not hasattr(self, '_current_customer') or existing.id != self._current_customer.id):
            raise ValidationError('This customer already exists.')
    email = StringField('Email', validators=[DataRequired(), Email()])
    gender = SelectField('Gender', choices=[('Male','Male'),('Female','Female'),('Other','Other')], validators=[DataRequired()])
    marital_status = SelectField('Marital Status', choices=[('Married','Married'),('Single','Single'),('Other','Other')], validators=[DataRequired()])
    blood_group = SelectField('Blood Group', choices=[('A+','A+'),('A-','A-'),('B+','B+'),('B-','B-'),('O+','O+'),('O-','O-'),('AB+','AB+'),('AB-','AB-')], validators=[Optional()])
    dob = DateField('Date of Birth', validators=[DataRequired()], format='%Y-%m-%d')
    height = FloatField('Height (cm)', validators=[DataRequired()])
    weight = FloatField('Weight (kg)', validators=[DataRequired()])
    waist = FloatField('Waist (cm)', validators=[Optional()])
    profession = StringField('Profession', validators=[Optional()])
    nationality = StringField('Nationality', validators=[Optional()])
    address = StringField('Address', validators=[DataRequired()])
    phone = StringField('Phone Number', validators=[DataRequired(), Length(min=11, max=14)])
    emergency_contact = StringField('Emergency Contact No', validators=[DataRequired(), Length(min=11, max=14)])
    package = SelectField('Package', choices=[
        ('Individual_Monthly','Individual - 1 Month'),
        ('Individual_3Month','Individual - 3 Months'),
        ('Individual_6Month','Individual - 6 Months'),
        ('Personal_Monthly','Personal Training - 1 Month'),
        ('Personal_3Month','Personal Training - 3 Months'),
        ('Personal_6Month','Personal Training - 6 Months'),
    ], validators=[DataRequired()])
    personal_training_time = StringField('Preferred Training Time', validators=[Optional()])
    trainer = SelectField('Trainer', choices=[('Trainer 1', 'Trainer 1'), ('Trainer 2','Trainer 2'), ('Trainer 3','Trainer 3')], validators=[Optional()])
    bmi_test = SelectField('BMI Test', choices=[('No', 'No'), ('Yes', 'Yes')], default='No', validators=[DataRequired()])
    bmi_value = StringField('BMI Value', validators=[Optional()])
    illnesses = StringField('Do you suffer from any of these illnesses?')
    join_reasons = StringField('Why do you want to join?')
    terms_accepted = BooleanField('I accept the', validators=[DataRequired()])
    submit = SubmitField('Add Customer')



class EmployeeForm(FlaskForm):
    name = StringField('Employee Name', validators=[DataRequired()])
    cnic = StringField('CNIC', validators=[DataRequired()])

    def validate_cnic(self, field):
        cnic = field.data.strip()
        # CNIC format check (same as yours)
        if '-' in cnic:
            if len(cnic) != 15 and len(cnic) != 16:
                raise ValidationError('CNIC with dashes must be 15-16 characters long.')
            if not re.match(r'^\d{5}-\d{7}-\d$', cnic):
                raise ValidationError('CNIC format should be 12345-1234567-1')
        else:
            if len(cnic) != 13:
                raise ValidationError('CNIC without dashes must be 13 digits.')
            if not cnic.isdigit():
                raise ValidationError('CNIC without dashes must be all digits.')
        # Uniqueness check in Employee table
        existing = Employee.query.filter_by(cnic=cnic).first()
        # Only raise error if the CNIC belongs to a different employee (for edit support)
        if existing and (not hasattr(self, '_current_employee') or existing.id != self._current_employee.id):
            raise ValidationError('This employee already exists.')

    employment_type = SelectField('Employment Type', choices=[('Owner', 'Owner'), ('Trainer', 'Trainer'), ('Office Boy', 'Office Boy')], validators=[DataRequired()])
    timing = StringField('Timing')
    shift = SelectField('Shift', choices=[('Morning', 'Morning'), ('Evening', 'Evening'), ('Night', 'Night')], validators=[DataRequired()])
    salary = FloatField('Salary')
    status = SelectField('Status', choices=[('Active', 'Active'), ('Inactive', 'Inactive')], validators=[DataRequired()])
    submit = SubmitField('Add Employee')
