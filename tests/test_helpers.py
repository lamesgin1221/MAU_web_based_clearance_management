import io

import pytest
from flask import session

import app as app_module
from app import (
    ROLE_LABELS,
    PhotoUploadError,
    current_user,
    role_dashboard,
    save_uploaded_photo,
    update_approval,
)


@pytest.mark.parametrize(
    'role, endpoint',
    [
        ('student', 'student_dashboard'),
        ('department', 'department_approve'),
        ('library', 'library_approve'),
        ('finance', 'finance_approve'),
        ('dormitory', 'dormitary_approve'),
        ('registrar', 'registrar_approve'),
        ('admin', 'admin_dashboard'),
    ],
)
def test_role_dashboard_maps_known_roles(role, endpoint):
    assert role_dashboard(role) == endpoint


@pytest.mark.parametrize('role', ['', None, 'unknown', 'dormitary'])
def test_role_dashboard_falls_back_to_index_for_unknown_roles(role):
    assert role_dashboard(role) == 'index'


def test_role_labels_cover_every_dashboard_role():
    assert set(ROLE_LABELS) == {'student', 'department', 'library', 'finance', 'dormitory', 'registrar', 'admin'}


def test_current_user_returns_none_without_session(flask_app):
    with flask_app.test_request_context('/'):
        assert current_user() is None


def test_current_user_returns_none_for_stale_session_id(flask_app):
    with flask_app.test_request_context('/'):
        session['user_id'] = 9999
        assert current_user() is None


def test_current_user_returns_logged_in_user(flask_app, student):
    with flask_app.test_request_context('/'):
        session['user_id'] = student.id
        assert current_user().email == student.email


def test_save_uploaded_photo_returns_none_without_file(flask_app):
    with flask_app.test_request_context('/', method='POST', data={}):
        assert save_uploaded_photo() is None


def test_save_uploaded_photo_returns_none_for_empty_filename(flask_app):
    data = {'photo': (io.BytesIO(b''), '')}
    with flask_app.test_request_context('/', method='POST', data=data):
        assert save_uploaded_photo() is None


def test_save_uploaded_photo_writes_file_with_generated_name(flask_app):
    data = {'photo': (io.BytesIO(b'image-bytes'), 'passport.png')}
    with flask_app.test_request_context('/', method='POST', data=data):
        stored_name = save_uploaded_photo()

    assert stored_name.endswith('.png')
    assert 'passport' not in stored_name
    saved_file = app_module.UPLOAD_FOLDER / stored_name
    assert saved_file.read_bytes() == b'image-bytes'


@pytest.mark.parametrize('filename', ['../../etc/passwd', 'evil.html', 'shell.py', 'noextension'])
def test_save_uploaded_photo_rejects_non_image_files(flask_app, filename):
    data = {'photo': (io.BytesIO(b'x'), filename)}
    with flask_app.test_request_context('/', method='POST', data=data):
        with pytest.raises(PhotoUploadError):
            save_uploaded_photo()

    assert list(app_module.UPLOAD_FOLDER.iterdir()) == []


@pytest.fixture
def no_notifications(monkeypatch):
    sent = []
    monkeypatch.setattr(app_module, 'send_notification_to_student', lambda user, message: sent.append((user.email, message)) or True)
    return sent


def test_update_approval_records_decision_and_actor(flask_app, student, make_application, no_notifications):
    application = make_application(student)
    officer = app_module.User(full_name='Lib Officer', email='lib@mau.edu.ng', password_hash='x', role='library')
    app_module.db.session.add(officer)
    app_module.db.session.commit()

    with flask_app.test_request_context('/'):
        session['user_id'] = officer.id
        update_approval(application.id, 'library_status', 'approved')

    app_module.db.session.refresh(application)
    assert application.library_status == 'approved'
    assert application.approved_by == 'Lib Officer'
    assert application.status == 'pending'


def test_update_approval_rejection_sets_application_rejected(flask_app, student, make_application, no_notifications):
    application = make_application(student)
    officer = app_module.User(full_name='Fin Officer', email='fin@mau.edu.ng', password_hash='x', role='finance')
    app_module.db.session.add(officer)
    app_module.db.session.commit()

    with flask_app.test_request_context('/'):
        session['user_id'] = officer.id
        update_approval(application.id, 'finance_status', 'rejected')

    app_module.db.session.refresh(application)
    assert application.status == 'rejected'


def test_update_approval_notifies_student_with_role_label(flask_app, student, make_application, no_notifications):
    application = make_application(student, purpose='Transcript')
    officer = app_module.User(full_name='Reg Officer', email='reg@mau.edu.ng', password_hash='x', role='registrar')
    app_module.db.session.add(officer)
    app_module.db.session.commit()

    with flask_app.test_request_context('/'):
        session['user_id'] = officer.id
        update_approval(application.id, 'registrar_status', 'approved')

    assert no_notifications == [(student.email, "Your clearance request 'Transcript' was approved by Registrar.")]


def test_update_approval_aborts_for_unknown_application(flask_app, student, no_notifications):
    from werkzeug.exceptions import NotFound

    with flask_app.test_request_context('/'):
        session['user_id'] = student.id
        with pytest.raises(NotFound):
            update_approval(4242, 'library_status', 'approved')


def test_inject_globals_exposes_current_user_and_labels(flask_app, student):
    with flask_app.test_request_context('/'):
        session['user_id'] = student.id
        globals_ = app_module.inject_globals()

    assert globals_['current_user'].email == student.email
    assert globals_['role_labels'] == ROLE_LABELS
