import os
import base64
import logging
import smtplib
from pathlib import Path
from functools import wraps
from datetime import datetime
from email.message import EmailMessage
from urllib import parse, request as urlrequest, error as urlerror

from flask import Flask, abort, render_template, request, redirect, url_for, flash, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'data.db'
UPLOAD_FOLDER = BASE_DIR / 'uploads'
UPLOAD_FOLDER.mkdir(exist_ok=True)
ALLOWED_PHOTO_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

logging.basicConfig(
    level=os.environ.get('LOG_LEVEL', 'INFO').upper(),
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
)

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET', 'replace-this-with-a-secret')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_BYTES

db = SQLAlchemy(app)


class PhotoUploadError(Exception):
    """Raised when an uploaded photo cannot be validated or stored."""


def commit_session(failure_message='Something went wrong while saving your changes. Please try again.'):
    """Commit the session, rolling back and surfacing the failure to the user.

    Returns True on success, False when the commit failed.
    """
    try:
        db.session.commit()
        return True
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception('Database commit failed')
        flash(failure_message, 'danger')
        return False


def delete_photo_file(photo_name):
    """Best-effort photo removal; failures are logged instead of being hidden."""
    if not photo_name:
        return False
    try:
        (UPLOAD_FOLDER / photo_name).unlink(missing_ok=True)
        return True
    except OSError:
        app.logger.warning('Could not delete uploaded photo %s', photo_name, exc_info=True)
        return False

ROLE_LABELS = {
    'student': 'Student',
    'department': 'Department',
    'library': 'Library',
    'finance': 'Finance',
    'dormitory': 'Dormitory',
    'registrar': 'Registrar',
    'admin': 'Admin',
}

STAFF_ROLES = {'department', 'library', 'finance', 'dormitory', 'registrar'}
APPLICATION_STATUSES = {'pending', 'approved', 'rejected'}
APPROVAL_DECISIONS = {'approved', 'rejected'}

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
        statuses = [
            self.department_status,
            self.library_status,
            self.finance_status,
            self.dormitory_status,
            self.registrar_status,
        ]
        if 'rejected' in statuses:
            self.status = 'rejected'
        elif all(value == 'approved' for value in statuses):
            self.status = 'approved'
        else:
            self.status = 'pending'

def bootstrap_database():
    """Create tables, apply the photo_path migration and seed the admin account.

    Any database failure here is logged and re-raised: starting the app against a
    half-migrated database would only produce confusing failures later on.
    """
    try:
        db.create_all()
        table_info = db.session.execute(db.text('PRAGMA table_info(clearance_application)')).fetchall()
        columns = [column[1] for column in table_info]
        if 'photo_path' not in columns:
            db.session.execute(db.text('ALTER TABLE clearance_application ADD COLUMN photo_path VARCHAR(255)'))
            db.session.commit()
        if not User.query.filter_by(email='admin@mau.edu.ng').first():
            admin = User(
                full_name='System Administrator',
                email='admin@mau.edu.ng',
                password_hash=generate_password_hash('Admin@123'),
                role='admin',
                student_id='ADM001',
                department='Administration',
                phone='07000000000',
            )
            db.session.add(admin)
            db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception('Database initialisation failed')
        raise


with app.app_context():
    bootstrap_database()

def current_user():
    if 'user_id' not in session:
        return None
    try:
        return db.session.get(User, session['user_id'])
    except SQLAlchemyError:
        app.logger.exception('Could not load the logged in user %s', session.get('user_id'))
        raise

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            session.clear()
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped

def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                session.clear()
                flash('Please log in to continue.', 'warning')
                return redirect(url_for('login'))
            if user.role not in roles:
                app.logger.info('User %s with role %s was denied access to %s', user.id, user.role, request.path)
                flash('You do not have permission to open that page.', 'danger')
                return redirect(url_for(role_dashboard(user.role)))
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

@app.route('/index.php')
def legacy_index_php():
    return redirect(url_for('index'))

@app.route('/login.php')
def legacy_login_php():
    return redirect(url_for('login'))

@app.route('/register.php')
def legacy_register_php():
    return redirect(url_for('register'))

