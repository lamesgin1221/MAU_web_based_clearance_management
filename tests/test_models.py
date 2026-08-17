import pytest
from werkzeug.security import generate_password_hash

from app import ClearanceApplication, User

STAGES = [
    'department_status',
    'library_status',
    'finance_status',
    'dormitory_status',
    'registrar_status',
]


def build_application(**stage_values):
    application = ClearanceApplication(purpose='Graduation', academic_year='2024/2025')
    for stage in STAGES:
        setattr(application, stage, stage_values.get(stage, 'pending'))
    return application


def test_refresh_status_stays_pending_when_no_stage_decided():
    application = build_application()
    application.refresh_status()
    assert application.status == 'pending'


def test_refresh_status_pending_when_only_some_stages_approved():
    application = build_application(department_status='approved', library_status='approved')
    application.refresh_status()
    assert application.status == 'pending'


def test_refresh_status_approved_when_every_stage_approved():
    application = build_application(**{stage: 'approved' for stage in STAGES})
    application.refresh_status()
    assert application.status == 'approved'


@pytest.mark.parametrize('rejected_stage', STAGES)
def test_refresh_status_rejected_when_any_stage_rejected(rejected_stage):
    stage_values = {stage: 'approved' for stage in STAGES}
    stage_values[rejected_stage] = 'rejected'
    application = build_application(**stage_values)
    application.refresh_status()
    assert application.status == 'rejected'


def test_refresh_status_rejection_wins_over_pending():
    application = build_application(department_status='rejected')
    application.refresh_status()
    assert application.status == 'rejected'


def test_refresh_status_can_move_back_to_pending_after_reset():
    application = build_application(**{stage: 'approved' for stage in STAGES})
    application.refresh_status()
    assert application.status == 'approved'

    application.registrar_status = 'pending'
    application.refresh_status()
    assert application.status == 'pending'


def test_check_password_accepts_correct_password():
    user = User(full_name='Ada', email='ada@mau.edu.ng', password_hash=generate_password_hash('Secret123'))
    assert user.check_password('Secret123') is True


def test_check_password_rejects_wrong_password():
    user = User(full_name='Ada', email='ada@mau.edu.ng', password_hash=generate_password_hash('Secret123'))
    assert user.check_password('secret123') is False
    assert user.check_password('') is False


def test_password_is_not_stored_in_plain_text():
    user = User(full_name='Ada', email='ada@mau.edu.ng', password_hash=generate_password_hash('Secret123'))
    assert 'Secret123' not in user.password_hash


def test_application_defaults_are_applied_on_insert(flask_app, student, make_application):
    from app import db

    application = make_application(student)
    db.session.refresh(application)

    assert application.status == 'pending'
    assert all(getattr(application, stage) == 'pending' for stage in STAGES)
    assert application.submitted_at is not None
    assert application.updated_at is not None
    assert application.photo_path is None


@pytest.mark.xfail(
    reason='User.applications uses passive_deletes=True but SQLite enforces no ON DELETE CASCADE, '
           'so applications are left orphaned when a user is deleted',
    strict=True,
)
def test_deleting_user_cascades_to_applications(flask_app, student, make_application):
    from app import db

    make_application(student)
    assert ClearanceApplication.query.count() == 1

    db.session.delete(student)
    db.session.commit()

    assert ClearanceApplication.query.count() == 0
