"""Admin actions that change what the public avatar endpoint returns must clean up S3 and the CDN (Step 6)."""
import hashlib
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib import admin
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.avatars import imaging, storage
from apps.avatars.models import Avatar
from apps.avatars.tests import S3_SETTINGS, FakeStorage, make_image

from .admin import UserAdmin
from .emailhash import hash_email
from .models import User

PASSWORD = "correct-horse-battery-staple-9"


@override_settings(ORIGIN_VERIFY_SECRET="", **S3_SETTINGS)
class AdminCleanupTests(TestCase):
    def setUp(self):
        self.fake = FakeStorage()
        patcher = patch.multiple(
            storage,
            put_object=self.fake.put_object,
            delete_objects=self.fake.delete_objects,
            delete_prefix=self.fake.delete_prefix,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        # Each module imports the invalidation function under its own name, so each one is patched where it is used.
        targets = {
            "accounts_invalidate": "apps.accounts.admin.invalidate_email_hashes",  # edits made in the user admin form
            "accounts_service_invalidate": "apps.accounts.services.invalidate_email_hashes",  # account soft delete
            "avatars_invalidate": "apps.avatars.services.invalidate_email_hashes",  # picture deletion
        }
        for attribute, target in targets.items():
            mocked = patch(target)
            setattr(self, attribute, mocked.start())
            self.addCleanup(mocked.stop)

        self.admin_user = User.objects.create_superuser("admin@example.com", PASSWORD)
        self.client.force_login(self.admin_user)
        self.user = User.objects.create_user("user@example.com", PASSWORD, email_verified_at=timezone.now())
        self.avatar = self.make_avatar(self.user)

    def make_avatar(self, user):
        processed = imaging.process_upload(make_image(), 4096)
        avatar_id = uuid.uuid4()
        key = storage.original_key(user.pk, avatar_id)
        self.fake.objects[key] = processed.data
        self.fake.objects[storage.derived_key(avatar_id, 160)] = b"preview"
        avatar = Avatar.objects.create(
            id=avatar_id, user=user, storage_key=key, content_hash=hashlib.sha256(processed.data).hexdigest(),
            size_bytes=len(processed.data), width=processed.width, height=processed.height,
        )
        user.current_avatar = avatar
        user.save(update_fields=["current_avatar", "updated_at"])
        return avatar

    def test_deleting_a_user_is_a_soft_delete_and_invalidates_the_cdn(self):
        old_hash = self.user.email_hash
        files_before = dict(self.fake.objects)
        response = self.client.post(f"/admin/accounts/user/{self.user.pk}/delete/", {"post": "yes"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertTrue(User.all_objects.get(pk=self.user.pk).is_deleted)
        self.assertEqual(self.fake.objects, files_before)  # kept until the retention period is over
        self.accounts_service_invalidate.assert_called_with(old_hash)

    def test_bulk_deleting_users_does_the_same(self):
        old_hash = self.user.email_hash
        files_before = dict(self.fake.objects)
        data = {"action": "delete_selected", "_selected_action": [str(self.user.pk)], "post": "yes"}
        response = self.client.post("/admin/accounts/user/", data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.all_objects.get(pk=self.user.pk).is_deleted)
        self.assertEqual(self.fake.objects, files_before)
        self.accounts_service_invalidate.assert_called_with(old_hash)

    def test_deleting_a_picture_is_a_soft_delete_and_invalidates_the_cdn(self):
        files_before = dict(self.fake.objects)
        response = self.client.post(f"/admin/avatars/avatar/{self.avatar.pk}/delete/", {"post": "yes"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Avatar.objects.count(), 0)
        self.assertTrue(Avatar.all_objects.get(pk=self.avatar.pk).is_deleted)
        self.assertEqual(self.fake.objects, files_before)
        self.avatars_invalidate.assert_called_with(self.user.email_hash)
        self.assertIsNone(User.objects.get(pk=self.user.pk).current_avatar_id)

    def test_deactivating_a_user_invalidates_the_cdn(self):
        user_admin = UserAdmin(User, admin.site)
        self.user.is_active = False
        user_admin.save_model(None, self.user, SimpleNamespace(changed_data=["is_active"], initial={}), True)
        self.accounts_invalidate.assert_called_once_with(self.user.email_hash)

    def test_changing_an_email_invalidates_old_and_new_hash(self):
        user_admin = UserAdmin(User, admin.site)
        old_hash = self.user.email_hash
        self.user.email = "renamed@example.com"
        form = SimpleNamespace(changed_data=["email"], initial={"email": "user@example.com"})
        user_admin.save_model(None, self.user, form, True)
        self.accounts_invalidate.assert_called_once_with(old_hash, hash_email("renamed@example.com"))

    def test_editing_unrelated_fields_does_not_invalidate(self):
        user_admin = UserAdmin(User, admin.site)
        form = SimpleNamespace(changed_data=["display_name"], initial={})
        user_admin.save_model(None, self.user, form, True)
        self.accounts_invalidate.assert_not_called()