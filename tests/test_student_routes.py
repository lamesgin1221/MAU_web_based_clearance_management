import io

import pytest

import app as app_module
from app import ClearanceApplication, User, db


@pytest.fixture(autouse=True)
def logged_in_student(student, login):
    login(student)
    return student


def test_dashboard_lists_only_five_most_recent_applications(client, logged_in_student, make_application):
    for index in range(7):
        make_application(logged_in_student, purpose=f'Purpose {index}')

    response = client.get('/student/dashboard')

    assert response.status_code == 200
    assert b'Purpose 6' in response.data
    assert b'Purpose 1' not in response.data


def test_apply_page_renders(client):
    assert client.get('/student/apply').status_code == 200


def test_apply_creates_application(client, logged_in_student):
    response = client.post('/student/apply', data={'purpose': 'Graduation', 'academic_year': '2024/2025'})

    assert response.headers['Location'].endswith('/student/status')
    application = ClearanceApplication.query.one()
    assert application.user_id == logged_in_student.id
    assert application.status == 'pending'
    assert application.photo_path is None


def test_apply_stores_uploaded_photo(client):
    response = client.post(
        '/student/apply',
        data={
            'purpose': 'Graduation',
            'academic_year': '2024/2025',
            'photo': (io.BytesIO(b'photo'), 'me.png'),
        },
        content_type='multipart/form-data',
    )

    assert response.status_code == 302
    application = ClearanceApplication.query.one()
    assert application.photo_path.endswith('_me.png')
    assert (app_module.UPLOAD_FOLDER / application.photo_path).exists()


@pytest.mark.parametrize('missing', ['purpose', 'academic_year'])
def test_apply_requires_purpose_and_academic_year(client, missing):
    data = {'purpose': 'Graduation', 'academic_year': '2024/2025'}
    data[missing] = ''

    response = client.post('/student/apply', data=data)

    assert b'Please complete the form.' in response.data
    assert ClearanceApplication.query.count() == 0


def test_status_page_lists_applications(client, logged_in_student, make_application):
    make_application(logged_in_student, purpose='Transcript')

    response = client.get('/student/status')

    assert response.status_code == 200
    assert b'Transcript' in response.data


def test_edit_page_renders_for_own_pending_application(client, logged_in_student, make_application):
    application = make_application(logged_in_student)
    assert client.get(f'/student/application/{application.id}/edit').status_code == 200


def test_edit_updates_pending_application(client, logged_in_student, make_application):
    application = make_application(logged_in_student)

    response = client.post(
        f'/student/application/{application.id}/edit',
        data={'purpose': 'Transfer', 'academic_year': '2025/2026'},
    )

    assert response.headers['Location'].endswith('/student/status')
    db.session.refresh(application)
    assert (application.purpose, application.academic_year) == ('Transfer', '2025/2026')


def test_edit_replaces_photo_and_removes_the_old_file(client, logged_in_student, make_application):
    old_photo = app_module.UPLOAD_FOLDER / 'old.png'
    old_photo.write_bytes(b'old')
    application = make_application(logged_in_student, photo_path='old.png')

    client.post(
        f'/student/application/{application.id}/edit',
        data={
            'purpose': 'Transfer',
            'academic_year': '2025/2026',
            'photo': (io.BytesIO(b'new'), 'new.png'),
        },
        content_type='multipart/form-data',
    )

    db.session.refresh(application)
    assert application.photo_path.endswith('_new.png')
    assert not old_photo.exists()


def test_edit_keeps_existing_photo_when_none_uploaded(client, logged_in_student, make_application):
    photo = app_module.UPLOAD_FOLDER / 'keep.png'
    photo.write_bytes(b'keep')
    application = make_application(logged_in_student, photo_path='keep.png')

    client.post(
        f'/student/application/{application.id}/edit',
        data={'purpose': 'Transfer', 'academic_year': '2025/2026'},
    )

    db.session.refresh(application)
    assert application.photo_path == 'keep.png'
    assert photo.exists()


@pytest.mark.parametrize('missing', ['purpose', 'academic_year'])
def test_edit_requires_purpose_and_academic_year(client, logged_in_student, make_application, missing):
    application = make_application(logged_in_student)
    data = {'purpose': 'Transfer', 'academic_year': '2025/2026'}
    data[missing] = ''

    response = client.post(f'/student/application/{application.id}/edit', data=data)

    assert response.headers['Location'].endswith(f'/student/application/{application.id}/edit')
    db.session.refresh(application)
    assert application.purpose == 'Graduation'


@pytest.mark.parametrize(
    'stage',
    ['department_status', 'library_status', 'finance_status', 'dormitory_status', 'registrar_status'],
)
def test_edit_blocked_once_a_stage_has_decided(client, logged_in_student, make_application, stage):
    application = make_application(logged_in_student, **{stage: 'approved'})

    response = client.post(
        f'/student/application/{application.id}/edit',
        data={'purpose': 'Transfer', 'academic_year': '2025/2026'},
    )

    assert response.headers['Location'].endswith('/student/status')
    db.session.refresh(application)
    assert application.purpose == 'Graduation'


