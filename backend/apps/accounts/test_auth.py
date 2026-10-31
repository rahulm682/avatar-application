"""Tests for the authentication and account endpoints (Step 3)."""
import re
from datetime import timedelta
from urllib.parse import unquote

from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .emailhash import hash_email
from .models import User

ORIGIN = "http://localhost:5173"  # must be in CORS_ALLOWED_ORIGINS
PASSWORD = "correct-horse-battery-staple-9"
NEW_PASSWORD = "another-strong-password-77"
BAD_LOGIN = {"detail": "Email or password is wrong."}

REGISTER = "/api/auth/register/"
VERIFY = "/api/auth/verify-email/"
RESEND = "/api/auth/resend-verification/"
LOGIN = "/api/auth/login/"
REFRESH = "/api/auth/refresh/"
LOGOUT = "/api/auth/logout/"
RESET_REQUEST = "/api/auth/password-reset/request/"
RESET_CONFIRM = "/api/auth/password-reset/confirm/"
CHANGE_PASSWORD = "/api/auth/change-password/"
EMAIL_CHANGE_REQUEST = "/api/auth/email-change/request/"
EMAIL_CHANGE_CONFIRM = "/api/auth/email-change/confirm/"
ME = "/api/me/"
COOKIE = "refresh_token"


def link_param(message, name):
    """Reads a query parameter from the link in an email body."""
    match = re.search(rf"[?&]{name}=([^\s&]+)", message.body)
    assert match, f"no '{name}' parameter in email body:\n{message.body}"
    return unquote(match.group(1))


@override_settings(EMAIL_SEND_ASYNC=False)
class AuthTestCase(TestCase):
    def setUp(self):
        cache.clear()  # rate-limit counters live in the cache
        self.client = APIClient()

    # ---- helpers ----
    def post(self, path, data=None, origin=True, **extra):
        if origin:
            extra["HTTP_ORIGIN"] = ORIGIN
        return self.client.post(path, data or {}, format="json", **extra)

    def make_user(self, email="user@example.com", password=PASSWORD, verified=True):
        return User.objects.create_user(
            email, password, email_verified_at=timezone.now() if verified else None
        )

    def login(self, email="user@example.com", password=PASSWORD):
        return self.post(LOGIN, {"email": email, "password": password})

    def login_and_authenticate(self, email="user@example.com", password=PASSWORD):
        response = self.login(email, password)
        self.assertEqual(response.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + response.json()["access"])
        return response

    def refresh_cookie(self):
        return self.client.cookies[COOKIE].value


class RegistrationTests(AuthTestCase):
    def test_register_creates_unverified_user_and_sends_link(self):
        response = self.post(REGISTER, {"email": "New@Example.com", "password": PASSWORD})
        self.assertEqual(response.status_code, 202)
        user = User.objects.get(email="new@example.com")
        self.assertIsNone(user.email_verified_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["new@example.com"])
        self.assertIn("/verify-email?token=", mail.outbox[0].body)

    def test_weak_password_is_rejected(self):
        response = self.post(REGISTER, {"email": "new@example.com", "password": "short"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.json())
        self.assertFalse(User.objects.filter(email="new@example.com").exists())

    def test_invalid_email_is_rejected(self):
        response = self.post(REGISTER, {"email": "not-an-email", "password": PASSWORD})
        self.assertEqual(response.status_code, 400)

    def test_response_is_identical_for_new_and_registered_emails(self):
        first = self.post(REGISTER, {"email": "new@example.com", "password": PASSWORD})
        User.objects.filter(email="new@example.com").update(email_verified_at=timezone.now())
        second = self.post(REGISTER, {"email": "new@example.com", "password": PASSWORD})
        self.assertEqual(first.status_code, second.status_code)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(User.objects.filter(email="new@example.com").count(), 1)
        # The existing owner gets a notice instead of a verification link.
        self.assertEqual(len(mail.outbox), 2)
        self.assertNotIn("/verify-email", mail.outbox[1].body)

    def test_new_signup_replaces_unverified_one_and_invalidates_old_link(self):
        self.post(REGISTER, {"email": "new@example.com", "password": PASSWORD})
        old_token = link_param(mail.outbox[0], "token")
        old_id = User.objects.get(email="new@example.com").pk

        self.post(REGISTER, {"email": "new@example.com", "password": NEW_PASSWORD})
        users = User.objects.filter(email="new@example.com")
        self.assertEqual(users.count(), 1)
        self.assertNotEqual(users[0].pk, old_id)
        self.assertEqual(self.post(VERIFY, {"token": old_token}).status_code, 400)

        new_token = link_param(mail.outbox[1], "token")
        self.assertEqual(self.post(VERIFY, {"token": new_token}).status_code, 200)


class VerificationTests(AuthTestCase):
    def register(self):
        self.post(REGISTER, {"email": "new@example.com", "password": PASSWORD})
        return link_param(mail.outbox[-1], "token")

    def test_valid_token_verifies_the_user(self):
        token = self.register()
        response = self.post(VERIFY, {"token": token})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.get(email="new@example.com").is_email_verified)

    def test_verifying_twice_is_harmless(self):
        token = self.register()
        self.assertEqual(self.post(VERIFY, {"token": token}).status_code, 200)
        self.assertEqual(self.post(VERIFY, {"token": token}).status_code, 200)

    def test_tampered_token_is_rejected(self):
        token = self.register()
        self.assertEqual(self.post(VERIFY, {"token": token + "x"}).status_code, 400)
        self.assertFalse(User.objects.get(email="new@example.com").is_email_verified)

    def test_expired_token_is_rejected(self):
        token = self.register()
        with override_settings(EMAIL_VERIFICATION_MAX_AGE=-1):
            self.assertEqual(self.post(VERIFY, {"token": token}).status_code, 400)

    def test_resend_is_generic_and_only_sends_for_unverified_accounts(self):
        self.make_user("verified@example.com")
        self.make_user("pending@example.com", verified=False)
        a = self.post(RESEND, {"email": "verified@example.com"})
        b = self.post(RESEND, {"email": "pending@example.com"})
        c = self.post(RESEND, {"email": "nobody@example.com"})
        self.assertEqual([a.status_code, b.status_code, c.status_code], [202, 202, 202])
        self.assertEqual(a.json(), b.json())
        self.assertEqual(b.json(), c.json())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["pending@example.com"])


