"""Soft delete, restore and purge for accounts (Step 9). S3 is replaced by an in-memory fake."""
import hashlib
import uuid
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.avatars import fallbacks, imaging, storage
from apps.avatars.models import Avatar
from apps.avatars.public_views import find_current_avatar
from apps.avatars.services import delete_avatar
from apps.avatars.tests import S3_SETTINGS, FakeStorage, make_image
from apps.moderation.models import Report

from . import services
from .emailhash import hash_email
from .models import User

PASSWORD = "correct-horse-battery-staple-9"
ORIGIN = "http://localhost:5173"


@override_settings(ORIGIN_VERIFY_SECRET="", EMAIL_SEND_ASYNC=False, **S3_SETTINGS)
class SoftDeleteTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.fake = FakeStorage()
        patcher = patch.multiple(
            storage,
            put_object=self.fake.put_object,
            read_object=self.fake.read_object,
            delete_objects=self.fake.delete_objects,
            delete_prefix=self.fake.delete_prefix,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        # Each module imports the invalidation function under its own name, so each one is patched where it is used.
        self.account_invalidate = self.patch_name("apps.accounts.services.invalidate_email_hashes")
        self.avatar_invalidate = self.patch_name("apps.avatars.services.invalidate_email_hashes")

        self.user = User.objects.create_user("owner@example.com", PASSWORD, email_verified_at=timezone.now())
        self.old_email = self.user.email
        self.old_hash = self.user.email_hash
        self.first = self.make_avatar(self.user, (255, 0, 0))  # the current picture
        self.second = self.make_avatar(self.user, (0, 255, 0), make_current=False)
        self.api = APIClient()

    def patch_name(self, target):
        patcher = patch(target)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def make_user(self, email):
        return User.objects.create_user(email, PASSWORD, email_verified_at=timezone.now())

    def make_avatar(self, user, color, make_current=True):
        processed = imaging.process_upload(make_image(color=color), 4096)
        avatar_id = uuid.uuid4()
        key = storage.original_key(user.pk, avatar_id)
        self.fake.objects[key] = processed.data
        self.fake.objects[storage.derived_key(avatar_id, 160)] = b"preview"
        avatar = Avatar.objects.create(
            id=avatar_id, user=user, storage_key=key, content_hash=hashlib.sha256(processed.data).hexdigest(),
            size_bytes=len(processed.data), width=processed.width, height=processed.height,
        )
        if make_current:
            user.current_avatar = avatar
            user.save(update_fields=["current_avatar", "updated_at"])
        return avatar

    def deleted_user(self):
        return User.all_objects.get(pk=self.user.pk)


class AccountSoftDeleteTests(SoftDeleteTestCase):
    def test_account_is_hidden_and_marked_with_a_placeholder_email(self):
        services.soft_delete_user(self.user)

        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())  # invisible to normal lookups
        deleted = self.deleted_user()
        self.assertTrue(deleted.is_deleted)
        self.assertIsNotNone(deleted.deleted_at)
        self.assertEqual(deleted.original_email, self.old_email)
        self.assertEqual(deleted.email, f"deleted-{self.user.pk}@deleted.invalid")
        self.assertEqual(deleted.email_hash, hash_email(deleted.email))
        self.assertNotEqual(deleted.email_hash, self.old_hash)
        self.account_invalidate.assert_called_once_with(self.old_hash)

    def test_pictures_are_soft_deleted_too_and_their_files_stay(self):
        files_before = dict(self.fake.objects)
        services.soft_delete_user(self.user)
        self.assertEqual(Avatar.objects.count(), 0)
        self.assertEqual(Avatar.all_objects.filter(is_deleted=True).count(), 2)
        self.assertEqual(self.fake.objects, files_before)

    def test_deleting_through_the_api_logs_the_user_out_everywhere(self):
        login = self.api.post("/api/auth/login/", {"email": self.old_email, "password": PASSWORD}, format="json")
        self.assertEqual(login.status_code, 200)
        access = login.json()["access"]
        old_refresh_cookie = self.api.cookies["refresh_token"].value
        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        self.assertEqual(self.api.delete("/api/me/", {"password": PASSWORD}, format="json").status_code, 204)

        # the still-valid access token stops working at once
        self.assertEqual(self.api.get("/api/me/").status_code, 401)
        # the refresh token is revoked
        self.api.credentials()
        self.api.cookies["refresh_token"] = old_refresh_cookie
        self.assertEqual(self.api.post("/api/auth/refresh/", {}, format="json", HTTP_ORIGIN=ORIGIN).status_code, 401)
        # and the account cannot log in any more
        again = self.api.post("/api/auth/login/", {"email": self.old_email, "password": PASSWORD}, format="json")
        self.assertEqual(again.status_code, 401)

    def test_the_email_address_can_be_registered_again(self):
        services.soft_delete_user(self.user)
        response = self.api.post(
            "/api/auth/register/", {"email": self.old_email, "password": "another-strong-password-77"}, format="json"
        )
        self.assertEqual(response.status_code, 202)
        newcomer = User.objects.get(email=self.old_email)
        self.assertNotEqual(newcomer.pk, self.user.pk)
        self.assertEqual(User.all_objects.count(), 2)  # the deleted account is still there, waiting for the purge

    def test_the_public_picture_disappears(self):
        services.soft_delete_user(self.user)
        response = Client().get(f"/avatar/{self.old_hash}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, fallbacks.default_image(80))

    def test_a_deleted_account_cannot_be_reported_or_found_by_email(self):
        services.soft_delete_user(self.user)
        self.assertIsNone(find_current_avatar(self.old_hash))
        with self.assertRaises(User.DoesNotExist):
            User.objects.get_by_email(self.old_email)


class RestoreTests(SoftDeleteTestCase):
    def test_restore_brings_back_the_email_the_hash_and_the_pictures(self):
        services.soft_delete_user(self.user)
        services.restore_user(self.deleted_user())

        restored = User.objects.get(pk=self.user.pk)
        self.assertEqual(restored.email, self.old_email)
        self.assertEqual(restored.email_hash, self.old_hash)
        self.assertFalse(restored.is_deleted)
        self.assertEqual(restored.original_email, "")
        self.assertEqual(Avatar.objects.filter(user=restored).count(), 2)
        self.assertEqual(restored.current_avatar_id, self.first.pk)  # the current picture is current again
        self.assertEqual(find_current_avatar(self.old_hash).pk, self.first.pk)
        self.account_invalidate.assert_called_with(self.old_hash)

    def test_pictures_deleted_before_the_account_stay_deleted(self):
        delete_avatar(Avatar.objects.get(pk=self.second.pk))  # the user removed this one earlier
        services.soft_delete_user(self.user)
        services.restore_user(self.deleted_user())
        self.assertEqual(list(Avatar.objects.values_list("pk", flat=True)), [self.first.pk])
        self.assertTrue(Avatar.all_objects.get(pk=self.second.pk).is_deleted)

    def test_restore_is_refused_if_a_new_account_took_the_address(self):
        services.soft_delete_user(self.user)
        self.make_user(self.old_email)
        with self.assertRaises(services.RestoreError):
            services.restore_user(self.deleted_user())
        self.assertTrue(self.deleted_user().is_deleted)

    def test_restoring_a_live_account_does_nothing(self):
        services.restore_user(self.user)
        self.assertEqual(User.objects.get(pk=self.user.pk).email, self.old_email)


class PurgeTests(SoftDeleteTestCase):
    def test_purging_an_account_removes_everything_but_the_reports(self):
        report = Report.objects.create(
            avatar_uuid=self.first.pk, user_uuid=self.user.pk, email_hash=self.old_hash, reason="audit trail"
        )
        services.soft_delete_user(self.user)
        services.purge_user(self.deleted_user())

        self.assertFalse(User.all_objects.filter(pk=self.user.pk).exists())
        self.assertEqual(Avatar.all_objects.count(), 0)
        self.assertEqual(self.fake.objects, {})
        self.assertTrue(Report.objects.filter(pk=report.pk).exists())

    def age(self, *, users=(), avatars=(), days=40):
        long_ago = timezone.now() - timedelta(days=days)
        User.all_objects.filter(pk__in=[u.pk for u in users]).update(deleted_at=long_ago)
        Avatar.all_objects.filter(pk__in=[a.pk for a in avatars]).update(deleted_at=long_ago)

    def test_the_command_removes_only_what_is_older_than_the_retention_period(self):
        # an account deleted 40 days ago, and its pictures
        services.soft_delete_user(self.user)
        self.age(users=[self.user], avatars=[self.first, self.second])
        # another user: one picture deleted 40 days ago, one deleted 5 days ago
        other = self.make_user("other@example.com")
        old_one = self.make_avatar(other, (1, 2, 3))
        recent_one = self.make_avatar(other, (4, 5, 6), make_current=False)
        delete_avatar(Avatar.objects.get(pk=old_one.pk))
        delete_avatar(Avatar.objects.get(pk=recent_one.pk))
        self.age(avatars=[old_one], days=40)
        self.age(avatars=[recent_one], days=5)

        out = StringIO()
        call_command("purge_deleted", stdout=out)

        self.assertFalse(User.all_objects.filter(pk=self.user.pk).exists())
        self.assertFalse(Avatar.all_objects.filter(pk__in=[self.first.pk, self.second.pk, old_one.pk]).exists())
        self.assertTrue(Avatar.all_objects.filter(pk=recent_one.pk).exists())  # still inside the retention period
        self.assertTrue(any(str(recent_one.pk) in key for key in self.fake.objects))
        self.assertFalse(any(str(old_one.pk) in key or str(self.first.pk) in key for key in self.fake.objects))
        self.assertIn("Removed 3 picture(s) and 1 account(s)", out.getvalue())

    def test_dry_run_changes_nothing(self):
        services.soft_delete_user(self.user)
        self.age(users=[self.user], avatars=[self.first, self.second])
        files_before = dict(self.fake.objects)

        out = StringIO()
        call_command("purge_deleted", "--dry-run", stdout=out)

        self.assertTrue(User.all_objects.filter(pk=self.user.pk).exists())
        self.assertEqual(Avatar.all_objects.count(), 2)
        self.assertEqual(self.fake.objects, files_before)
        self.assertIn("Would remove 2 picture(s) and 1 account(s)", out.getvalue())

    def test_the_retention_period_can_be_changed(self):
        services.soft_delete_user(self.user)
        self.age(users=[self.user], avatars=[self.first, self.second], days=10)
        call_command("purge_deleted", stdout=StringIO())  # default 30 days: too early
        self.assertTrue(User.all_objects.filter(pk=self.user.pk).exists())
        call_command("purge_deleted", "--days", "7", stdout=StringIO())
        self.assertFalse(User.all_objects.filter(pk=self.user.pk).exists())


class AccountAdminTests(SoftDeleteTestCase):
    def setUp(self):
        super().setUp()
        self.admin_user = User.objects.create_superuser("admin@example.com", PASSWORD)
        self.client.force_login(self.admin_user)

    def action(self, name, *users):
        data = {"action": name, "_selected_action": [str(u.pk) for u in users]}
        return self.client.post("/admin/accounts/user/", data)

    def test_the_list_shows_deleted_accounts_and_can_filter_them(self):
        services.soft_delete_user(self.user)
        everything = self.client.get("/admin/accounts/user/")
        self.assertContains(everything, f"deleted-{self.user.pk}@deleted.invalid")
        only_live = self.client.get("/admin/accounts/user/?is_deleted__exact=0")
        self.assertNotContains(only_live, f"deleted-{self.user.pk}@deleted.invalid")

    def test_deleting_again_from_the_admin_removes_the_account_for_good(self):
        services.soft_delete_user(self.user)
        response = self.client.post(f"/admin/accounts/user/{self.user.pk}/delete/", {"post": "yes"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.all_objects.filter(pk=self.user.pk).exists())
        self.assertEqual(self.fake.objects, {})

    def test_restore_action(self):
        services.soft_delete_user(self.user)
        response = self.action("restore_accounts", self.deleted_user())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(User.objects.get(pk=self.user.pk).email, self.old_email)

    def test_restore_action_reports_a_conflict_and_leaves_the_account_deleted(self):
        services.soft_delete_user(self.user)
        self.make_user(self.old_email)
        response = self.action("restore_accounts", self.deleted_user())
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.deleted_user().is_deleted)

    def test_delete_permanently_action(self):
        response = self.action("delete_permanently", self.user)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.all_objects.filter(pk=self.user.pk).exists())
        self.assertEqual(self.fake.objects, {})