@app.route('/logout.php')
def legacy_logout_php():
    return redirect(url_for('logout'))

@app.route('/admin/dashboard.php')
def legacy_admin_dashboard_php():
    return redirect(url_for('admin_dashboard'))

@app.route('/student/status.php')
def legacy_student_status_php():
    return redirect(url_for('student_status'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user():
        return redirect(url_for(role_dashboard(current_user().role)))
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
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
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        phone = request.form.get('phone', '').strip()
        department = request.form.get('department', '').strip()
        if not full_name or not email or not password:
            flash('Please fill all required fields.', 'danger')
        elif User.query.filter_by(email=email).first():
            flash('An account with this email already exists.', 'danger')
        else:
            user = User(
                full_name=full_name,
                email=email,
                password_hash=generate_password_hash(password),
                role='student',
                student_id=f'STU{int(datetime.utcnow().timestamp())}',
                department=department,
                phone=phone,
            )
            db.session.add(user)
            if commit_session('Could not create your account. Please try again.'):
                flash('Student account created successfully. You can now log in.', 'success')
                return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/register/office', methods=['GET', 'POST'])
def register_office():
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        phone = request.form.get('phone', '').strip()
        role = request.form.get('role', '').strip()
        role = {'dormitary': 'dormitory'}.get(role, role)
        if role not in STAFF_ROLES:
            flash('Please choose an office role.', 'danger')
        elif not full_name or not email or not password:
            flash('Please fill all required fields.', 'danger')
        elif User.query.filter_by(email=email).first():
            flash('An account with this email already exists.', 'danger')
        else:
            user = User(
                full_name=full_name,
                email=email,
                password_hash=generate_password_hash(password),
                role=role,
                department=role.title(),
                phone=phone,
            )
            db.session.add(user)
            if commit_session('Could not create the office account. Please try again.'):
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
    user = current_user()
    applications = ClearanceApplication.query.filter_by(user_id=user.id).order_by(ClearanceApplication.submitted_at.desc()).limit(5).all()
    return render_template('student/dashboard.html', applications=applications)

def save_uploaded_photo():
    """Store the uploaded photo and return its file name, or None when none was sent.

    Raises PhotoUploadError when the upload is unusable or cannot be written; callers
    are expected to report that to the user instead of losing the failure.
    """
    file = request.files.get('photo')
    if not file or not file.filename:
        return None

    filename = secure_filename(file.filename)
    if not filename:
        raise PhotoUploadError('The uploaded photo has an unsupported file name.')
    if Path(filename).suffix.lower() not in ALLOWED_PHOTO_EXTENSIONS:
        allowed = ', '.join(sorted(ALLOWED_PHOTO_EXTENSIONS))
        raise PhotoUploadError(f'Unsupported photo type. Allowed types: {allowed}.')

    unique_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{filename}"
    try:
        file.save(UPLOAD_FOLDER / unique_name)
    except OSError as exc:
        app.logger.exception('Could not store uploaded photo %s', unique_name)
        raise PhotoUploadError('The photo could not be saved. Please try again.') from exc
    return unique_name

@app.route('/student/apply', methods=['GET', 'POST'])
@roles_required('student')
def student_apply():
    if request.method == 'POST':
        purpose = request.form.get('purpose', '').strip()
        academic_year = request.form.get('academic_year', '').strip()

        if not purpose or not academic_year:
            flash('Please complete the form.', 'danger')
            return render_template('student/apply_clearance.html')

        try:
            photo_path = save_uploaded_photo()
        except PhotoUploadError as exc:
            flash(str(exc), 'danger')
            return render_template('student/apply_clearance.html')

        application = ClearanceApplication(
            user_id=current_user().id,
            purpose=purpose,
            academic_year=academic_year,
            photo_path=photo_path,
        )
        db.session.add(application)
        if not commit_session('Could not submit your application. Please try again.'):
            delete_photo_file(photo_path)
            return render_template('student/apply_clearance.html')
        flash('Clearance application submitted successfully.', 'success')
        return redirect(url_for('student_status'))
    return render_template('student/apply_clearance.html')

@app.route('/student/application/<int:application_id>/edit', methods=['GET', 'POST'])
@roles_required('student')
def student_edit_application(application_id):
    application = ClearanceApplication.query.filter_by(id=application_id, user_id=current_user().id).first_or_404()
    if request.method == 'POST':
        purpose = request.form.get('purpose', '').strip()
        academic_year = request.form.get('academic_year', '').strip()
        if not purpose or not academic_year:
            flash('Please complete the form.', 'danger')
            return redirect(url_for('student_edit_application', application_id=application.id))

        if application.status != 'pending' or any(
            getattr(application, field) not in {None, 'pending'}
            for field in ['department_status', 'library_status', 'finance_status', 'dormitory_status', 'registrar_status']
        ):
            flash('This application cannot be edited after it has started moving through the approval stages.', 'danger')
            return redirect(url_for('student_status'))

        try:
            new_photo_path = save_uploaded_photo()
        except PhotoUploadError as exc:
            flash(str(exc), 'danger')
            return redirect(url_for('student_edit_application', application_id=application.id))

        previous_photo_path = application.photo_path
        if new_photo_path:
            application.photo_path = new_photo_path

        application.purpose = purpose
        application.academic_year = academic_year
        if not commit_session('Could not update your application. Please try again.'):
            delete_photo_file(new_photo_path)
            return redirect(url_for('student_edit_application', application_id=application.id))

        if new_photo_path and previous_photo_path and previous_photo_path != new_photo_path:
            delete_photo_file(previous_photo_path)
        flash('Clearance application updated successfully.', 'success')
        return redirect(url_for('student_status'))
    return render_template('student/edit_application.html', application=application)

@app.route('/student/application/<int:application_id>/delete', methods=['POST'])
@roles_required('student')
def student_delete_application(application_id):
    application = ClearanceApplication.query.filter_by(id=application_id, user_id=current_user().id).first_or_404()
    photo_path = application.photo_path
    db.session.delete(application)
    if not commit_session('Could not delete your application. Please try again.'):
        return redirect(url_for('student_status'))
    delete_photo_file(photo_path)
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
    applications = ClearanceApplication.query.filter_by(user_id=current_user().id).order_by(ClearanceApplication.submitted_at.desc()).all()
    return render_template('student/status.html', applications=applications)

@app.route('/student/profile', methods=['GET', 'POST'])
@roles_required('student')
def student_profile():
    user = current_user()
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        department = request.form.get('department', '').strip()
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        password_changed = False

        # Validate email uniqueness if changed
        if email and email != user.email:
            if User.query.filter_by(email=email).first():
                flash('Email already in use by another account.', 'danger')
                return redirect(url_for('student_profile'))
        
        # Handle password change
        if current_password and new_password and confirm_password:
            if not user.check_password(current_password):
                flash('Current password is incorrect.', 'danger')
                return redirect(url_for('student_profile'))
            if new_password != confirm_password:
                flash('New passwords do not match.', 'danger')
                return redirect(url_for('student_profile'))
            if len(new_password) < 6:
                flash('Password must be at least 6 characters.', 'danger')
                return redirect(url_for('student_profile'))
            user.password_hash = generate_password_hash(new_password)
            password_changed = True
        
        # Update other fields
        if full_name:
            user.full_name = full_name
        if email:
            user.email = email
        if phone:
            user.phone = phone
        if department:
            user.department = department

        if commit_session('Could not update your profile. Please try again.'):
            if password_changed:
                flash('Password changed successfully.', 'success')
            flash('Profile updated successfully.', 'success')
        return redirect(url_for('student_profile'))
    return render_template('student/profile.html')

@app.route('/admin/dashboard')
@roles_required('admin')
def admin_dashboard():
    students = User.query.filter_by(role='student').count()
    applications = ClearanceApplication.query.count()
    approved = ClearanceApplication.query.filter_by(status='approved').count()
    pending = ClearanceApplication.query.filter_by(status='pending').count()
    recent = ClearanceApplication.query.order_by(ClearanceApplication.submitted_at.desc()).limit(8).all()
    return render_template('admin/dashboard.html', students=students, applications=applications, approved=approved, pending=pending, recent=recent)

@app.route('/admin/students', methods=['GET', 'POST'])
@roles_required('admin')
def admin_students():
    if request.method == 'POST':
        action = request.form.get('action', '')
        student_id = request.form.get('student_id', type=int)
        if action == 'delete' and student_id:
            student = User.query.filter_by(id=student_id, role='student').first()
            if student:
                db.session.delete(student)
                if commit_session('Could not delete the student. Please try again.'):
                    flash('Student deleted successfully.', 'success')
            else:
                flash('Student not found.', 'danger')
        elif action == 'update' and student_id:
            student = User.query.filter_by(id=student_id, role='student').first()
            if student:
                student.full_name = request.form.get('full_name', '').strip() or student.full_name
                student.email = request.form.get('email', '').strip() or student.email
                student.student_id = request.form.get('student_id_value', '').strip() or student.student_id
                student.department = request.form.get('department', '').strip() or student.department
                if commit_session('Could not update the student. Please try again.'):
                    flash('Student updated successfully.', 'success')
            else:
                flash('Student not found.', 'danger')
        else:
            app.logger.warning('Unsupported admin_students action %r for student %r', action, student_id)
            flash('That action could not be completed.', 'danger')
        return redirect(url_for('admin_students'))

    students = User.query.filter_by(role='student').order_by(User.created_at.desc()).all()
    return render_template('admin/students.html', students=students)

@app.route('/admin/applications', methods=['GET', 'POST'])
@roles_required('admin')
def admin_applications():
    if request.method == 'POST':
        action = request.form.get('action', '')
        application_id = request.form.get('application_id', type=int)
        if action == 'delete' and application_id:
            application = db.session.get(ClearanceApplication, application_id)
            if application:
                photo_path = application.photo_path
                db.session.delete(application)
                if commit_session('Could not delete the application. Please try again.'):
                    delete_photo_file(photo_path)
                    flash('Application deleted successfully.', 'success')
            else:
                flash('Application not found.', 'danger')
        elif action == 'update' and application_id:
            application = db.session.get(ClearanceApplication, application_id)
            if application:
                status = request.form.get('status', '').strip()
                if status and status not in APPLICATION_STATUSES:
                    flash('Unknown application status.', 'danger')
                    return redirect(url_for('admin_applications'))
                application.purpose = request.form.get('purpose', '').strip() or application.purpose
                application.academic_year = request.form.get('academic_year', '').strip() or application.academic_year
                application.status = status or application.status
                if commit_session('Could not update the application. Please try again.'):
                    flash('Application updated successfully.', 'success')
            else:
                flash('Application not found.', 'danger')
        else:
            app.logger.warning('Unsupported admin_applications action %r for application %r', action, application_id)
            flash('That action could not be completed.', 'danger')
        return redirect(url_for('admin_applications'))

    applications = ClearanceApplication.query.order_by(ClearanceApplication.submitted_at.desc()).all()
    return render_template('admin/applications.html', applications=applications)

@app.route('/admin/reports', methods=['GET', 'POST'])
@roles_required('admin')
def admin_reports():
    if request.method == 'POST':
        action = request.form.get('action', '')
        application_id = request.form.get('application_id', type=int)
        if action == 'delete' and application_id:
            application = db.session.get(ClearanceApplication, application_id)
            if application:
                photo_path = application.photo_path
                db.session.delete(application)
                if commit_session('Could not delete the report. Please try again.'):
                    delete_photo_file(photo_path)
                    flash('Report deleted successfully.', 'success')
            else:
                flash('Report not found.', 'danger')
        elif action == 'update' and application_id:
            application = db.session.get(ClearanceApplication, application_id)
            if application:
                status = request.form.get('status', '').strip()
                if status and status not in APPLICATION_STATUSES:
                    flash('Unknown application status.', 'danger')
                    return redirect(url_for('admin_reports'))
                application.purpose = request.form.get('purpose', '').strip() or application.purpose
                application.academic_year = request.form.get('academic_year', '').strip() or application.academic_year
                application.status = status or application.status
                if commit_session('Could not update the report. Please try again.'):
                    flash('Report updated successfully.', 'success')
            else:
                flash('Report not found.', 'danger')
        else:
            app.logger.warning('Unsupported admin_reports action %r for application %r', action, application_id)
            flash('That action could not be completed.', 'danger')
        return redirect(url_for('admin_reports'))

    applications = ClearanceApplication.query.order_by(ClearanceApplication.submitted_at.desc()).all()
    return render_template('admin/reports.html', applications=applications)

@app.route('/admin/users', methods=['GET', 'POST'])
@roles_required('admin')
def admin_users():
    if request.method == 'POST':
        action = request.form.get('action', '')
        user_id = request.form.get('user_id', type=int)
        
        # Only admin can delete staff
        if action == 'delete' and user_id:
            user = User.query.filter_by(id=user_id).first()
            if user and user.role != 'student' and user.role != 'admin':
                db.session.delete(user)
                if commit_session('Could not delete the staff member. Please try again.'):
                    flash('Staff member deleted successfully.', 'success')
            else:
                flash('Cannot delete this user.', 'danger')
        # Admin creates new staff
        elif action == 'create':
            full_name = request.form.get('full_name', '').strip()
            email = request.form.get('email', '').strip()
            password = request.form.get('password', '')
            role = request.form.get('role', 'department').strip()
            if not full_name or not email or not password:
                flash('Please fill all fields.', 'danger')
            elif role not in STAFF_ROLES:
                flash('Please choose a valid staff role.', 'danger')
            elif User.query.filter_by(email=email).first():
                flash('A user with that email already exists.', 'danger')
            else:
                user = User(
                    full_name=full_name,
                    email=email,
                    password_hash=generate_password_hash(password),
                    role=role,
                    department=role.title(),
                )
                db.session.add(user)
                if commit_session('Could not create the staff member. Please try again.'):
                    flash('Staff member created successfully.', 'success')
        else:
            app.logger.warning('Unsupported admin_users action %r for user %r', action, user_id)
            flash('That action could not be completed.', 'danger')
        return redirect(url_for('admin_users'))
    
    users = User.query.filter(User.role != 'student').order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)

@app.route('/office/students', methods=['GET', 'POST'])
@roles_required('department', 'library', 'finance', 'dormitory', 'registrar', 'admin')
def office_students():
    if request.method == 'POST':
        action = request.form.get('action', '')
        student_id = request.form.get('student_id', type=int)
        
        # Office staff can edit students
        if action == 'update' and student_id:
            student = User.query.filter_by(id=student_id, role='student').first()
            if student:
                student.full_name = request.form.get('full_name', '').strip() or student.full_name
                student.email = request.form.get('email', '').strip() or student.email
                student.student_id = request.form.get('student_id_value', '').strip() or student.student_id
                student.department = request.form.get('department', '').strip() or student.department
                if commit_session('Could not update the student. Please try again.'):
                    flash('Student updated successfully.', 'success')
            else:
                flash('Student not found.', 'danger')
        # Office staff can delete students
        elif action == 'delete' and student_id:
            student = User.query.filter_by(id=student_id, role='student').first()
            if student:
                db.session.delete(student)
                if commit_session('Could not delete the student. Please try again.'):
                    flash('Student deleted successfully.', 'success')
            else:
                flash('Student not found.', 'danger')
        else:
            app.logger.warning('Unsupported office_students action %r for student %r', action, student_id)
            flash('That action could not be completed.', 'danger')
        return redirect(url_for('office_students'))
    
    students = User.query.filter_by(role='student').order_by(User.created_at.desc()).all()
    return render_template('office/students.html', students=students)

@app.route('/office/profile', methods=['GET', 'POST'])
@roles_required('department', 'library', 'finance', 'dormitory', 'registrar')
def office_profile():
    user = current_user()
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        password_changed = False

        # Validate email uniqueness if changed
        if email and email != user.email:
            if User.query.filter_by(email=email).first():
                flash('Email already in use by another account.', 'danger')
                return redirect(url_for('office_profile'))
        
        # Handle password change
        if current_password and new_password and confirm_password:
            if not user.check_password(current_password):
                flash('Current password is incorrect.', 'danger')
                return redirect(url_for('office_profile'))
            if new_password != confirm_password:
                flash('New passwords do not match.', 'danger')
                return redirect(url_for('office_profile'))
            if len(new_password) < 6:
                flash('Password must be at least 6 characters.', 'danger')
                return redirect(url_for('office_profile'))
            user.password_hash = generate_password_hash(new_password)
            password_changed = True
        
        # Update other fields
        if full_name:
            user.full_name = full_name
        if email:
            user.email = email
        if phone:
            user.phone = phone

        if commit_session('Could not update your profile. Please try again.'):
            if password_changed:
                flash('Password changed successfully.', 'success')
            flash('Profile updated successfully.', 'success')
        return redirect(url_for('office_profile'))
    return render_template('office/profile.html')

def send_email_to_student(user, message):
    email_address = user.email if user else ''
    if not email_address:
        app.logger.warning('No email address on record for user %s; skipping email', getattr(user, 'id', None))
        return False

    try:
        msg = EmailMessage()
        msg['Subject'] = 'MAU Clearance Update'
        msg['From'] = os.environ.get('MAIL_FROM', 'noreply@mau.edu.ng')
        msg['To'] = email_address
        msg.set_content(message)

        smtp_server = os.environ.get('MAIL_SERVER', 'localhost')
        smtp_port = int(os.environ.get('MAIL_PORT', '25'))
        smtp_username = os.environ.get('MAIL_USERNAME')
        smtp_password = os.environ.get('MAIL_PASSWORD')

        with smtplib.SMTP(smtp_server, smtp_port) as smtp:
            if smtp_username and smtp_password:
                smtp.starttls()
                smtp.login(smtp_username, smtp_password)
            smtp.send_message(msg)
        return True
    except (OSError, smtplib.SMTPException, ValueError):
        app.logger.exception('Could not email clearance update to %s', email_address)
        return False


def send_sms_to_student(user, message):
    phone_number = user.phone if user else ''
    if not phone_number:
        app.logger.warning('No phone number on record for user %s; skipping SMS', getattr(user, 'id', None))
        return False

    account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
    auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
    from_number = os.environ.get('TWILIO_FROM_NUMBER')
    if not (account_sid and auth_token and from_number):
        app.logger.warning('Twilio credentials are not configured; skipping SMS to %s', phone_number)
        return False

    try:
        payload = parse.urlencode({
            'To': phone_number,
            'From': from_number,
            'Body': message,
        }).encode()
        auth = f'{account_sid}:{auth_token}'.encode('utf-8')
        req = urlrequest.Request(
            f'https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json',
            data=payload,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            method='POST',
        )
        req.add_header('Authorization', 'Basic ' + base64.b64encode(auth).decode('ascii'))
        with urlrequest.urlopen(req, timeout=10) as response:
            response.read()
        return True
    except urlerror.HTTPError as exc:
        app.logger.error('Twilio rejected the SMS to %s: HTTP %s', phone_number, exc.code, exc_info=True)
        return False
    except (urlerror.URLError, OSError, ValueError):
        app.logger.exception('Could not send SMS to %s', phone_number)
        return False


def send_notification_to_student(user, message):
    if send_email_to_student(user, message):
        return True
    if send_sms_to_student(user, message):
        return True
    app.logger.error('Every notification channel failed for user %s', getattr(user, 'id', None))
    return False


def update_approval(application_id, field, decision):
    """Record an office decision and notify the student.

    Returns a (saved, notified) pair. Raises ValueError for an unknown decision and
    aborts with 404 when the application does not exist.
    """
    if decision not in APPROVAL_DECISIONS:
        raise ValueError(f'Unsupported clearance decision: {decision!r}')

    application = db.get_or_404(ClearanceApplication, application_id)
    setattr(application, field, decision)
    application.approved_by = current_user().full_name
    application.refresh_status()
    if not commit_session('Could not record the decision. Please try again.'):
        return False, False

    actor_role = ROLE_LABELS.get(current_user().role, current_user().role)
    message = f"Your clearance request '{application.purpose}' was {decision} by {actor_role}."
    student = db.session.get(User, application.user_id)
    if student is None:
        app.logger.error('Application %s references missing user %s', application.id, application.user_id)
        return True, False
    return True, send_notification_to_student(student, message)

def handle_approval_request(field, office_label, endpoint):
    """Validate an approval form submission, record it and report the outcome."""
    application_id = request.form.get('application_id', type=int)
    decision = request.form.get('decision', '').strip()
    if not application_id or decision not in APPROVAL_DECISIONS:
        app.logger.warning(
            'Invalid %s approval submission: application_id=%r decision=%r',
            field, request.form.get('application_id'), decision,
        )
        flash('Please choose an application and a valid decision.', 'danger')
        return redirect(url_for(endpoint))

    saved, notified = update_approval(application_id, field, decision)
    if saved:
        flash(f'{office_label} decision recorded.', 'success')
        if not notified:
            flash('The student could not be notified automatically. Please contact them directly.', 'warning')
    return redirect(url_for(endpoint))

@app.route('/department/approve', methods=['GET', 'POST'])
@roles_required('department')
def department_approve():
    if request.method == 'POST':
        return handle_approval_request('department_status', 'Department', 'department_approve')
    applications = ClearanceApplication.query.order_by(ClearanceApplication.submitted_at.desc()).all()
    return render_template('department/approve.html', applications=applications)

@app.route('/library/approve', methods=['GET', 'POST'])
@roles_required('library')
def library_approve():
    if request.method == 'POST':
        return handle_approval_request('library_status', 'Library', 'library_approve')
    applications = ClearanceApplication.query.order_by(ClearanceApplication.submitted_at.desc()).all()
    return render_template('library/approve.html', applications=applications)

@app.route('/finance/approve', methods=['GET', 'POST'])
@roles_required('finance')
def finance_approve():
    if request.method == 'POST':
        return handle_approval_request('finance_status', 'Finance', 'finance_approve')
    applications = ClearanceApplication.query.order_by(ClearanceApplication.submitted_at.desc()).all()
    return render_template('finance/approve.html', applications=applications)

@app.route('/dormitary/approve', methods=['GET', 'POST'])
@roles_required('dormitory')
def dormitary_approve():
    if request.method == 'POST':
        return handle_approval_request('dormitory_status', 'Dormitory', 'dormitary_approve')
    applications = ClearanceApplication.query.order_by(ClearanceApplication.submitted_at.desc()).all()
    return render_template('dormitary/approve.html', applications=applications)

@app.route('/registrar/approve', methods=['GET', 'POST'])
@roles_required('registrar')
def registrar_approve():
    if request.method == 'POST':
        return handle_approval_request('registrar_status', 'Registrar', 'registrar_approve')
    applications = ClearanceApplication.query.order_by(ClearanceApplication.submitted_at.desc()).all()
    return render_template('registrar/approve.html', applications=applications)

@app.route('/registrar/certificate')
@login_required
def registrar_certificate():
    application_id = request.args.get('application_id', type=int)
    application = None
    if application_id:
        application = db.get_or_404(ClearanceApplication, application_id)
        user = current_user()
        if user.role == 'student' and application.user_id != user.id:
            app.logger.warning('Student %s tried to open certificate %s', user.id, application_id)
            abort(403)
    return render_template('registrar/certificate.html', application=application)

@app.errorhandler(400)
def handle_bad_request(error):
    app.logger.info('Bad request for %s: %s', request.path, error)
    return render_template('error.html', code=400, message='The request could not be understood.'), 400

@app.errorhandler(403)
def handle_forbidden(error):
    return render_template('error.html', code=403, message='You do not have access to that page.'), 403

@app.errorhandler(404)
def handle_not_found(error):
    return render_template('error.html', code=404, message='We could not find that page.'), 404

@app.errorhandler(413)
def handle_payload_too_large(error):
    limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
    return render_template('error.html', code=413, message=f'The upload is too large. The limit is {limit_mb} MB.'), 413

@app.errorhandler(Exception)
def handle_unexpected_error(error):
    """Log every unhandled exception before returning a generic error page."""
    if isinstance(error, HTTPException):
        return error
    db.session.rollback()
    app.logger.exception('Unhandled error while processing %s %s', request.method, request.path)
    return render_template('error.html', code=500, message='Something went wrong on our side. The issue has been logged.'), 500

if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1')