class LoginTests(AuthTestCase):
    def test_login_returns_access_token_and_httponly_refresh_cookie(self):
        self.make_user()
        response = self.login()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("access", body)
        self.assertNotIn("refresh", body)  # the refresh token must never be in the body
        self.assertEqual(body["user"]["email"], "user@example.com")
        cookie = response.cookies[COOKIE]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["path"], "/api/auth/")
        self.assertEqual(cookie["samesite"], "Lax")  # relaxed in dev settings

    def test_failures_are_indistinguishable(self):
        self.make_user("verified@example.com")
        self.make_user("pending@example.com", verified=False)
        responses = [
            self.login("nobody@example.com", PASSWORD),  # unknown email
            self.login("verified@example.com", "wrong-password-123"),  # wrong password
            self.login("pending@example.com", PASSWORD),  # right password, unverified
        ]
        for response in responses:
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json(), BAD_LOGIN)

    def test_email_is_normalized_on_login(self):
        self.make_user()
        self.assertEqual(self.login("  USER@Example.com ").status_code, 200)

    def test_inactive_user_cannot_log_in(self):
        user = self.make_user()
        user.is_active = False
        user.save()
        self.assertEqual(self.login().status_code, 401)

    def test_too_many_attempts_for_one_email_are_throttled(self):
        self.make_user()
        statuses = [self.login(password="wrong-password-123").status_code for _ in range(6)]
        self.assertEqual(statuses, [401, 401, 401, 401, 401, 429])


class RefreshAndLogoutTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        self.make_user()
        self.login()

    def test_refresh_rotates_the_token(self):
        old = self.refresh_cookie()
        response = self.post(REFRESH)
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())
        self.assertNotEqual(self.refresh_cookie(), old)

    def test_an_old_refresh_token_cannot_be_reused(self):
        old = self.refresh_cookie()
        self.assertEqual(self.post(REFRESH).status_code, 200)
        self.client.cookies[COOKIE] = old
        self.assertEqual(self.post(REFRESH).status_code, 401)

    def test_refresh_without_cookie_is_unauthorized(self):
        self.client.cookies[COOKIE] = ""
        self.assertEqual(self.post(REFRESH).status_code, 401)

    def test_refresh_rejects_missing_or_foreign_origin(self):
        self.assertEqual(self.post(REFRESH, origin=False).status_code, 403)
        self.assertEqual(self.post(REFRESH, origin=False, HTTP_ORIGIN="https://evil.example").status_code, 403)

    def test_refresh_requires_json_content_type(self):
        response = self.client.generic("POST", REFRESH, "", content_type="text/plain", HTTP_ORIGIN=ORIGIN)
        self.assertEqual(response.status_code, 403)

    def test_logout_revokes_the_token_and_clears_the_cookie(self):
        old = self.refresh_cookie()
        response = self.post(LOGOUT)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.refresh_cookie(), "")
        self.client.cookies[COOKIE] = old
        self.assertEqual(self.post(REFRESH).status_code, 401)

    def test_logout_rejects_foreign_origin(self):
        self.assertEqual(self.post(LOGOUT, origin=False, HTTP_ORIGIN="https://evil.example").status_code, 403)


