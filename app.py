import os
from pathlib import Path
from functools import wraps
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

from utils import (
    apply_optional_updates,
    delete_photo,
    form_value,
    form_values,
    save_uploaded_photo,
    send_notification_to_student,
)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'data.db'
UPLOAD_FOLDER = BASE_DIR / 'uploads'
UPLOAD_FOLDER.mkdir(exist_ok=True)

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET', 'replace-this-with-a-secret')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)

db = SQLAlchemy(app)

ROLE_LABELS = {
    'student': 'Student',
    'department': 'Department',
    'library': 'Library',
    'finance': 'Finance',
    'dormitory': 'Dormitory',
    'registrar': 'Registrar',
    'admin': 'Admin',
}

# endpoint, url rule, role, application status column, flash label
APPROVAL_OFFICES = (
    ('department_approve', '/department/approve', 'department', 'department_status', 'Department'),
    ('library_approve', '/library/approve', 'library', 'library_status', 'Library'),
    ('finance_approve', '/finance/approve', 'finance', 'finance_status', 'Finance'),
    ('dormitary_approve', '/dormitary/approve', 'dormitory', 'dormitory_status', 'Dormitory'),
    ('registrar_approve', '/registrar/approve', 'registrar', 'registrar_status', 'Registrar'),
)

STAGE_STATUS_FIELDS = [office[3] for office in APPROVAL_OFFICES]

LEGACY_PHP_ROUTES = (
    ('/index.php', 'index'),
    ('/login.php', 'login'),
    ('/register.php', 'register'),
    ('/logout.php', 'logout'),
    ('/admin/dashboard.php', 'admin_dashboard'),
    ('/student/status.php', 'student_status'),
)

STUDENT_EDITABLE_FIELDS = {
    'full_name': 'full_name',
    'email': 'email',
    'student_id': 'student_id_value',
    'department': 'department',
}

APPLICATION_EDITABLE_FIELDS = {
    'purpose': 'purpose',
    'academic_year': 'academic_year',
    'status': 'status',
}

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default='student')
    student_id = db.Column(db.String(50), nullable=True)
    department = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    applications = db.relationship('ClearanceApplication', cascade='all, delete-orphan', passive_deletes=True)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class ClearanceApplication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    purpose = db.Column(db.String(255), nullable=False)
    academic_year = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')
    department_status = db.Column(db.String(20), nullable=False, default='pending')
    library_status = db.Column(db.String(20), nullable=False, default='pending')
    finance_status = db.Column(db.String(20), nullable=False, default='pending')
    dormitory_status = db.Column(db.String(20), nullable=False, default='pending')
    registrar_status = db.Column(db.String(20), nullable=False, default='pending')
    remarks = db.Column(db.Text, nullable=True)
    photo_path = db.Column(db.String(255), nullable=True)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    approved_by = db.Column(db.String(100), nullable=True)
    user = db.relationship('User', foreign_keys=[user_id])

    def refresh_status(self):
        statuses = [getattr(self, field) for field in STAGE_STATUS_FIELDS]
        if 'rejected' in statuses:
            self.status = 'rejected'
        elif all(value == 'approved' for value in statuses):
            self.status = 'approved'
        else:
            self.status = 'pending'

def create_account(full_name, email, password, role, department=None, phone=None, student_id=None):
    user = User(
        full_name=full_name,
        email=email,
        password_hash=generate_password_hash(password),
        role=role,
        student_id=student_id,
        department=department,
        phone=phone,
    )
    db.session.add(user)
    db.session.commit()
    return user

def account_error(full_name, email, password, missing_message='Please fill all required fields.'):
    """Return a flash message when the submitted account details are unusable."""
    if not full_name or not email or not password:
        return missing_message
    if User.query.filter_by(email=email).first():
        return 'An account with this email already exists.'
    return None

def ensure_default_admin():
    """Create the bootstrap administrator account when it is missing."""
    if User.query.filter_by(email='admin@mau.edu.ng').first():
        return None
    return create_account(
        full_name='System Administrator',
        email='admin@mau.edu.ng',
        password='Admin@123',
        role='admin',
        student_id='ADM001',
        department='Administration',
        phone='07000000000',
    )

with app.app_context():
    db.create_all()
    table_info = db.session.execute(db.text('PRAGMA table_info(clearance_application)')).fetchall()
    columns = [column[1] for column in table_info]
    if 'photo_path' not in columns:
        db.session.execute(db.text('ALTER TABLE clearance_application ADD COLUMN photo_path VARCHAR(255)'))
        db.session.commit()
    ensure_default_admin()

