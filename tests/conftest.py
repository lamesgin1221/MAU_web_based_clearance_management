import os
import sys
import tempfile
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

TEST_DB_DIR = tempfile.mkdtemp(prefix='mau-test-db-')
os.environ['DATABASE_URL'] = f"sqlite:///{Path(TEST_DB_DIR) / 'test.db'}"

import app as app_module  # noqa: E402  (import after DATABASE_URL is set)


@pytest.fixture
def flask_app(tmp_path, monkeypatch):
    upload_folder = tmp_path / 'uploads'
    upload_folder.mkdir()
    monkeypatch.setattr(app_module, 'UPLOAD_FOLDER', upload_folder)
    app_module.app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        UPLOAD_FOLDER=str(upload_folder),
    )
    with app_module.app.app_context():
        app_module.db.drop_all()
        app_module.db.create_all()
        yield app_module.app
        app_module.db.session.remove()
        app_module.db.drop_all()


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def make_user(flask_app):
    def _make_user(email, role='student', password='Passw0rd!', **kwargs):
        user = app_module.User(
            full_name=kwargs.pop('full_name', f'{role.title()} User'),
            email=email,
            password_hash=generate_password_hash(password),
            role=role,
            **kwargs,
        )
        app_module.db.session.add(user)
        app_module.db.session.commit()
        return user

    return _make_user


@pytest.fixture
def student(make_user):
    return make_user('student@mau.edu.ng', role='student', student_id='STU001', department='CS', phone='0700000001')


@pytest.fixture
def make_application(flask_app):
    def _make_application(user, purpose='Graduation', academic_year='2024/2025', **kwargs):
        application = app_module.ClearanceApplication(
            user_id=user.id,
            purpose=purpose,
            academic_year=academic_year,
            **kwargs,
        )
        app_module.db.session.add(application)
        app_module.db.session.commit()
        return application

    return _make_application


@pytest.fixture
def login(client):
    def _login(user):
        with client.session_transaction() as sess:
            sess['user_id'] = user.id
            sess['role'] = user.role

    return _login