class ProfileTests(AuthTestCase):
    def test_me_requires_login(self):
        self.assertEqual(self.client.get(ME).status_code, 401)

    def test_get_and_update_profile(self):
        self.make_user()
        self.login_and_authenticate()
        profile = self.client.get(ME).json()
        self.assertEqual(profile["email"], "user@example.com")
        self.assertEqual(profile["email_hash"], hash_email("user@example.com"))
        self.assertTrue(profile["avatar_url"].endswith("/avatar/" + profile["email_hash"]))

        response = self.client.patch(ME, {"display_name": "Sam", "bio": "Hello there"}, format="json")
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(email="user@example.com")
        self.assertEqual((user.display_name, user.bio), ("Sam", "Hello there"))

    def test_email_cannot_be_changed_through_profile_update(self):
        self.make_user()
        self.login_and_authenticate()
        self.client.patch(ME, {"email": "other@example.com"}, format="json")
        self.assertEqual(User.objects.get().email, "user@example.com")

    def test_display_name_length_is_limited(self):
        self.make_user()
        self.login_and_authenticate()
        response = self.client.patch(ME, {"display_name": "x" * 81}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_delete_account_requires_the_password(self):
        self.make_user()
        self.login_and_authenticate()
        response = self.client.delete(ME, {"password": "wrong-password-123"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 1)

        response = self.client.delete(ME, {"password": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(User.objects.count(), 0)


class PasswordResetTests(AuthTestCase):
    def test_request_is_generic_and_only_emails_verified_accounts(self):
        self.make_user("verified@example.com")
        self.make_user("pending@example.com", verified=False)
        a = self.post(RESET_REQUEST, {"email": "verified@example.com"})
        b = self.post(RESET_REQUEST, {"email": "pending@example.com"})
        c = self.post(RESET_REQUEST, {"email": "nobody@example.com"})
        self.assertEqual([a.status_code, b.status_code, c.status_code], [202, 202, 202])
        self.assertEqual(a.json(), c.json())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["verified@example.com"])

    def request_link(self):
        self.post(RESET_REQUEST, {"email": "user@example.com"})
        message = mail.outbox[-1]
        return link_param(message, "uid"), link_param(message, "token")

    def test_reset_sets_new_password_and_revokes_sessions(self):
        self.make_user()
        self.login()  # this device's refresh cookie
        uid, token = self.request_link()

        response = self.post(RESET_CONFIRM, {"uid": uid, "token": token, "new_password": NEW_PASSWORD})
        self.assertEqual(response.status_code, 200)

        self.assertEqual(self.login(password=PASSWORD).status_code, 401)
        self.assertEqual(self.login(password=NEW_PASSWORD).status_code, 200)

    def test_existing_sessions_are_revoked(self):
        self.make_user()
        self.login()
        old_cookie = self.refresh_cookie()
        uid, token = self.request_link()
        self.post(RESET_CONFIRM, {"uid": uid, "token": token, "new_password": NEW_PASSWORD})
        self.client.cookies[COOKIE] = old_cookie
        self.assertEqual(self.post(REFRESH).status_code, 401)

    def test_link_cannot_be_used_twice(self):
        self.make_user()
        uid, token = self.request_link()
        data = {"uid": uid, "token": token, "new_password": NEW_PASSWORD}
        self.assertEqual(self.post(RESET_CONFIRM, data).status_code, 200)
        self.assertEqual(self.post(RESET_CONFIRM, data).status_code, 400)

    def test_weak_password_is_rejected_and_link_stays_valid(self):
        self.make_user()
        uid, token = self.request_link()
        weak = self.post(RESET_CONFIRM, {"uid": uid, "token": token, "new_password": "short"})
        self.assertEqual(weak.status_code, 400)
        self.assertIn("new_password", weak.json())
        ok = self.post(RESET_CONFIRM, {"uid": uid, "token": token, "new_password": NEW_PASSWORD})
        self.assertEqual(ok.status_code, 200)

    def test_invalid_uid_or_token_is_rejected(self):
        self.make_user()
        uid, token = self.request_link()
        bad_uid = self.post(RESET_CONFIRM, {"uid": "not-valid", "token": token, "new_password": NEW_PASSWORD})
        bad_token = self.post(RESET_CONFIRM, {"uid": uid, "token": "bad-token", "new_password": NEW_PASSWORD})
        self.assertEqual(bad_uid.status_code, 400)
        self.assertEqual(bad_token.status_code, 400)


class ChangePasswordTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        self.make_user()
        self.login_and_authenticate()

    def test_change_password_revokes_old_sessions_but_keeps_this_device_logged_in(self):
        old_cookie = self.refresh_cookie()
        response = self.client.post(
            CHANGE_PASSWORD, {"current_password": PASSWORD, "new_password": NEW_PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())

        new_cookie = self.refresh_cookie()
        self.assertNotEqual(new_cookie, old_cookie)
        self.assertEqual(self.post(REFRESH).status_code, 200)  # new session works

        self.client.cookies[COOKIE] = old_cookie
        self.assertEqual(self.post(REFRESH).status_code, 401)  # old one is revoked

    def test_wrong_current_password_is_rejected(self):
        response = self.client.post(
            CHANGE_PASSWORD, {"current_password": "wrong-password-123", "new_password": NEW_PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_weak_new_password_is_rejected(self):
        response = self.client.post(
            CHANGE_PASSWORD, {"current_password": PASSWORD, "new_password": "short"}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_requires_login(self):
        self.client.credentials()
        response = self.client.post(
            CHANGE_PASSWORD, {"current_password": PASSWORD, "new_password": NEW_PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 401)


class EmailChangeTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.login_and_authenticate()

    def request_change(self, new_email="new@example.com", password=PASSWORD):
        return self.client.post(
            EMAIL_CHANGE_REQUEST, {"new_email": new_email, "password": password}, format="json"
        )

    def test_full_flow_updates_email_and_hash(self):
        self.assertEqual(self.request_change("New@Example.com").status_code, 202)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["new@example.com"])
        token = link_param(mail.outbox[0], "token")

        response = self.post(EMAIL_CHANGE_CONFIRM, {"token": token})
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new@example.com")
        self.assertEqual(self.user.email_hash, hash_email("new@example.com"))
        self.assertTrue(self.user.is_email_verified)

        self.assertEqual(self.login("new@example.com").status_code, 200)
        self.assertEqual(self.login("user@example.com").status_code, 401)

    def test_link_cannot_be_replayed(self):
        self.request_change()
        token = link_param(mail.outbox[0], "token")
        self.assertEqual(self.post(EMAIL_CHANGE_CONFIRM, {"token": token}).status_code, 200)
        self.assertEqual(self.post(EMAIL_CHANGE_CONFIRM, {"token": token}).status_code, 400)

    def test_wrong_password_and_same_email_are_rejected(self):
        self.assertEqual(self.request_change(password="wrong-password-123").status_code, 400)
        self.assertEqual(self.request_change("user@example.com").status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    def test_email_used_by_another_account_gets_the_same_answer_but_no_link(self):
        self.make_user("taken@example.com")
        ok = self.request_change("free@example.com")
        taken = self.request_change("taken@example.com")
        self.assertEqual(ok.status_code, taken.status_code)
        self.assertEqual(ok.json(), taken.json())
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[1].to, ["taken@example.com"])
        self.assertNotIn("confirm-email-change", mail.outbox[1].body)

    def test_confirm_fails_if_the_address_was_taken_meanwhile(self):
        self.request_change("free@example.com")
        token = link_param(mail.outbox[0], "token")
        self.make_user("free@example.com")
        self.assertEqual(self.post(EMAIL_CHANGE_CONFIRM, {"token": token}).status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "user@example.com")

    def test_stale_unverified_account_does_not_block_the_change(self):
        self.make_user("stale@example.com", verified=False)
        self.request_change("stale@example.com")
        token = link_param(mail.outbox[0], "token")
        self.assertEqual(self.post(EMAIL_CHANGE_CONFIRM, {"token": token}).status_code, 200)
        self.assertEqual(User.objects.filter(email="stale@example.com").count(), 1)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "stale@example.com")


class CleanupCommandTests(TestCase):
    def test_removes_only_old_unverified_regular_accounts(self):
        old_unverified = User.objects.create_user("old@example.com", PASSWORD)
        recent_unverified = User.objects.create_user("recent@example.com", PASSWORD)
        old_verified = User.objects.create_user("verified@example.com", PASSWORD, email_verified_at=timezone.now())
        old_staff = User.objects.create_user("staff@example.com", PASSWORD, is_staff=True)
        long_ago = timezone.now() - timedelta(hours=48)
        User.objects.filter(pk__in=[old_unverified.pk, old_verified.pk, old_staff.pk]).update(created_at=long_ago)

        call_command("cleanup_unverified")

        remaining = set(User.objects.values_list("email", flat=True))
        self.assertEqual(remaining, {"recent@example.com", "verified@example.com", "staff@example.com"})
