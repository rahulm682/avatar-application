"""Emails for the account flows. Locally they are caught by Mailpit (http://localhost:8025)."""
import logging
import threading
from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import EmailMessage

from . import tokens

logger = logging.getLogger(__name__)


def _frontend_url(path, **params):
    return f"{settings.FRONTEND_BASE_URL.rstrip('/')}{path}?{urlencode(params)}"


def _deliver(message):
    try:
        message.send()
    except Exception:  # noqa: BLE001 - a mail failure must never break the request
        logger.exception("Failed to send email to %s", message.to)


def send_email(to, subject, body):
    message = EmailMessage(subject=subject, body=body, to=[to])
    if settings.EMAIL_SEND_ASYNC:
        threading.Thread(target=_deliver, args=(message,), daemon=True).start()
    else:
        _deliver(message)


def send_verification_email(user):
    link = _frontend_url("/verify-email", token=tokens.make_verification_token(user))
    hours = settings.EMAIL_VERIFICATION_MAX_AGE // 3600
    send_email(
        user.email,
        "Confirm your email address",
        f"Welcome!\n\nConfirm your email address to finish creating your account:\n\n{link}\n\n"
        f"This link is valid for {hours} hours. If you did not sign up, you can ignore this email.\n",
    )


def send_registration_notice(email):
    """Sent when someone signs up with an address that already has an account."""
    link = _frontend_url("/forgot-password")
    send_email(
        email,
        "Someone tried to create an account with your email",
        "Someone just tried to sign up using this email address, but an account already exists.\n\n"
        f"If it was you, log in normally, or reset your password here:\n\n{link}\n\n"
        "If it was not you, you can ignore this email.\n",
    )


def send_password_reset_email(user):
    uid, token = tokens.make_password_reset_parts(user)
    link = _frontend_url("/reset-password", uid=uid, token=token)
    minutes = settings.PASSWORD_RESET_TIMEOUT // 60
    send_email(
        user.email,
        "Reset your password",
        f"Use this link to choose a new password:\n\n{link}\n\n"
        f"The link is valid for {minutes} minutes and stops working once the password changes. "
        "If you did not ask for this, you can ignore this email.\n",
    )


def send_email_change_email(user, new_email):
    link = _frontend_url("/confirm-email-change", token=tokens.make_email_change_token(user, new_email))
    hours = settings.EMAIL_CHANGE_MAX_AGE // 3600
    send_email(
        new_email,
        "Confirm your new email address",
        f"Confirm that this should be the email address for your account:\n\n{link}\n\n"
        f"The link is valid for {hours} hours. If you did not ask for this, you can ignore this email.\n",
    )


def send_email_in_use_notice(email):
    """Sent when someone tries to move their account to an address that already belongs to another account."""
    send_email(
        email,
        "This email is already in use",
        "Someone tried to use this email address for a different account, but it already belongs to an account.\n\n"
        "If it was you, there is nothing to do. If it was not you, you can ignore this email.\n",
    )
