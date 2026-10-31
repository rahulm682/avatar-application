"""Stateless signed tokens for emailed links (design doc, section 6). No token table is needed.

- Email verification and email change use django.core.signing (HMAC signature plus timestamp).
- Password reset uses Django's PasswordResetTokenGenerator, which is bound to the current password hash,
  so a reset link stops working as soon as the password changes.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.exceptions import ValidationError
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

VERIFY_EMAIL = "verify_email"
CHANGE_EMAIL = "change_email"
_SALTS = {VERIFY_EMAIL: "accounts.verify-email", CHANGE_EMAIL: "accounts.change-email"}


def _make(purpose, payload):
    return signing.dumps({**payload, "purpose": purpose}, salt=_SALTS[purpose])


def _read(purpose, token, max_age):
    try:
        payload = signing.loads(token, salt=_SALTS[purpose], max_age=max_age)
    except signing.BadSignature:  # includes SignatureExpired
        return None
    if not isinstance(payload, dict) or payload.get("purpose") != purpose:
        return None
    return payload


# ---- email verification ----
def make_verification_token(user):
    return _make(VERIFY_EMAIL, {"uid": str(user.pk), "email": user.email})


def read_verification_token(token):
    return _read(VERIFY_EMAIL, token, settings.EMAIL_VERIFICATION_MAX_AGE)


# ---- email change ----
def make_email_change_token(user, new_email):
    # old_email_hash ties the link to the current email, so it cannot be replayed after the change.
    return _make(CHANGE_EMAIL, {"uid": str(user.pk), "new_email": new_email, "old_email_hash": user.email_hash})


def read_email_change_token(token):
    return _read(CHANGE_EMAIL, token, settings.EMAIL_CHANGE_MAX_AGE)


# ---- password reset ----
def make_password_reset_parts(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    return uid, default_token_generator.make_token(user)


def user_from_uid(uid):
    User = get_user_model()
    try:
        return User.objects.get(pk=force_str(urlsafe_base64_decode(uid)))
    except (TypeError, ValueError, OverflowError, ValidationError, User.DoesNotExist):
        return None


def check_password_reset_token(user, token):
    return default_token_generator.check_token(user, token)
