import pytest

import app as app_module
from app import ClearanceApplication, User, db

APPROVAL_ROUTES = [
    ('department', '/department/approve', 'department_status', 'Department decision recorded.'),
    ('library', '/library/approve', 'library_status', 'Library decision recorded.'),
    ('finance', '/finance/approve', 'finance_status', 'Finance decision recorded.'),
    ('dormitory', '/dormitary/approve', 'dormitory_status', 'Dormitory decision recorded.'),
    ('registrar', '/registrar/approve', 'registrar_status', 'Registrar decision recorded.'),
]


@pytest.fixture(autouse=True)
def silent_notifications(monkeypatch):
    monkeypatch.setattr(app_module, 'send_notification_to_student', lambda user, message: True)


@pytest.mark.parametrize('role, path, field, message', APPROVAL_ROUTES)
def test_office_approval_page_lists_applications(client, make_user, login, student, make_application, role, path, field, message):
    make_application(student, purpose='Transcript')
    login(make_user(f'{role}@mau.edu.ng', role=role))

    response = client.get(path)

    assert response.status_code == 200
    assert b'Transcript' in response.data


@pytest.mark.parametrize('role, path, field, message', APPROVAL_ROUTES)
def test_office_can_approve_application(client, make_user, login, student, make_application, role, path, field, message):
    application = make_application(student)
    login(make_user(f'{role}@mau.edu.ng', role=role, full_name=f'{role.title()} Officer'))

    response = client.post(
        path, data={'application_id': application.id, 'decision': 'approved'}, follow_redirects=True
    )

    assert message.encode() in response.data
    db.session.refresh(application)
    assert getattr(application, field) == 'approved'
    assert application.approved_by == f'{role.title()} Officer'


@pytest.mark.parametrize('role, path, field, message', APPROVAL_ROUTES)
def test_office_can_reject_application(client, make_user, login, student, make_application, role, path, field, message):
    application = make_application(student)
    login(make_user(f'{role}@mau.edu.ng', role=role))

    client.post(path, data={'application_id': application.id, 'decision': 'rejected'})

    db.session.refresh(application)
    assert getattr(application, field) == 'rejected'
    assert application.status == 'rejected'


@pytest.mark.parametrize('role, path, field, message', APPROVAL_ROUTES)
def test_office_role_cannot_use_another_offices_route(client, make_user, login, role, path, field, message):
    other_role = 'library' if role != 'library' else 'finance'
    login(make_user(f'{other_role}@mau.edu.ng', role=other_role))

    response = client.get(path)

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')


def test_application_is_approved_after_every_office_signs_off(client, make_user, login, student, make_application):
    application = make_application(student)

    for role, path, field, _message in APPROVAL_ROUTES:
        login(make_user(f'{role}@mau.edu.ng', role=role))
        client.post(path, data={'application_id': application.id, 'decision': 'approved'})

    db.session.refresh(application)
    assert application.status == 'approved'
    assert all(getattr(application, field) == 'approved' for _r, _p, field, _m in APPROVAL_ROUTES)


def test_approval_notifies_the_student(client, make_user, login, student, make_application, monkeypatch):
    sent = []
    monkeypatch.setattr(app_module, 'send_notification_to_student', lambda user, message: sent.append((user.email, message)) or True)
    application = make_application(student, purpose='Transcript')
    login(make_user('library@mau.edu.ng', role='library'))

    client.post('/library/approve', data={'application_id': application.id, 'decision': 'approved'})

    assert sent == [(student.email, "Your clearance request 'Transcript' was approved by Library.")]


def test_approval_of_unknown_application_returns_404(client, make_user, login):
    login(make_user('library@mau.edu.ng', role='library'))

    response = client.post('/library/approve', data={'application_id': 9999, 'decision': 'approved'})

    assert response.status_code == 404


@pytest.mark.parametrize('role', ['department', 'library', 'finance', 'dormitory', 'registrar'])
def test_office_students_page_is_open_to_every_office_role(client, make_user, login, student, role):
    login(make_user(f'{role}@mau.edu.ng', role=role))

    response = client.get('/office/students')

    assert response.status_code == 200
    assert student.full_name.encode() in response.data


def test_office_can_update_student_record(client, make_user, login, student):
    login(make_user('library@mau.edu.ng', role='library'))

    response = client.post(
        '/office/students',
        data={
            'action': 'update',
            'student_id': student.id,
            'full_name': 'Ada Lovelace',
            'email': 'ada@mau.edu.ng',
            'student_id_value': 'STU777',
            'department': 'Physics',
        },
        follow_redirects=True,
    )

    assert b'Student updated successfully.' in response.data
    db.session.refresh(student)
    assert (student.full_name, student.email, student.student_id, student.department) == (
        'Ada Lovelace',
        'ada@mau.edu.ng',
        'STU777',
        'Physics',
    )


