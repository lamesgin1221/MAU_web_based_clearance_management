import pytest

from app import ClearanceApplication, User, db


@pytest.fixture
def admin(make_user):
    return make_user('admin@mau.edu.ng', role='admin', student_id='ADM001', department='Administration')


@pytest.fixture(autouse=True)
def logged_in_admin(admin, login):
    login(admin)
    return admin


def test_dashboard_reports_counts(client, make_user, make_application):
    student_one = make_user('one@mau.edu.ng', role='student')
    student_two = make_user('two@mau.edu.ng', role='student')
    make_application(student_one, status='approved')
    make_application(student_two)

    response = client.get('/admin/dashboard')

    assert response.status_code == 200
    assert User.query.filter_by(role='student').count() == 2
    assert ClearanceApplication.query.filter_by(status='approved').count() == 1
    assert ClearanceApplication.query.filter_by(status='pending').count() == 1


def test_students_page_lists_students_only(client, student, make_user):
    make_user('lib@mau.edu.ng', role='library', full_name='Library Officer')

    response = client.get('/admin/students')

    assert response.status_code == 200
    assert b'Library Officer' not in response.data


def test_students_update_changes_editable_fields(client, student):
    response = client.post(
        '/admin/students',
        data={
            'action': 'update',
            'student_id': student.id,
            'full_name': 'Ada Lovelace',
            'email': 'ada@mau.edu.ng',
            'student_id_value': 'STU999',
            'department': 'Mathematics',
        },
    )

    assert response.headers['Location'].endswith('/admin/students')
    db.session.refresh(student)
    assert (student.full_name, student.email, student.student_id, student.department) == (
        'Ada Lovelace',
        'ada@mau.edu.ng',
        'STU999',
        'Mathematics',
    )


def test_students_update_keeps_existing_values_for_blank_fields(client, student):
    original = (student.full_name, student.email, student.student_id, student.department)

    client.post(
        '/admin/students',
        data={'action': 'update', 'student_id': student.id, 'full_name': '', 'email': '', 'department': ''},
    )

    db.session.refresh(student)
    assert (student.full_name, student.email, student.student_id, student.department) == original


def test_students_delete_removes_student(client, student):
    client.post('/admin/students', data={'action': 'delete', 'student_id': student.id})
    assert User.query.filter_by(role='student').count() == 0


def test_students_delete_ignores_non_student_accounts(client, make_user):
    officer = make_user('lib@mau.edu.ng', role='library')

    response = client.post(
        '/admin/students', data={'action': 'delete', 'student_id': officer.id}, follow_redirects=True
    )

    assert b'Student not found.' in response.data
    assert User.query.get(officer.id) is not None


def test_students_update_reports_missing_student(client):
    response = client.post(
        '/admin/students', data={'action': 'update', 'student_id': 9999}, follow_redirects=True
    )
    assert b'Student not found.' in response.data


def test_students_unknown_action_is_a_no_op(client, student):
    response = client.post('/admin/students', data={'action': 'archive', 'student_id': student.id})

    assert response.headers['Location'].endswith('/admin/students')
    assert User.query.get(student.id) is not None


@pytest.mark.parametrize('endpoint, noun', [('/admin/applications', 'Application'), ('/admin/reports', 'Report')])
def test_application_and_report_update(client, student, make_application, endpoint, noun):
    application = make_application(student)

    response = client.post(
        endpoint,
        data={
            'action': 'update',
            'application_id': application.id,
            'purpose': 'Transfer',
            'academic_year': '2025/2026',
            'status': 'approved',
        },
        follow_redirects=True,
    )

    assert f'{noun} updated successfully.'.encode() in response.data
    db.session.refresh(application)
    assert (application.purpose, application.academic_year, application.status) == (
        'Transfer',
        '2025/2026',
        'approved',
    )


@pytest.mark.parametrize('endpoint, noun', [('/admin/applications', 'Application'), ('/admin/reports', 'Report')])
def test_application_and_report_update_keeps_blank_fields(client, student, make_application, endpoint, noun):
    application = make_application(student)

    client.post(
        endpoint,
        data={
            'action': 'update',
            'application_id': application.id,
            'purpose': '',
            'academic_year': '',
            'status': '',
        },
    )

    db.session.refresh(application)
    assert (application.purpose, application.academic_year, application.status) == (
        'Graduation',
        '2024/2025',
        'pending',
    )


