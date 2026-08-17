import pytest

from app import User


def test_index_renders_landing_page_for_anonymous_visitor(client):
    response = client.get('/')
    assert response.status_code == 200


def test_index_redirects_logged_in_user_to_role_dashboard(client, student, login):
    login(student)
    response = client.get('/')
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/student/dashboard')


@pytest.mark.parametrize(
    'legacy_path, target',
    [
        ('/index.php', '/'),
        ('/login.php', '/login'),
        ('/register.php', '/register'),
        ('/logout.php', '/logout'),
        ('/admin/dashboard.php', '/admin/dashboard'),
        ('/student/status.php', '/student/status'),
    ],
)
def test_legacy_php_urls_redirect_to_flask_routes(client, legacy_path, target):
    response = client.get(legacy_path)
    assert response.status_code == 302
    assert response.headers['Location'].endswith(target)


def test_login_page_renders(client):
    assert client.get('/login').status_code == 200


def test_login_with_valid_credentials_starts_session(client, make_user):
    make_user('ada@mau.edu.ng', role='student', password='Secret123')

    response = client.post('/login', data={'email': 'ada@mau.edu.ng', 'password': 'Secret123'})

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/student/dashboard')
    with client.session_transaction() as sess:
        assert sess['role'] == 'student'


def test_login_trims_whitespace_around_email(client, make_user):
    make_user('ada@mau.edu.ng', role='admin', password='Secret123')

    response = client.post('/login', data={'email': '  ada@mau.edu.ng  ', 'password': 'Secret123'})

    assert response.headers['Location'].endswith('/admin/dashboard')


@pytest.mark.parametrize(
    'email, password',
    [
        ('ada@mau.edu.ng', 'wrong-password'),
        ('nobody@mau.edu.ng', 'Secret123'),
        ('', ''),
    ],
)
def test_login_with_invalid_credentials_shows_error(client, make_user, email, password):
    make_user('ada@mau.edu.ng', role='student', password='Secret123')

    response = client.post('/login', data={'email': email, 'password': password})

    assert response.status_code == 200
    assert b'Invalid email or password.' in response.data
    with client.session_transaction() as sess:
        assert 'user_id' not in sess


def test_login_page_redirects_already_authenticated_user(client, student, login):
    login(student)
    response = client.get('/login')
    assert response.headers['Location'].endswith('/student/dashboard')


def test_register_creates_student_with_generated_student_id(client):
    response = client.post(
        '/register',
        data={
            'full_name': 'Ada Lovelace',
            'email': 'ada@mau.edu.ng',
            'password': 'Secret123',
            'phone': '0700000000',
            'department': 'Computer Science',
        },
    )

    assert response.headers['Location'].endswith('/login')
    user = User.query.filter_by(email='ada@mau.edu.ng').one()
    assert user.role == 'student'
    assert user.department == 'Computer Science'
    assert user.student_id.startswith('STU')
    assert user.check_password('Secret123')


@pytest.mark.parametrize('missing', ['full_name', 'email', 'password'])
def test_register_requires_mandatory_fields(client, missing):
    data = {'full_name': 'Ada', 'email': 'ada@mau.edu.ng', 'password': 'Secret123'}
    data[missing] = ''

    response = client.post('/register', data=data)

    assert b'Please fill all required fields.' in response.data
    assert User.query.count() == 0


def test_register_rejects_duplicate_email(client, make_user):
    make_user('ada@mau.edu.ng')

    response = client.post(
        '/register',
        data={'full_name': 'Ada Two', 'email': 'ada@mau.edu.ng', 'password': 'Secret123'},
    )

    assert b'An account with this email already exists.' in response.data
    assert User.query.filter_by(email='ada@mau.edu.ng').count() == 1


def test_register_page_renders(client):
    assert client.get('/register').status_code == 200


@pytest.fixture
def logged_in_admin(make_user, login):
    admin = make_user('office-admin@mau.edu.ng', role='admin')
    login(admin)
    return admin


@pytest.mark.parametrize('role', ['department', 'library', 'finance', 'dormitory', 'registrar'])
def test_register_office_creates_staff_account(client, logged_in_admin, role):
    response = client.post(
        '/register/office',
        data={
            'full_name': 'Office Staff',
            'email': f'{role}@mau.edu.ng',
            'password': 'Secret123',
            'phone': '0700000000',
            'role': role,
        },
    )

    assert response.headers['Location'].endswith('/login')
    user = User.query.filter_by(email=f'{role}@mau.edu.ng').one()
    assert user.role == role
    assert user.department == role.title()
    assert user.student_id is None