def test_office_update_keeps_blank_fields_unchanged(client, make_user, login, student):
    login(make_user('library@mau.edu.ng', role='library'))
    original = (student.full_name, student.email, student.department)

    client.post(
        '/office/students',
        data={'action': 'update', 'student_id': student.id, 'full_name': '', 'email': '', 'department': ''},
    )

    db.session.refresh(student)
    assert (student.full_name, student.email, student.department) == original


@pytest.mark.xfail(
    reason='deleting a student leaves their applications orphaned (no ON DELETE CASCADE in SQLite)',
    strict=True,
)
def test_office_can_delete_student_with_applications(client, make_user, login, student, make_application):
    make_application(student)
    login(make_user('library@mau.edu.ng', role='library'))

    response = client.post(
        '/office/students', data={'action': 'delete', 'student_id': student.id}, follow_redirects=True
    )

    assert b'Student deleted successfully.' in response.data
    assert User.query.filter_by(role='student').count() == 0
    assert ClearanceApplication.query.count() == 0


@pytest.mark.parametrize('action', ['update', 'delete'])
def test_office_student_actions_report_missing_student(client, make_user, login, action):
    login(make_user('library@mau.edu.ng', role='library'))

    response = client.post(
        '/office/students', data={'action': action, 'student_id': 9999}, follow_redirects=True
    )

    assert b'Student not found.' in response.data


def test_office_cannot_delete_staff_through_student_route(client, make_user, login):
    officer = make_user('library@mau.edu.ng', role='library')
    login(officer)

    response = client.post(
        '/office/students', data={'action': 'delete', 'student_id': officer.id}, follow_redirects=True
    )

    assert b'Student not found.' in response.data
    assert User.query.get(officer.id) is not None


def test_office_profile_updates_details_and_password(client, make_user, login):
    officer = make_user('library@mau.edu.ng', role='library', password='Passw0rd!')
    login(officer)

    client.post(
        '/office/profile',
        data={
            'full_name': 'Head Librarian',
            'email': 'head.library@mau.edu.ng',
            'phone': '0800000000',
            'current_password': 'Passw0rd!',
            'new_password': 'BrandNew1',
            'confirm_password': 'BrandNew1',
        },
    )

    db.session.refresh(officer)
    assert officer.full_name == 'Head Librarian'
    assert officer.email == 'head.library@mau.edu.ng'
    assert officer.phone == '0800000000'
    assert officer.check_password('BrandNew1')


def test_office_profile_rejects_duplicate_email(client, make_user, login):
    officer = make_user('library@mau.edu.ng', role='library')
    make_user('taken@mau.edu.ng', role='finance')
    login(officer)

    response = client.post('/office/profile', data={'email': 'taken@mau.edu.ng'}, follow_redirects=True)

    assert b'Email already in use by another account.' in response.data
    db.session.refresh(officer)
    assert officer.email == 'library@mau.edu.ng'


@pytest.mark.parametrize(
    'password_data, expected_message',
    [
        (
            {'current_password': 'wrong', 'new_password': 'BrandNew1', 'confirm_password': 'BrandNew1'},
            b'Current password is incorrect.',
        ),
        (
            {'current_password': 'Passw0rd!', 'new_password': 'BrandNew1', 'confirm_password': 'Other1'},
            b'New passwords do not match.',
        ),
        (
            {'current_password': 'Passw0rd!', 'new_password': 'tiny', 'confirm_password': 'tiny'},
            b'Password must be at least 8 characters.',
        ),
    ],
)
def test_office_profile_password_validation(client, make_user, login, password_data, expected_message):
    officer = make_user('library@mau.edu.ng', role='library', password='Passw0rd!')
    login(officer)

    response = client.post('/office/profile', data=password_data, follow_redirects=True)

    assert expected_message in response.data
    db.session.refresh(officer)
    assert officer.check_password('Passw0rd!')


def test_office_profile_page_renders(client, make_user, login):
    login(make_user('library@mau.edu.ng', role='library'))
    assert client.get('/office/profile').status_code == 200


def test_registrar_can_open_certificate_for_approved_application(client, make_user, login, student, make_application):
    application = make_application(
        student,
        status='approved',
        department_status='approved',
        library_status='approved',
        finance_status='approved',
        dormitory_status='approved',
        registrar_status='approved',
    )
    login(make_user('registrar@mau.edu.ng', role='registrar'))

    response = client.get(f'/registrar/certificate?application_id={application.id}')

    assert response.status_code == 200


def test_certificate_ignores_unknown_application_id(client, make_user, login):
    login(make_user('registrar@mau.edu.ng', role='registrar'))
    assert client.get('/registrar/certificate?application_id=9999').status_code == 200
