import builtins

import pytest

import init_db as init_db_module
from app import ClearanceApplication, User, db


def test_init_db_creates_default_admin(flask_app, capsys):
    init_db_module.init_db()

    admin = User.query.filter_by(email='admin@mau.edu.ng').one()
    assert admin.role == 'admin'
    assert admin.student_id == 'ADM001'
    assert admin.check_password('Admin@123')
    assert 'Admin user created' in capsys.readouterr().out


def test_init_db_is_idempotent(flask_app, capsys):
    init_db_module.init_db()
    capsys.readouterr()

    init_db_module.init_db()

    assert User.query.filter_by(email='admin@mau.edu.ng').count() == 1
    assert 'Admin user already exists' in capsys.readouterr().out


def test_reset_db_drops_data_when_confirmed(flask_app, student, make_application, monkeypatch):
    make_application(student)
    monkeypatch.setattr(builtins, 'input', lambda *args: 'YES')

    init_db_module.reset_db()

    assert ClearanceApplication.query.count() == 0
    assert User.query.filter_by(role='student').count() == 0
    assert User.query.filter_by(email='admin@mau.edu.ng').count() == 1


def test_reset_db_keeps_data_when_cancelled(flask_app, student, make_application, monkeypatch, capsys):
    make_application(student)
    monkeypatch.setattr(builtins, 'input', lambda *args: 'no')

    init_db_module.reset_db()

    assert ClearanceApplication.query.count() == 1
    assert User.query.filter_by(role='student').count() == 1
    assert 'Cancelled.' in capsys.readouterr().out


@pytest.fixture(autouse=True)
def clean_session(flask_app):
    yield
    db.session.remove()