def current_user():
    if 'user_id' not in session:
        return None
    return User.query.get(session['user_id'])

def applications_query(**filters):
    """Applications ordered newest first, optionally narrowed by column filters."""
    query = ClearanceApplication.query
    if filters:
        query = query.filter_by(**filters)
    return query.order_by(ClearanceApplication.submitted_at.desc())

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped

def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user or user.role not in roles:
                return redirect(url_for('login'))
            return view(*args, **kwargs)
        return wrapped
    return decorator

def role_dashboard(role):
    return {
        'student': 'student_dashboard',
        'department': 'department_approve',
        'library': 'library_approve',
        'finance': 'finance_approve',
        'dormitory': 'dormitary_approve',
        'registrar': 'registrar_approve',
        'admin': 'admin_dashboard',
    }.get(role, 'index')

@app.context_processor
def inject_globals():
    return {
        'current_user': current_user(),
        'role_labels': ROLE_LABELS,
    }

@app.route('/')
def index():
    if current_user():
        return redirect(url_for(role_dashboard(current_user().role)))
    return render_template('index.html')

def make_legacy_redirect(endpoint):
    def view():
        return redirect(url_for(endpoint))
    return view

for legacy_path, target_endpoint in LEGACY_PHP_ROUTES:
    app.add_url_rule(legacy_path, f'legacy_{target_endpoint}_php', make_legacy_redirect(target_endpoint))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user():
        return redirect(url_for(role_dashboard(current_user().role)))
    if request.method == 'POST':
        email = form_value('email')
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['role'] = user.role
            flash('Welcome back!', 'success')
            return redirect(url_for(role_dashboard(user.role)))
        flash('Invalid email or password.', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        full_name, email, phone, department = form_values('full_name', 'email', 'phone', 'department')
        password = request.form.get('password', '')
        error = account_error(full_name, email, password)
        if error:
            flash(error, 'danger')
        else:
            create_account(
                full_name=full_name,
                email=email,
                password=password,
                role='student',
                student_id=f'STU{int(datetime.utcnow().timestamp())}',
                department=department,
                phone=phone,
            )
            flash('Student account created successfully. You can now log in.', 'success')
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/register/office', methods=['GET', 'POST'])
def register_office():
    if request.method == 'POST':
        full_name, email, phone, role = form_values('full_name', 'email', 'phone', 'role')
        password = request.form.get('password', '')
        if role not in {'department', 'library', 'dormitary', 'registrar'}:
            flash('Please choose an office role.', 'danger')
        else:
            error = account_error(full_name, email, password)
            if error:
                flash(error, 'danger')
            else:
                create_account(
                    full_name=full_name,
                    email=email,
                    password=password,
                    role=role,
                    department=role.title(),
                    phone=phone,
                )
                flash('Office account created successfully. You can now log in.', 'success')
                return redirect(url_for('login'))
    return render_template('register_office.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/student/dashboard')
@roles_required('student')
def student_dashboard():
    applications = applications_query(user_id=current_user().id).limit(5).all()
    return render_template('student/dashboard.html', applications=applications)

@app.route('/student/apply', methods=['GET', 'POST'])
@roles_required('student')
def student_apply():
    if request.method == 'POST':
        purpose, academic_year = form_values('purpose', 'academic_year')
        photo_path = save_uploaded_photo(UPLOAD_FOLDER)

        if not purpose or not academic_year:
            flash('Please complete the form.', 'danger')
        else:
            application = ClearanceApplication(
                user_id=current_user().id,
                purpose=purpose,
                academic_year=academic_year,
                photo_path=photo_path,
            )
            db.session.add(application)
            db.session.commit()
            flash('Clearance application submitted successfully.', 'success')
            return redirect(url_for('student_status'))
    return render_template('student/apply_clearance.html')

@app.route('/student/application/<int:application_id>/edit', methods=['GET', 'POST'])
@roles_required('student')
def student_edit_application(application_id):
    application = ClearanceApplication.query.filter_by(id=application_id, user_id=current_user().id).first_or_404()
    if request.method == 'POST':
        purpose, academic_year = form_values('purpose', 'academic_year')
        if not purpose or not academic_year:
            flash('Please complete the form.', 'danger')
            return redirect(url_for('student_edit_application', application_id=application.id))

        if application.status != 'pending' or any(
            getattr(application, field) not in {None, 'pending'}
            for field in STAGE_STATUS_FIELDS
        ):
            flash('This application cannot be edited after it has started moving through the approval stages.', 'danger')
            return redirect(url_for('student_status'))

        new_photo_path = save_uploaded_photo(UPLOAD_FOLDER)
        if new_photo_path:
            if application.photo_path != new_photo_path:
                delete_photo(UPLOAD_FOLDER, application.photo_path)
            application.photo_path = new_photo_path

        application.purpose = purpose
        application.academic_year = academic_year
        db.session.commit()
        flash('Clearance application updated successfully.', 'success')
        return redirect(url_for('student_status'))
    return render_template('student/edit_application.html', application=application)

@app.route('/student/application/<int:application_id>/delete', methods=['POST'])
@roles_required('student')
def student_delete_application(application_id):
    application = ClearanceApplication.query.filter_by(id=application_id, user_id=current_user().id).first_or_404()
    delete_photo(UPLOAD_FOLDER, application.photo_path)
    db.session.delete(application)
    db.session.commit()
    flash('Clearance application deleted successfully.', 'success')
    return redirect(url_for('student_status'))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/assets/<path:filename>')
def assets_file(filename):
    return send_from_directory(BASE_DIR / 'assests', filename)

@app.route('/student/status')
@roles_required('student')
def student_status():
    applications = applications_query(user_id=current_user().id).all()
    return render_template('student/status.html', applications=applications)

def password_change_error(user, current_password, new_password, confirm_password):
    if not user.check_password(current_password):
        return 'Current password is incorrect.'
    if new_password != confirm_password:
        return 'New passwords do not match.'
    if len(new_password) < 6:
        return 'Password must be at least 6 characters.'
    return None

def handle_profile_post(endpoint, editable_fields):
    """Apply a profile edit (and optional password change) for the signed in user."""
    user = current_user()
    email = form_value('email')
    if email and email != user.email and User.query.filter_by(email=email).first():
        flash('Email already in use by another account.', 'danger')
        return redirect(url_for(endpoint))

    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')
    if current_password and new_password and confirm_password:
        error = password_change_error(user, current_password, new_password, confirm_password)
        if error:
            flash(error, 'danger')
            return redirect(url_for(endpoint))
        user.password_hash = generate_password_hash(new_password)
        flash('Password changed successfully.', 'success')

    apply_optional_updates(user, {field: field for field in editable_fields})
    db.session.commit()
    flash('Profile updated successfully.', 'success')
    return redirect(url_for(endpoint))

@app.route('/student/profile', methods=['GET', 'POST'])
@roles_required('student')
def student_profile():
    if request.method == 'POST':
        return handle_profile_post('student_profile', ['full_name', 'email', 'phone', 'department'])
    return render_template(
        'shared/profile.html',
        back_url=url_for('student_dashboard'),
        back_label='Back to Dashboard',
        page_title='Profile',
        editable_department=True,
        identifier_label='Student ID',
        identifier_value=current_user().student_id,
        role_label='Student',
        show_department_summary=False,
    )

@app.route('/admin/dashboard')
@roles_required('admin')
def admin_dashboard():
    students = User.query.filter_by(role='student').count()
    applications = ClearanceApplication.query.count()
    approved = ClearanceApplication.query.filter_by(status='approved').count()
    pending = ClearanceApplication.query.filter_by(status='pending').count()
    recent = applications_query().limit(8).all()
    return render_template('admin/dashboard.html', students=students, applications=applications, approved=approved, pending=pending, recent=recent)

def students_ordered():
    return User.query.filter_by(role='student').order_by(User.created_at.desc()).all()

def handle_student_record_post(endpoint):
    """Update or delete a student record from an admin/office management table."""
    action = form_value('action')
    student_pk = request.form.get('student_id', type=int)
    if action in {'update', 'delete'} and student_pk:
        student = User.query.filter_by(id=student_pk, role='student').first()
        if not student:
            flash('Student not found.', 'danger')
        elif action == 'delete':
            db.session.delete(student)
            db.session.commit()
            flash('Student deleted successfully.', 'success')
        else:
            apply_optional_updates(student, STUDENT_EDITABLE_FIELDS)
            db.session.commit()
            flash('Student updated successfully.', 'success')
    return redirect(url_for(endpoint))

def handle_application_record_post(endpoint, label):
    """Update or delete an application, flashing messages that use ``label``."""
    action = form_value('action')
    application_id = request.form.get('application_id', type=int)
    if action in {'update', 'delete'} and application_id:
        application = ClearanceApplication.query.get(application_id)
        if not application:
            flash(f'{label} not found.', 'danger')
        elif action == 'delete':
            db.session.delete(application)
            db.session.commit()
            flash(f'{label} deleted successfully.', 'success')
        else:
            apply_optional_updates(application, APPLICATION_EDITABLE_FIELDS)
            db.session.commit()
            flash(f'{label} updated successfully.', 'success')
    return redirect(url_for(endpoint))

@app.route('/admin/students', methods=['GET', 'POST'])
@roles_required('admin')
def admin_students():
    if request.method == 'POST':
        return handle_student_record_post('admin_students')
    return render_template('admin/students.html', students=students_ordered())

@app.route('/admin/applications', methods=['GET', 'POST'])
@roles_required('admin')
def admin_applications():
    if request.method == 'POST':
        return handle_application_record_post('admin_applications', 'Application')
    return render_template('admin/applications.html', applications=applications_query().all())

@app.route('/admin/reports', methods=['GET', 'POST'])
@roles_required('admin')
def admin_reports():
    if request.method == 'POST':
        return handle_application_record_post('admin_reports', 'Report')
    return render_template('admin/reports.html', applications=applications_query().all())

@app.route('/admin/users', methods=['GET', 'POST'])
@roles_required('admin')
def admin_users():
    if request.method == 'POST':
        action = form_value('action')
        user_id = request.form.get('user_id', type=int)

        # Only admin can delete staff
        if action == 'delete' and user_id:
            user = User.query.filter_by(id=user_id).first()
            if user and user.role != 'student' and user.role != 'admin':
                db.session.delete(user)
                db.session.commit()
                flash('Staff member deleted successfully.', 'success')
            else:
                flash('Cannot delete this user.', 'danger')
        # Admin creates new staff
        elif action == 'create':
            full_name, email = form_values('full_name', 'email')
            password = request.form.get('password', '')
            role = request.form.get('role', 'department')
            error = account_error(full_name, email, password, missing_message='Please fill all fields.')
            if error:
                flash(error, 'danger')
            else:
                create_account(
                    full_name=full_name,
                    email=email,
                    password=password,
                    role=role,
                    department=role.title(),
                )
                flash('Staff member created successfully.', 'success')
        return redirect(url_for('admin_users'))
    
    users = User.query.filter(User.role != 'student').order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)

