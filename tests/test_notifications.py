import smtplib
from urllib import error as urlerror

import pytest

import app as app_module
from app import send_email_to_student, send_notification_to_student, send_sms_to_student


class Recipient:
    def __init__(self, email='', phone=''):
        self.email = email
        self.phone = phone


class FakeSMTP:
    instances = []

    def __init__(self, server, port):
        self.server = server
        self.port = port
        self.started_tls = False
        self.credentials = None
        self.messages = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.credentials = (username, password)

    def send_message(self, msg):
        self.messages.append(msg)


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, 'SMTP', FakeSMTP)
    return FakeSMTP


def test_send_email_returns_false_without_email_address(fake_smtp):
    assert send_email_to_student(Recipient(), 'hello') is False
    assert fake_smtp.instances == []


def test_send_email_uses_configured_server_and_sender(fake_smtp, monkeypatch):
    monkeypatch.setenv('MAIL_SERVER', 'smtp.example.org')
    monkeypatch.setenv('MAIL_PORT', '2525')
    monkeypatch.setenv('MAIL_FROM', 'clearance@mau.edu.ng')
    monkeypatch.delenv('MAIL_USERNAME', raising=False)
    monkeypatch.delenv('MAIL_PASSWORD', raising=False)

    assert send_email_to_student(Recipient(email='ada@mau.edu.ng'), 'Approved') is True

    smtp = fake_smtp.instances[0]
    assert (smtp.server, smtp.port) == ('smtp.example.org', 2525)
    assert smtp.started_tls is False
    assert smtp.credentials is None

    message = smtp.messages[0]
    assert message['To'] == 'ada@mau.edu.ng'
    assert message['From'] == 'clearance@mau.edu.ng'
    assert message['Subject'] == 'MAU Clearance Update'
    assert message.get_content().strip() == 'Approved'


def test_send_email_authenticates_when_credentials_present(fake_smtp, monkeypatch):
    monkeypatch.setenv('MAIL_USERNAME', 'mailer')
    monkeypatch.setenv('MAIL_PASSWORD', 'secret')

    assert send_email_to_student(Recipient(email='ada@mau.edu.ng'), 'Approved') is True

    smtp = fake_smtp.instances[0]
    assert smtp.started_tls is True
    assert smtp.credentials == ('mailer', 'secret')


def test_send_email_returns_false_when_smtp_fails(monkeypatch):
    def explode(*args, **kwargs):
        raise smtplib.SMTPException('no server')

    monkeypatch.setattr(smtplib, 'SMTP', explode)
    assert send_email_to_student(Recipient(email='ada@mau.edu.ng'), 'Approved') is False


def test_send_email_returns_false_for_invalid_port(monkeypatch, fake_smtp):
    monkeypatch.setenv('MAIL_PORT', 'not-a-port')
    assert send_email_to_student(Recipient(email='ada@mau.edu.ng'), 'Approved') is False


@pytest.fixture
def twilio_env(monkeypatch):
    monkeypatch.setenv('TWILIO_ACCOUNT_SID', 'AC123')
    monkeypatch.setenv('TWILIO_AUTH_TOKEN', 'token123')
    monkeypatch.setenv('TWILIO_FROM_NUMBER', '+15550000')


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self):
        return b'{"sid": "SM123"}'


def test_send_sms_returns_false_without_phone_number(twilio_env):
    assert send_sms_to_student(Recipient(email='ada@mau.edu.ng'), 'hello') is False


@pytest.mark.parametrize('missing', ['TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_FROM_NUMBER'])
def test_send_sms_returns_false_when_credentials_incomplete(twilio_env, monkeypatch, missing):
    monkeypatch.delenv(missing)
    assert send_sms_to_student(Recipient(phone='+15551111'), 'hello') is False


def test_send_sms_posts_authenticated_request_to_twilio(twilio_env, monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured['url'] = req.full_url
        captured['method'] = req.get_method()
        captured['data'] = req.data.decode()
        captured['headers'] = dict(req.header_items())
        captured['timeout'] = timeout
        return FakeResponse()

    monkeypatch.setattr(app_module.urlrequest, 'urlopen', fake_urlopen)

    assert send_sms_to_student(Recipient(phone='+15551111'), 'Clearance approved') is True

    assert captured['url'] == 'https://api.twilio.com/2010-04-01/Accounts/AC123/Messages.json'
    assert captured['method'] == 'POST'
    assert 'To=%2B15551111' in captured['data']
    assert 'Body=Clearance+approved' in captured['data']
    assert captured['timeout'] == 10
    assert captured['headers']['Authorization'].startswith('Basic ')


def test_send_sms_returns_false_on_network_error(twilio_env, monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise urlerror.URLError('unreachable')

    monkeypatch.setattr(app_module.urlrequest, 'urlopen', fake_urlopen)
    assert send_sms_to_student(Recipient(phone='+15551111'), 'hello') is False


def test_send_notification_prefers_email(monkeypatch):
    calls = []
    monkeypatch.setattr(app_module, 'send_email_to_student', lambda u, m: calls.append('email') or True)
    monkeypatch.setattr(app_module, 'send_sms_to_student', lambda u, m: calls.append('sms') or True)

    assert send_notification_to_student(Recipient(email='ada@mau.edu.ng'), 'hi') is True
    assert calls == ['email']


def test_send_notification_falls_back_to_sms(monkeypatch):
    calls = []
    monkeypatch.setattr(app_module, 'send_email_to_student', lambda u, m: calls.append('email') and False)
    monkeypatch.setattr(app_module, 'send_sms_to_student', lambda u, m: calls.append('sms') or True)

    assert send_notification_to_student(Recipient(phone='+15551111'), 'hi') is True
    assert calls == ['email', 'sms']


def test_send_notification_returns_false_when_both_channels_fail(monkeypatch):
    monkeypatch.setattr(app_module, 'send_email_to_student', lambda u, m: False)
    monkeypatch.setattr(app_module, 'send_sms_to_student', lambda u, m: False)

    assert send_notification_to_student(Recipient(), 'hi') is False
