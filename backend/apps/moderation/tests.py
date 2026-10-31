"""Tests for reports and the moderation actions (Step 8)."""
import hashlib
import uuid
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

from apps.accounts.authtokens import issue_tokens
from apps.accounts.emailhash import hash_email
from apps.accounts.models import User
from apps.avatars import imaging, storage
from apps.avatars.models import Avatar
from apps.avatars.tests import S3_SETTINGS, FakeStorage, make_image

from .models import Report

PASSWORD = "correct-horse-battery-staple-9"
REPORTS = "/api/reports/"
CHANGELIST = "/admin/moderation/report/"


@override_settings(ORIGIN_VERIFY_SECRET="", **S3_SETTINGS)
class ModerationTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.fake = FakeStorage()
        patcher = patch.multiple(
            storage,
            put_object=self.fake.put_object,
            delete_objects=self.fake.delete_objects,
            delete_prefix=self.fake.delete_prefix,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        self.avatar_invalidate = self.patch_name("apps.avatars.services.invalidate_email_hashes")
        self.moderation_invalidate = self.patch_name("apps.moderation.admin.invalidate_email_hashes")

        self.user = User.objects.create_user("poster@example.com", PASSWORD, email_verified_at=timezone.now())
        self.avatar = self.make_avatar(self.user)
        self.api = APIClient()

    def patch_name(self, target):
        patcher = patch(target)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def make_avatar(self, user, color=(255, 0, 0)):
        processed = imaging.process_upload(make_image(color=color), 4096)
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

    def report(self, email_hash=None, reason="This picture is offensive"):
        return self.api.post(
            REPORTS, {"email_hash": email_hash or self.user.email_hash, "reason": reason}, format="json"
        )


class ReportEndpointTests(ModerationTestCase):
    def test_reporting_a_picture_creates_a_report(self):
        response = self.report()
        self.assertEqual(response.status_code, 202)
        report = Report.objects.get()
        self.assertEqual(report.avatar_uuid, self.avatar.pk)
        self.assertEqual(report.user_uuid, self.user.pk)
        self.assertEqual(report.email_hash, self.user.email_hash)
        self.assertEqual(report.reason, "This picture is offensive")
        self.assertEqual(report.status, Report.Status.OPEN)

    def test_unknown_hash_gets_the_same_answer_but_stores_nothing(self):
        known = self.report()
        unknown = self.report(email_hash=hash_email("nobody@example.com"))
        self.assertEqual((known.status_code, known.json()), (unknown.status_code, unknown.json()))
        self.assertEqual(Report.objects.count(), 1)

    def test_user_without_a_current_picture_cannot_be_reported(self):
        User.objects.filter(pk=self.user.pk).update(current_avatar=None)
        self.assertEqual(self.report().status_code, 202)
        self.assertEqual(Report.objects.count(), 0)

    def test_the_picture_that_was_current_at_report_time_is_recorded(self):
        self.report()
        second = self.make_avatar(self.user, color=(0, 0, 255))
        self.report()
        self.assertEqual(sorted(str(r.avatar_uuid) for r in Report.objects.all()), sorted([str(self.avatar.pk), str(second.pk)]))

    def test_input_is_validated(self):
        self.assertEqual(self.report(email_hash="not-a-hash").status_code, 400)
        self.assertEqual(self.report(email_hash=self.user.email_hash.upper()).status_code, 400)
        self.assertEqual(self.report(reason="").status_code, 400)
        self.assertEqual(self.report(reason="x" * 501).status_code, 400)
        self.assertEqual(Report.objects.count(), 0)

    def test_requires_no_login(self):
        self.assertEqual(self.report().status_code, 202)  # self.api is anonymous

    def test_reports_are_rate_limited_per_ip(self):
        statuses = [self.report().status_code for _ in range(11)]
        self.assertEqual(statuses[:10], [202] * 10)
        self.assertEqual(statuses[10], 429)


class ModerationActionTests(ModerationTestCase):
    def setUp(self):
        super().setUp()
        self.admin_user = User.objects.create_superuser("admin@example.com", PASSWORD)
        self.client.force_login(self.admin_user)
        self.report()
        self.report(reason="Another person also objects")
        self.reports = list(Report.objects.all())

    def run_action(self, action, reports=None):
        pks = [str(r.pk) for r in (reports or self.reports)]
        return self.client.post(CHANGELIST, {"action": action, "_selected_action": pks})

    def test_remove_pictures_deletes_the_picture_and_closes_every_report_about_it(self):
        response = self.run_action("remove_pictures", self.reports[:1])  # select only one of the two reports
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Avatar.objects.count(), 0)
        self.assertTrue(Avatar.all_objects.get(pk=self.avatar.pk).is_deleted)  # soft delete: a moderator can undo it
        self.assertTrue(self.fake.objects)  # files stay until the retention period is over
        self.avatar_invalidate.assert_called_with(self.user.email_hash)
        self.assertEqual(set(Report.objects.values_list("status", flat=True)), {Report.Status.ACTIONED})
        self.assertTrue(all(r.handled_at for r in Report.objects.all()))
        self.assertIsNone(User.objects.get(pk=self.user.pk).current_avatar_id)

    def test_removing_an_already_deleted_picture_just_closes_the_report(self):
        Avatar.objects.filter(pk=self.avatar.pk).delete()
        self.assertEqual(self.run_action("remove_pictures").status_code, 302)
        self.assertEqual(set(Report.objects.values_list("status", flat=True)), {Report.Status.ACTIONED})

    def test_deactivate_users_blocks_the_account_and_revokes_sessions(self):
        _, refresh = issue_tokens(self.user)
        self.assertEqual(self.run_action("deactivate_users").status_code, 302)
        self.assertFalse(User.objects.get(pk=self.user.pk).is_active)
        self.assertEqual(BlacklistedToken.objects.count(), 1)
        self.moderation_invalidate.assert_called_with(self.user.email_hash)
        self.assertEqual(set(Report.objects.values_list("status", flat=True)), {Report.Status.ACTIONED})
        self.assertTrue(refresh)

    def test_staff_accounts_are_never_deactivated_from_a_report(self):
        User.objects.filter(pk=self.user.pk).update(is_staff=True)
        self.run_action("deactivate_users")
        self.assertTrue(User.objects.get(pk=self.user.pk).is_active)

    def test_dismiss_keeps_the_picture(self):
        self.assertEqual(self.run_action("dismiss_reports").status_code, 302)
        self.assertEqual(Avatar.objects.count(), 1)
        self.assertEqual(set(Report.objects.values_list("status", flat=True)), {Report.Status.DISMISSED})
        self.avatar_invalidate.assert_not_called()

    def test_handled_reports_are_not_processed_again(self):
        self.run_action("dismiss_reports")
        self.run_action("remove_pictures")
        self.assertEqual(Avatar.objects.count(), 1)  # the dismissed reports no longer trigger removal

    def test_admin_list_page_renders(self):
        response = self.client.get(CHANGELIST)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Another person also objects")
        self.assertContains(response, self.user.email_hash[:12])

    def test_report_survives_the_deletion_of_the_user(self):
        User.objects.filter(pk=self.user.pk).delete()
        self.assertEqual(Report.objects.count(), 2)  # the audit trail stays


class HashTests(TestCase):
    def test_report_endpoint_uses_the_same_hash_rule_as_the_public_url(self):
        self.assertEqual(hash_email("Poster@Example.com "), hash_email("poster@example.com"))