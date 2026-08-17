import os
import base64
import smtplib
from pathlib import Path
from functools import wraps
from datetime import datetime
from email.message import EmailMessage
from urllib import parse, request as urlrequest, error as urlerror

from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'data.db'
UPLOAD_FOLDER = BASE_DIR / 'uploads'
UPLOAD_FOLDER.mkdir(exist_ok=True)

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET', 'replace-this-with-a-secret')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', f'sqlite:///{DB_PATH}')
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

with app.app_context():
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

def current_user():
    if 'user_id' not in session:
        return None
    return User.query.get(session['user_id'])

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
            db.session.commit()
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
        if role not in {'department', 'library', 'dormitary', 'registrar'}:
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
            db.session.commit()
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
    photo_path = None
    if 'photo' in request.files:
        file = request.files['photo']
        if file and file.filename:
            filename = secure_filename(file.filename)
            unique_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{filename}"
            file.save(UPLOAD_FOLDER / unique_name)
            photo_path = unique_name
    return photo_path

@app.route('/student/apply', methods=['GET', 'POST'])
@roles_required('student')
def student_apply():
    if request.method == 'POST':
        purpose = request.form.get('purpose', '').strip()
        academic_year = request.form.get('academic_year', '').strip()
        photo_path = save_uploaded_photo()

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

        new_photo_path = save_uploaded_photo()
        if new_photo_path:
            if application.photo_path and application.photo_path != new_photo_path:
                old_photo = UPLOAD_FOLDER / application.photo_path
                if old_photo.exists():
                    old_photo.unlink()
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
    if application.photo_path:
        photo_file = UPLOAD_FOLDER / application.photo_path
        if photo_file.exists():
            photo_file.unlink()
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
            flash('Password changed successfully.', 'success')
        
        # Update other fields
        if full_name:
            user.full_name = full_name
        if email:
            user.email = email
        if phone:
            user.phone = phone
        if department:
            user.department = department
        
        db.session.commit()
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
                db.session.commit()
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
                db.session.commit()
                flash('Student updated successfully.', 'success')
            else:
                flash('Student not found.', 'danger')
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
            application = ClearanceApplication.query.get(application_id)
            if application:
                db.session.delete(application)
                db.session.commit()
                flash('Application deleted successfully.', 'success')
            else:
                flash('Application not found.', 'danger')
        elif action == 'update' and application_id:
            application = ClearanceApplication.query.get(application_id)
            if application:
                application.purpose = request.form.get('purpose', '').strip() or application.purpose
                application.academic_year = request.form.get('academic_year', '').strip() or application.academic_year
                application.status = request.form.get('status', 'pending').strip() or application.status
                db.session.commit()
                flash('Application updated successfully.', 'success')
            else:
                flash('Application not found.', 'danger')
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
            application = ClearanceApplication.query.get(application_id)
            if application:
                db.session.delete(application)
                db.session.commit()
                flash('Report deleted successfully.', 'success')
            else:
                flash('Report not found.', 'danger')
        elif action == 'update' and application_id:
            application = ClearanceApplication.query.get(application_id)
            if application:
                application.purpose = request.form.get('purpose', '').strip() or application.purpose
                application.academic_year = request.form.get('academic_year', '').strip() or application.academic_year
                application.status = request.form.get('status', 'pending').strip() or application.status
                db.session.commit()
                flash('Report updated successfully.', 'success')
            else:
                flash('Report not found.', 'danger')
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
                db.session.commit()
                flash('Staff member deleted successfully.', 'success')
            else:
                flash('Cannot delete this user.', 'danger')
        # Admin creates new staff
        elif action == 'create':
            full_name = request.form.get('full_name', '').strip()
            email = request.form.get('email', '').strip()
            password = request.form.get('password', '')
            role = request.form.get('role', 'department')
            if not full_name or not email or not password:
                flash('Please fill all fields.', 'danger')
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
                db.session.commit()
                flash('Staff member created successfully.', 'success')
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
                db.session.commit()
                flash('Student updated successfully.', 'success')
            else:
                flash('Student not found.', 'danger')
        # Office staff can delete students
        elif action == 'delete' and student_id:
            student = User.query.filter_by(id=student_id, role='student').first()
            if student:
                db.session.delete(student)
                db.session.commit()
                flash('Student deleted successfully.', 'success')
            else:
                flash('Student not found.', 'danger')
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
            flash('Password changed successfully.', 'success')
        
        # Update other fields
        if full_name:
            user.full_name = full_name
        if email:
            user.email = email
        if phone:
            user.phone = phone
        
        db.session.commit()
        flash('Profile updated successfully.', 'success')
        return redirect(url_for('office_profile'))
    return render_template('office/profile.html')

def send_email_to_student(user, message):
    email_address = getattr(user, 'email', '')
    if not email_address:
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
    except Exception:
        return False


def send_sms_to_student(user, message):
    phone_number = getattr(user, 'phone', '')
    if not phone_number:
        return False

    try:
        account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
        auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
        from_number = os.environ.get('TWILIO_FROM_NUMBER')
        if not (account_sid and auth_token and from_number):
            return False

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
    except (urlerror.URLError, urlerror.HTTPError, Exception):
        return False


def send_notification_to_student(user, message):
    if send_email_to_student(user, message):
        return True
    return send_sms_to_student(user, message)


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

@app.route('/department/approve', methods=['GET', 'POST'])
@roles_required('department')
def department_approve():
    if request.method == 'POST':
        update_approval(int(request.form['application_id']), 'department_status', request.form['decision'])
        flash('Department decision recorded.', 'success')
        return redirect(url_for('department_approve'))
    applications = ClearanceApplication.query.order_by(ClearanceApplication.submitted_at.desc()).all()
    return render_template('department/approve.html', applications=applications)

@app.route('/library/approve', methods=['GET', 'POST'])
@roles_required('library')
def library_approve():
    if request.method == 'POST':
        update_approval(int(request.form['application_id']), 'library_status', request.form['decision'])
        flash('Library decision recorded.', 'success')
        return redirect(url_for('library_approve'))
    applications = ClearanceApplication.query.order_by(ClearanceApplication.submitted_at.desc()).all()
    return render_template('library/approve.html', applications=applications)

@app.route('/finance/approve', methods=['GET', 'POST'])
@roles_required('finance')
def finance_approve():
    if request.method == 'POST':
        update_approval(int(request.form['application_id']), 'finance_status', request.form['decision'])
        flash('Finance decision recorded.', 'success')
        return redirect(url_for('finance_approve'))
    applications = ClearanceApplication.query.order_by(ClearanceApplication.submitted_at.desc()).all()
    return render_template('finance/approve.html', applications=applications)

@app.route('/dormitary/approve', methods=['GET', 'POST'])
@roles_required('dormitory')
def dormitary_approve():
    if request.method == 'POST':
        update_approval(int(request.form['application_id']), 'dormitory_status', request.form['decision'])
        flash('Dormitory decision recorded.', 'success')
        return redirect(url_for('dormitary_approve'))
    applications = ClearanceApplication.query.order_by(ClearanceApplication.submitted_at.desc()).all()
    return render_template('dormitary/approve.html', applications=applications)

@app.route('/registrar/approve', methods=['GET', 'POST'])
@roles_required('registrar')
def registrar_approve():
    if request.method == 'POST':
        update_approval(int(request.form['application_id']), 'registrar_status', request.form['decision'])
        flash('Registrar decision recorded.', 'success')
        return redirect(url_for('registrar_approve'))
    applications = ClearanceApplication.query.order_by(ClearanceApplication.submitted_at.desc()).all()
    return render_template('registrar/approve.html', applications=applications)

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
