"""Soft delete, restore and purge for pictures (Step 9)."""
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import User
from . import public_views, services
from .models import Avatar
from .tests import AvatarTestCase, make_image

PASSWORD = "correct-horse-battery-staple-9"


class PictureSoftDeleteTests(AvatarTestCase):
    def test_deleting_hides_the_picture_but_keeps_row_and_files(self):
        picture = self.upload().json()
        files_before = dict(self.fake.objects)
        self.assertEqual(self.client.delete(f"/api/avatars/{picture['id']}/").status_code, 204)

        self.assertEqual(self.client.get("/api/avatars/").json()["results"], [])
        row = Avatar.all_objects.get(pk=picture["id"])
        self.assertTrue(row.is_deleted)
        self.assertIsNotNone(row.deleted_at)
        self.assertEqual(self.fake.objects, files_before)

    def test_deleting_twice_gives_not_found(self):
        picture = self.upload().json()
        self.client.delete(f"/api/avatars/{picture['id']}/")
        self.assertEqual(self.client.delete(f"/api/avatars/{picture['id']}/").status_code, 404)

    def test_the_same_picture_can_be_uploaded_again_after_deleting_it(self):
        data = make_image(color=(12, 34, 56))
        first = self.upload(data).json()
        self.client.delete(f"/api/avatars/{first['id']}/")

        again = self.upload(data)
        self.assertEqual(again.status_code, 201)  # a new picture, not "already exists"
        self.assertNotEqual(again.json()["id"], first["id"])
        self.assertEqual(Avatar.all_objects.count(), 2)  # the deleted one is still waiting for the purge

    @override_settings(AVATAR_MAX_PER_USER=1)
    def test_deleted_pictures_do_not_count_towards_the_limit(self):
        first = self.upload(make_image(color=(1, 1, 1))).json()
        self.client.delete(f"/api/avatars/{first['id']}/")
        self.assertEqual(self.upload(make_image(color=(2, 2, 2))).status_code, 201)

    def test_a_deleted_picture_cannot_be_chosen_as_the_current_one(self):
        self.upload(make_image(color=(1, 1, 1)))
        second = self.upload(make_image(color=(2, 2, 2))).json()
        self.client.delete(f"/api/avatars/{second['id']}/")
        response = self.client.put("/api/me/current-avatar/", {"avatar_id": second["id"]}, format="json")
        self.assertEqual(response.status_code, 404)

    def test_the_public_endpoint_never_serves_a_deleted_picture(self):
        picture = self.upload().json()
        Avatar.all_objects.filter(pk=picture["id"]).update(is_deleted=True)  # even if the current pointer is stale
        self.assertIsNone(public_views.find_current_avatar(self.user.email_hash))


class RestoreAndPurgeTests(AvatarTestCase):
    def setUp(self):
        super().setUp()
        self.first = Avatar.objects.get(pk=self.upload(make_image(color=(255, 0, 0))).json()["id"])
        self.second = Avatar.objects.get(pk=self.upload(make_image(color=(0, 255, 0))).json()["id"])

    def soft_delete(self, avatar):
        services.delete_avatar(Avatar.objects.get(pk=avatar.pk))
        return Avatar.all_objects.get(pk=avatar.pk)

    def test_restore_brings_a_picture_back_without_making_it_current(self):
        deleted = self.soft_delete(self.second)
        services.restore_avatar(deleted)
        restored = Avatar.objects.get(pk=self.second.pk)
        self.assertFalse(restored.is_deleted)
        self.assertIsNone(restored.deleted_at)
        self.assertEqual(self.current_id(), self.first.pk)

    def test_restore_is_refused_if_the_owner_already_has_the_same_picture(self):
        deleted = self.soft_delete(self.second)
        # the user uploads the identical picture again, so a live copy exists
        again = self.upload(make_image(color=(0, 255, 0)))  # the same picture as the deleted one
        self.assertEqual(again.status_code, 201)
        with self.assertRaises(services.AvatarError):
            services.restore_avatar(Avatar.all_objects.get(pk=deleted.pk))

    @override_settings(AVATAR_MAX_PER_USER=2)
    def test_restore_is_refused_if_the_limit_is_reached(self):
        deleted = self.soft_delete(self.second)
        self.assertEqual(self.upload(make_image(color=(9, 9, 9))).status_code, 201)  # back to 2 live pictures
        with self.assertRaises(services.AvatarError):
            services.restore_avatar(deleted)

    def test_restore_is_refused_while_the_account_is_deleted(self):
        deleted = self.soft_delete(self.second)
        User.all_objects.filter(pk=self.user.pk).update(is_deleted=True)
        with self.assertRaises(services.AvatarError):
            services.restore_avatar(Avatar.all_objects.get(pk=deleted.pk))

    def test_purging_removes_the_row_and_every_file(self):
        deleted = self.soft_delete(self.second)
        services.purge_avatar(deleted)
        self.assertFalse(Avatar.all_objects.filter(pk=self.second.pk).exists())
        self.assertFalse(any(str(self.second.pk) in key for key in self.fake.objects))
        self.assertTrue(any(str(self.first.pk) in key for key in self.fake.objects))  # the other picture is untouched

    def test_purging_the_current_picture_tells_the_cdn(self):
        self.invalidate.reset_mock()
        services.purge_avatar(Avatar.objects.select_related("user").get(pk=self.first.pk))
        self.invalidate.assert_called_once_with(self.user.email_hash)
        self.assertIsNone(self.current_id())


class AvatarAdminTests(AvatarTestCase):
    def setUp(self):
        super().setUp()
        self.admin_user = User.objects.create_superuser("admin@example.com", PASSWORD, email_verified_at=timezone.now())
        self.admin_client = self.client_class()
        self.admin_client.force_login(self.admin_user)
        self.picture = Avatar.objects.get(pk=self.upload(make_image(color=(5, 5, 5))).json()["id"])

    def action(self, name):
        data = {"action": name, "_selected_action": [str(self.picture.pk)]}
        return self.admin_client.post("/admin/avatars/avatar/", data)

    def test_the_list_includes_deleted_pictures(self):
        services.delete_avatar(self.picture)
        response = self.admin_client.get("/admin/avatars/avatar/")
        self.assertContains(response, str(self.picture.pk)[:8])

    def test_restore_action(self):
        services.delete_avatar(self.picture)
        self.assertEqual(self.action("restore_pictures").status_code, 302)
        self.assertFalse(Avatar.objects.get(pk=self.picture.pk).is_deleted)

    def test_deleting_an_already_deleted_picture_removes_it_for_good(self):
        services.delete_avatar(self.picture)
        response = self.admin_client.post(f"/admin/avatars/avatar/{self.picture.pk}/delete/", {"post": "yes"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Avatar.all_objects.filter(pk=self.picture.pk).exists())
        self.assertEqual(self.fake.objects, {})

    def test_delete_permanently_action_removes_even_a_live_picture(self):
        self.assertEqual(self.action("delete_permanently").status_code, 302)
        self.assertFalse(Avatar.all_objects.filter(pk=self.picture.pk).exists())
        self.assertEqual(self.fake.objects, {})