@pytest.mark.parametrize('role', ['', 'student', 'admin', 'unknown'])
def test_register_office_rejects_non_office_roles(client, logged_in_admin, role):
    response = client.post(
        '/register/office',
        data={'full_name': 'Staff', 'email': 'staff@mau.edu.ng', 'password': 'Secret123', 'role': role},
    )

    assert b'Please choose an office role.' in response.data
    assert User.query.filter_by(email='staff@mau.edu.ng').count() == 0


def test_register_office_requires_mandatory_fields(client, logged_in_admin):
    response = client.post(
        '/register/office',
        data={'full_name': '', 'email': 'staff@mau.edu.ng', 'password': 'Secret123', 'role': 'library'},
    )

    assert b'Please fill all required fields.' in response.data
    assert User.query.filter_by(email='staff@mau.edu.ng').count() == 0


def test_register_office_rejects_short_password(client, logged_in_admin):
    response = client.post(
        '/register/office',
        data={'full_name': 'Staff', 'email': 'staff@mau.edu.ng', 'password': 'short', 'role': 'library'},
    )

    assert b'Password must be at least 8 characters.' in response.data
    assert User.query.filter_by(email='staff@mau.edu.ng').count() == 0


@pytest.mark.parametrize('method', ['get', 'post'])
def test_register_office_is_admin_only(client, student, login, method):
    login(student)

    response = getattr(client, method)(
        '/register/office',
        data={'full_name': 'Staff', 'email': 'staff@mau.edu.ng', 'password': 'Secret123', 'role': 'library'},
    )

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')
    assert User.query.filter_by(email='staff@mau.edu.ng').count() == 0


def test_register_office_rejects_duplicate_email(client, logged_in_admin, make_user):
    make_user('lib@mau.edu.ng', role='library')

    response = client.post(
        '/register/office',
        data={'full_name': 'Staff', 'email': 'lib@mau.edu.ng', 'password': 'Secret123', 'role': 'library'},
    )

    assert b'An account with this email already exists.' in response.data
    assert User.query.filter_by(email='lib@mau.edu.ng').count() == 1


def test_register_office_page_renders(client, logged_in_admin):
    assert client.get('/register/office').status_code == 200


def test_logout_clears_session(client, student, login):
    login(student)

    response = client.get('/logout')

    assert response.headers['Location'].endswith('/login')
    with client.session_transaction() as sess:
        assert 'user_id' not in sess
        assert 'role' not in sess


@pytest.mark.parametrize(
    'path',
    [
        '/student/dashboard',
        '/student/apply',
        '/student/status',
        '/student/profile',
        '/admin/dashboard',
        '/admin/students',
        '/admin/applications',
        '/admin/reports',
        '/admin/users',
        '/office/students',
        '/office/profile',
        '/department/approve',
        '/library/approve',
        '/finance/approve',
        '/registrar/approve',
        '/dormitary/approve',
        '/registrar/certificate',
    ],
)
def test_protected_pages_redirect_anonymous_users_to_login(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')


@pytest.mark.parametrize(
    'path',
    [
        '/admin/dashboard',
        '/admin/users',
        '/department/approve',
        '/library/approve',
        '/finance/approve',
        '/registrar/approve',
        '/dormitary/approve',
        '/office/profile',
    ],
)
def test_student_cannot_reach_staff_pages(client, student, login, path):
    login(student)
    response = client.get(path)
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')


def test_uploaded_file_route_serves_photo_to_its_owner(client, flask_app, student, login, make_application):
    upload_folder = flask_app.config['UPLOAD_FOLDER']
    with open(f'{upload_folder}/photo.png', 'wb') as handle:
        handle.write(b'photo-bytes')
    make_application(student, photo_path='photo.png')
    login(student)

    response = client.get('/uploads/photo.png')

    assert response.status_code == 200
    assert response.data == b'photo-bytes'


def test_uploaded_file_route_hides_other_students_photos(client, flask_app, student, make_user, login, make_application):
    upload_folder = flask_app.config['UPLOAD_FOLDER']
    with open(f'{upload_folder}/photo.png', 'wb') as handle:
        handle.write(b'photo-bytes')
    make_application(student, photo_path='photo.png')
    login(make_user('other@mau.edu.ng', role='student'))

    assert client.get('/uploads/photo.png').status_code == 403


def test_uploaded_file_route_requires_login(client):
    response = client.get('/uploads/photo.png')

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')


def test_uploaded_file_route_returns_404_for_missing_file(client, make_user, login):
    login(make_user('registrar@mau.edu.ng', role='registrar'))
    assert client.get('/uploads/missing.png').status_code == 404


def test_assets_route_serves_static_asset(client):
    assert client.get('/assets/css/style.css').status_code == 200
