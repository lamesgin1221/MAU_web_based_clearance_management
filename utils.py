"""Framework level helpers shared by the clearance views."""
import base64
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from urllib import error as urlerror, parse, request as urlrequest

from flask import request
from werkzeug.utils import secure_filename


def form_value(name):
    return request.form.get(name, '').strip()


def form_values(*names):
    return tuple(form_value(name) for name in names)


def apply_optional_updates(instance, field_map):
    """Assign submitted values to ``instance``, keeping current ones when blank.

    ``field_map`` maps attribute names to the form field they are read from.
    """
    for attribute, field in field_map.items():
        value = form_value(field)
        if value:
            setattr(instance, attribute, value)


def save_uploaded_photo(upload_folder, field='photo'):
    if field not in request.files:
        return None
    file = request.files[field]
    if not file or not file.filename:
        return None
    unique_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
    file.save(upload_folder / unique_name)
    return unique_name


def delete_photo(upload_folder, photo_name):
    if not photo_name:
        return
    photo_file = upload_folder / photo_name
    if photo_file.exists():
        photo_file.unlink()


def send_email_to_student(user, message):
    email_address = getattr(user, 'email', '')
    if not email_address:
        return False

    try:
        msg = EmailMessage()
        msg['Subject'] = 'MAU Clearance Update'
        msg['From'] = os.environ.get('MAIL_FROM', 'noreply@mau.edu.ng')
        msg['To'] = email_address
        msg.set_content(message)

        smtp_server = os.environ.get('MAIL_SERVER', 'localhost')
        smtp_port = int(os.environ.get('MAIL_PORT', '25'))
        smtp_username = os.environ.get('MAIL_USERNAME')
        smtp_password = os.environ.get('MAIL_PASSWORD')

        with smtplib.SMTP(smtp_server, smtp_port) as smtp:
            if smtp_username and smtp_password:
                smtp.starttls()
                smtp.login(smtp_username, smtp_password)
            smtp.send_message(msg)
        return True
    except Exception:
        return False


def send_sms_to_student(user, message):
    phone_number = getattr(user, 'phone', '')
    if not phone_number:
        return False

    try:
        account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
        auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
        from_number = os.environ.get('TWILIO_FROM_NUMBER')
        if not (account_sid and auth_token and from_number):
            return False

        payload = parse.urlencode({
            'To': phone_number,
            'From': from_number,
            'Body': message,
        }).encode()
        auth = f'{account_sid}:{auth_token}'.encode('utf-8')
        req = urlrequest.Request(
            f'https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json',
            data=payload,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            method='POST',
        )
        req.add_header('Authorization', 'Basic ' + base64.b64encode(auth).decode('ascii'))
        with urlrequest.urlopen(req, timeout=10) as response:
            response.read()
        return True
    except (urlerror.URLError, urlerror.HTTPError, Exception):
        return False


def send_notification_to_student(user, message):
    if send_email_to_student(user, message):
        return True
    return send_sms_to_student(user, message)
