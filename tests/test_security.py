import pytest

import app as app_module


@pytest.fixture
def csrf_client(flask_app):
    flask_app.config.update(WTF_CSRF_ENABLED=True)
    try:
        yield flask_app.test_client()
    finally:
        flask_app.config.update(WTF_CSRF_ENABLED=False)


@pytest.mark.parametrize(
    'path, data',
    [
        ('/login', {'email': 'student@mau.edu.ng', 'password': 'Passw0rd!'}),
        ('/register', {'full_name': 'Ada', 'email': 'ada@mau.edu.ng', 'password': 'Secret123'}),
    ],
)
def test_post_without_csrf_token_is_rejected(csrf_client, path, data):
    assert csrf_client.post(path, data=data).status_code == 400


def test_forms_render_a_csrf_token(csrf_client):
    assert b'name="csrf_token"' in csrf_client.get('/login').data


def test_secret_key_is_not_a_shared_default(flask_app):
    assert flask_app.config['SECRET_KEY'] != 'replace-this-with-a-secret'


def test_session_cookie_is_hardened(flask_app):
    assert flask_app.config['SESSION_COOKIE_HTTPONLY'] is True
    assert flask_app.config['SESSION_COOKIE_SAMESITE'] == 'Lax'


def test_load_secret_key_requires_env_outside_debug(monkeypatch):
    monkeypatch.setenv('FLASK_SECRET', '')
    monkeypatch.setattr(app_module, 'DEBUG', False)

    with pytest.raises(RuntimeError):
        app_module.load_secret_key()


def test_certificate_hides_other_students_applications(client, student, make_user, login, make_application):
    application = make_application(student)
    login(make_user('other@mau.edu.ng', role='student'))

    assert client.get(f'/registrar/certificate?application_id={application.id}').status_code == 403


def test_certificate_visible_to_registrar(client, student, make_user, login, make_application):
    application = make_application(student)
    login(make_user('registrar@mau.edu.ng', role='registrar'))

    assert client.get(f'/registrar/certificate?application_id={application.id}').status_code == 200


@pytest.mark.parametrize('decision', ['', 'approved-ish', 'deleted'])
def test_approval_rejects_unknown_decisions(client, student, make_user, login, make_application, decision):
    application = make_application(student)
    login(make_user('lib@mau.edu.ng', role='library'))

    response = client.post(
        '/library/approve',
        data={'application_id': application.id, 'decision': decision},
        follow_redirects=True,
    )

    assert b'Invalid approval request.' in response.data
    app_module.db.session.refresh(application)
    assert application.library_status == 'pending'


def test_admin_cannot_set_arbitrary_application_status(client, make_user, login, student, make_application):
    application = make_application(student)
    login(make_user('admin@mau.edu.ng', role='admin'))

    response = client.post(
        '/admin/applications',
        data={'action': 'update', 'application_id': application.id, 'status': 'cleared'},
        follow_redirects=True,
    )

    assert b'Invalid application status.' in response.data
    app_module.db.session.refresh(application)
    assert application.status == 'pending'


def test_admin_cannot_create_another_admin(client, make_user, login):
    login(make_user('admin@mau.edu.ng', role='admin'))

    response = client.post(
        '/admin/users',
        data={
            'action': 'create',
            'full_name': 'Sneaky',
            'email': 'sneaky@mau.edu.ng',
            'password': 'Secret123',
            'role': 'admin',
        },
        follow_redirects=True,
    )

    assert b'Please choose a valid staff role.' in response.data
    assert app_module.User.query.filter_by(email='sneaky@mau.edu.ng').count() == 0