@app.route('/office/students', methods=['GET', 'POST'])
@roles_required('department', 'library', 'finance', 'dormitory', 'registrar', 'admin')
def office_students():
    if request.method == 'POST':
        return handle_student_record_post('office_students')
    return render_template('office/students.html', students=students_ordered())

@app.route('/office/profile', methods=['GET', 'POST'])
@roles_required('department', 'library', 'finance', 'dormitory', 'registrar')
def office_profile():
    if request.method == 'POST':
        return handle_profile_post('office_profile', ['full_name', 'email', 'phone'])
    user = current_user()
    return render_template(
        'shared/profile.html',
        back_url=url_for('index'),
        back_label='Back',
        page_title='My Profile',
        editable_department=False,
        identifier_label='Office Staff ID',
        identifier_value=f'OFF-{user.id}',
        role_label=user.role.upper(),
        show_department_summary=True,
    )

def update_approval(application_id, field, decision):
    application = ClearanceApplication.query.get_or_404(application_id)
    setattr(application, field, decision)
    application.approved_by = current_user().full_name
    application.refresh_status()

    actor_role = ROLE_LABELS.get(current_user().role, current_user().role)
    action = 'approved' if decision == 'approved' else 'rejected'
    message = f"Your clearance request '{application.purpose}' was {action} by {actor_role}."
    student = User.query.get(application.user_id)
    if student:
        send_notification_to_student(student, message)

    db.session.commit()

def make_approval_view(endpoint, status_field, label):
    def view():
        if request.method == 'POST':
            update_approval(int(request.form['application_id']), status_field, request.form['decision'])
            flash(f'{label} decision recorded.', 'success')
            return redirect(url_for(endpoint))
        return render_template(
            'shared/approve.html',
            applications=applications_query().all(),
            office_label=label,
            status_field=status_field,
        )
    return view

for endpoint, url_rule, office_role, status_column, office_label in APPROVAL_OFFICES:
    app.add_url_rule(
        url_rule,
        endpoint,
        roles_required(office_role)(make_approval_view(endpoint, status_column, office_label)),
        methods=['GET', 'POST'],
    )

@app.route('/registrar/certificate')
@login_required
def registrar_certificate():
    application_id = request.args.get('application_id', type=int)
    application = None
    if application_id:
        application = ClearanceApplication.query.get(application_id)
    return render_template('registrar/certificate.html', application=application)

if __name__ == '__main__':
    app.run(debug=True)