def test_edit_returns_404_for_another_students_application(client, make_user, make_application):
    other_student = make_user('other@mau.edu.ng', role='student')
    application = make_application(other_student)

    assert client.get(f'/student/application/{application.id}/edit').status_code == 404


def test_delete_removes_application_and_photo(client, logged_in_student, make_application):
    photo = app_module.UPLOAD_FOLDER / 'bye.png'
    photo.write_bytes(b'bye')
    application = make_application(logged_in_student, photo_path='bye.png')

    response = client.post(f'/student/application/{application.id}/delete')

    assert response.headers['Location'].endswith('/student/status')
    assert ClearanceApplication.query.count() == 0
    assert not photo.exists()


def test_delete_works_when_photo_file_is_already_gone(client, logged_in_student, make_application):
    application = make_application(logged_in_student, photo_path='missing.png')

    response = client.post(f'/student/application/{application.id}/delete')

    assert response.status_code == 302
    assert ClearanceApplication.query.count() == 0


def test_delete_returns_404_for_another_students_application(client, make_user, make_application):
    other_student = make_user('other@mau.edu.ng', role='student')
    application = make_application(other_student)

    assert client.post(f'/student/application/{application.id}/delete').status_code == 404
    assert ClearanceApplication.query.count() == 1


def test_profile_page_renders(client):
    assert client.get('/student/profile').status_code == 200


def test_profile_updates_contact_details(client, logged_in_student):
    response = client.post(
        '/student/profile',
        data={
            'full_name': 'Ada Lovelace',
            'email': 'ada@mau.edu.ng',
            'phone': '0800000000',
            'department': 'Mathematics',
        },
    )

    assert response.headers['Location'].endswith('/student/profile')
    db.session.refresh(logged_in_student)
    assert logged_in_student.full_name == 'Ada Lovelace'
    assert logged_in_student.email == 'ada@mau.edu.ng'
    assert logged_in_student.phone == '0800000000'
    assert logged_in_student.department == 'Mathematics'


def test_profile_ignores_blank_fields(client, logged_in_student):
    original = (logged_in_student.full_name, logged_in_student.email, logged_in_student.phone)

    client.post('/student/profile', data={'full_name': '', 'email': '', 'phone': '', 'department': ''})

    db.session.refresh(logged_in_student)
    assert (logged_in_student.full_name, logged_in_student.email, logged_in_student.phone) == original


def test_profile_rejects_email_already_used_by_another_account(client, logged_in_student, make_user):
    make_user('taken@mau.edu.ng', role='student')

    response = client.post('/student/profile', data={'email': 'taken@mau.edu.ng'}, follow_redirects=True)

    assert b'Email already in use by another account.' in response.data
    db.session.refresh(logged_in_student)
    assert logged_in_student.email == 'student@mau.edu.ng'


def test_profile_changes_password_with_correct_current_password(client, logged_in_student):
    client.post(
        '/student/profile',
        data={
            'current_password': 'Passw0rd!',
            'new_password': 'BrandNew1',
            'confirm_password': 'BrandNew1',
        },
    )

    db.session.refresh(logged_in_student)
    assert logged_in_student.check_password('BrandNew1')


def test_profile_rejects_wrong_current_password(client, logged_in_student):
    response = client.post(
        '/student/profile',
        data={
            'current_password': 'not-my-password',
            'new_password': 'BrandNew1',
            'confirm_password': 'BrandNew1',
        },
        follow_redirects=True,
    )

    assert b'Current password is incorrect.' in response.data
    db.session.refresh(logged_in_student)
    assert logged_in_student.check_password('Passw0rd!')


def test_profile_rejects_mismatched_new_passwords(client, logged_in_student):
    response = client.post(
        '/student/profile',
        data={
            'current_password': 'Passw0rd!',
            'new_password': 'BrandNew1',
            'confirm_password': 'Different1',
        },
        follow_redirects=True,
    )

    assert b'New passwords do not match.' in response.data
    db.session.refresh(logged_in_student)
    assert logged_in_student.check_password('Passw0rd!')


def test_profile_rejects_too_short_password(client, logged_in_student):
    response = client.post(
        '/student/profile',
        data={'current_password': 'Passw0rd!', 'new_password': 'short', 'confirm_password': 'short'},
        follow_redirects=True,
    )

    assert b'Password must be at least 6 characters.' in response.data
    db.session.refresh(logged_in_student)
    assert logged_in_student.check_password('Passw0rd!')


def test_certificate_page_renders_for_logged_in_student(client, logged_in_student, make_application):
    application = make_application(logged_in_student)

    response = client.get(f'/registrar/certificate?application_id={application.id}')

    assert response.status_code == 200


def test_certificate_page_renders_without_application_id(client):
    assert client.get('/registrar/certificate').status_code == 200


def test_student_cannot_manage_other_users(client):
    response = client.post('/admin/students', data={'action': 'delete', 'student_id': 1})
    assert response.headers['Location'].endswith('/login')
    assert User.query.filter_by(role='student').count() == 1