@pytest.mark.parametrize('endpoint, noun', [('/admin/applications', 'Application'), ('/admin/reports', 'Report')])
def test_application_and_report_delete(client, student, make_application, endpoint, noun):
    application = make_application(student)

    response = client.post(
        endpoint, data={'action': 'delete', 'application_id': application.id}, follow_redirects=True
    )

    assert f'{noun} deleted successfully.'.encode() in response.data
    assert ClearanceApplication.query.count() == 0


@pytest.mark.parametrize('endpoint, noun', [('/admin/applications', 'Application'), ('/admin/reports', 'Report')])
@pytest.mark.parametrize('action', ['delete', 'update'])
def test_application_and_report_missing_record(client, endpoint, noun, action):
    response = client.post(
        endpoint, data={'action': action, 'application_id': 9999}, follow_redirects=True
    )
    assert f'{noun} not found.'.encode() in response.data


@pytest.mark.parametrize('endpoint', ['/admin/applications', '/admin/reports'])
def test_application_and_report_pages_render(client, student, make_application, endpoint):
    make_application(student, purpose='Transcript')

    response = client.get(endpoint)

    assert response.status_code == 200
    assert b'Transcript' in response.data


def test_users_page_excludes_students(client, student, make_user):
    make_user('lib@mau.edu.ng', role='library', full_name='Library Officer')

    response = client.get('/admin/users')

    assert response.status_code == 200
    assert b'Library Officer' in response.data
    assert student.full_name.encode() not in response.data


def test_users_create_staff_account(client):
    response = client.post(
        '/admin/users',
        data={
            'action': 'create',
            'full_name': 'Finance Officer',
            'email': 'finance@mau.edu.ng',
            'password': 'Secret123',
            'role': 'finance',
        },
        follow_redirects=True,
    )

    assert b'Staff member created successfully.' in response.data
    officer = User.query.filter_by(email='finance@mau.edu.ng').one()
    assert officer.role == 'finance'
    assert officer.department == 'Finance'
    assert officer.check_password('Secret123')


@pytest.mark.parametrize('missing', ['full_name', 'email', 'password'])
def test_users_create_requires_all_fields(client, missing):
    data = {
        'action': 'create',
        'full_name': 'Finance Officer',
        'email': 'finance@mau.edu.ng',
        'password': 'Secret123',
        'role': 'finance',
    }
    data[missing] = ''

    response = client.post('/admin/users', data=data, follow_redirects=True)

    assert b'Please fill all fields.' in response.data
    assert User.query.filter_by(email='finance@mau.edu.ng').count() == 0


def test_users_create_rejects_duplicate_email(client, make_user):
    make_user('lib@mau.edu.ng', role='library')

    response = client.post(
        '/admin/users',
        data={
            'action': 'create',
            'full_name': 'Another Officer',
            'email': 'lib@mau.edu.ng',
            'password': 'Secret123',
            'role': 'library',
        },
        follow_redirects=True,
    )

    assert b'A user with that email already exists.' in response.data
    assert User.query.filter_by(email='lib@mau.edu.ng').count() == 1


def test_users_delete_staff_account(client, make_user):
    officer = make_user('lib@mau.edu.ng', role='library')

    response = client.post(
        '/admin/users', data={'action': 'delete', 'user_id': officer.id}, follow_redirects=True
    )

    assert b'Staff member deleted successfully.' in response.data
    assert User.query.get(officer.id) is None


@pytest.mark.parametrize('protected_role', ['student', 'admin'])
def test_users_delete_refuses_students_and_admins(client, make_user, protected_role):
    target = make_user(f'{protected_role}-target@mau.edu.ng', role=protected_role)

    response = client.post(
        '/admin/users', data={'action': 'delete', 'user_id': target.id}, follow_redirects=True
    )

    assert b'Cannot delete this user.' in response.data
    assert User.query.get(target.id) is not None


def test_users_delete_reports_missing_user(client):
    response = client.post('/admin/users', data={'action': 'delete', 'user_id': 9999}, follow_redirects=True)
    assert b'Cannot delete this user.' in response.data


def test_admin_can_view_office_students_page(client, student):
    response = client.get('/office/students')

    assert response.status_code == 200
    assert student.full_name.encode() in response.data


def test_admin_cannot_open_office_profile(client):
    response = client.get('/office/profile')
    assert response.headers['Location'].endswith('/login')
