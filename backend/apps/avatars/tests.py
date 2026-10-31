"""Avatar tests (Step 4). S3 is replaced by an in-memory fake, so these run without Silo.

Signing presigned URLs needs no network, so that part of storage.py runs for real with dummy credentials.
The real-S3 flow is covered by test_s3_integration.py (opt-in).
"""
import base64
import io
import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.models import User

from . import storage
from .models import Avatar

PASSWORD = "correct-horse-battery-staple-9"
UPLOAD_URL = "/api/avatars/upload-url/"
CONFIRM = "/api/avatars/confirm/"
LIST = "/api/avatars/"
CURRENT = "/api/me/current-avatar/"

S3_SETTINGS = dict(
    AWS_ACCESS_KEY_ID="test-key",
    AWS_SECRET_ACCESS_KEY="test-secret",
    AWS_S3_ENDPOINT_URL="http://s3.invalid:9000",
    AWS_S3_PUBLIC_ENDPOINT_URL="http://localhost:9000",
    AWS_STORAGE_BUCKET_NAME="test-bucket",
    AWS_S3_ADDRESSING_STYLE="path",
)


def make_image(fmt="PNG", size=(200, 100), color=(255, 0, 0)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, fmt)
    return buffer.getvalue()


class FakeStorage:
    """Minimal in-memory stand-in for the S3 functions in storage.py."""

    def __init__(self):
        self.objects = {}

    def read_object(self, key, max_bytes):
        if key not in self.objects:
            raise storage.ObjectNotFound(key)
        if len(self.objects[key]) > max_bytes:
            raise storage.ObjectTooLarge(key)
        return self.objects[key]

    def put_object(self, key, data, content_type):
        self.objects[key] = data

    def delete_objects(self, keys):
        for key in keys:
            self.objects.pop(key, None)

    def delete_prefix(self, prefix):
        for key in [k for k in self.objects if k.startswith(prefix)]:
            del self.objects[key]

    def keys(self, prefix=""):
        return sorted(k for k in self.objects if k.startswith(prefix))


@override_settings(**S3_SETTINGS)
class AvatarTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.fake = FakeStorage()
        patcher = patch.multiple(
            storage,
            read_object=self.fake.read_object,
            put_object=self.fake.put_object,
            delete_objects=self.fake.delete_objects,
            delete_prefix=self.fake.delete_prefix,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        invalidate = patch("apps.avatars.services.invalidate_email_hashes")
        self.invalidate = invalidate.start()
        self.addCleanup(invalidate.stop)

        self.user = self.make_user("user@example.com")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def make_user(self, email):
        return User.objects.create_user(email, PASSWORD, email_verified_at=timezone.now())

    def start_upload(self, content_type="image/png", client=None):
        response = (client or self.client).post(UPLOAD_URL, {"content_type": content_type}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def upload(self, data=None, client=None):
        """Simulates the whole flow: presign, the browser's upload to S3, then confirm."""
        body = self.start_upload(client=client)
        self.fake.objects[body["fields"]["key"]] = data if data is not None else make_image()
        return (client or self.client).post(CONFIRM, {"upload_token": body["upload_token"]}, format="json")

    def current_id(self):
        return User.objects.get(pk=self.user.pk).current_avatar_id


class UploadUrlTests(AvatarTestCase):
    def test_requires_login(self):
        response = APIClient().post(UPLOAD_URL, {"content_type": "image/png"}, format="json")
        self.assertEqual(response.status_code, 401)

    def test_returns_a_restricted_presigned_post(self):
        body = self.start_upload()
        self.assertTrue(body["url"].startswith("http://localhost:9000/test-bucket"))  # browser-reachable address
        self.assertTrue(body["fields"]["key"].startswith(f"uploads/{self.user.pk}/"))
        self.assertEqual(body["fields"]["Content-Type"], "image/png")
        policy = json.loads(base64.b64decode(body["fields"]["policy"]))
        self.assertIn(["content-length-range", 1, 5 * 1024 * 1024], policy["conditions"])
        self.assertIn({"Content-Type": "image/png"}, policy["conditions"])
        self.assertEqual(body["max_bytes"], 5 * 1024 * 1024)

    def test_rejects_other_content_types(self):
        response = self.client.post(UPLOAD_URL, {"content_type": "image/gif"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_rejects_declared_size_over_the_limit(self):
        response = self.client.post(
            UPLOAD_URL, {"content_type": "image/png", "size": 5 * 1024 * 1024 + 1}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    @override_settings(AVATAR_MAX_PER_USER=1)
    def test_refuses_when_the_limit_is_reached(self):
        self.assertEqual(self.upload().status_code, 201)
        response = self.client.post(UPLOAD_URL, {"content_type": "image/png"}, format="json")
        self.assertEqual(response.status_code, 400)


class ConfirmUploadTests(AvatarTestCase):
    def test_first_upload_is_stored_and_becomes_current(self):
        body = self.start_upload()
        raw_key = body["fields"]["key"]
        self.fake.objects[raw_key] = make_image()

        response = self.client.post(CONFIRM, {"upload_token": body["upload_token"]}, format="json")
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data["is_current"])
        self.assertEqual((data["width"], data["height"]), (200, 100))
        self.assertTrue(data["preview_url"].startswith("http://localhost:9000/test-bucket/derived/"))

        avatar = Avatar.objects.get()
        self.assertEqual(self.current_id(), avatar.pk)
        self.assertIn(f"originals/{self.user.pk}/{avatar.pk}.webp", self.fake.objects)
        self.assertIn(f"derived/{avatar.pk}/160.webp", self.fake.objects)
        self.assertNotIn(raw_key, self.fake.objects)  # the raw upload is removed
        self.invalidate.assert_called_once_with(self.user.email_hash)

    def test_stored_original_is_a_clean_webp(self):
        self.upload(make_image("JPEG"))
        original = self.fake.objects[Avatar.objects.get().storage_key]
        self.assertEqual(Image.open(io.BytesIO(original)).format, "WEBP")

    def test_second_upload_does_not_replace_the_current_avatar(self):
        first = self.upload(make_image(color=(255, 0, 0))).json()
        second = self.upload(make_image(color=(0, 0, 255))).json()
        self.assertTrue(first["is_current"])
        self.assertFalse(second["is_current"])
        self.assertEqual(str(self.current_id()), first["id"])
        self.assertEqual(Avatar.objects.count(), 2)
        self.invalidate.assert_called_once()  # only the first upload changed what the public URL returns

    def test_uploading_the_same_picture_again_returns_the_existing_one(self):
        data = make_image()
        first = self.upload(data)
        second = self.upload(data)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(Avatar.objects.count(), 1)
        self.assertEqual(self.fake.keys("uploads/"), [])

    def test_a_file_that_is_not_an_image_is_rejected_and_removed(self):
        response = self.upload(b"definitely not an image")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Avatar.objects.count(), 0)
        self.assertEqual(self.fake.objects, {})

    def test_gif_content_is_rejected_even_if_declared_as_png(self):
        buffer = io.BytesIO()
        Image.new("P", (10, 10)).save(buffer, "GIF")
        self.assertEqual(self.upload(buffer.getvalue()).status_code, 400)

    def test_too_many_pixels_are_rejected(self):
        response = self.upload(make_image(size=(4097, 1)))
        self.assertEqual(response.status_code, 400)
        self.assertIn("too large", response.json()["detail"])

    def test_exif_orientation_is_applied_and_metadata_removed(self):
        image = Image.new("RGB", (40, 20), (0, 128, 0))
        exif = image.getexif()
        exif[0x0112] = 6  # rotate 90 degrees
        exif[0x010F] = "SecretCameraMaker"
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", exif=exif)

        data = self.upload(buffer.getvalue()).json()
        self.assertEqual((data["width"], data["height"]), (20, 40))
        stored = Image.open(io.BytesIO(self.fake.objects[Avatar.objects.get().storage_key]))
        self.assertEqual(len(stored.getexif()), 0)

    @override_settings(AVATAR_MAX_PER_USER=1)
    def test_limit_is_enforced_at_confirm_time_too(self):
        body = self.start_upload()  # presigned while the user still had room
        self.assertEqual(self.upload(make_image(color=(1, 2, 3))).status_code, 201)
        self.fake.objects[body["fields"]["key"]] = make_image(color=(9, 9, 9))
        response = self.client.post(CONFIRM, {"upload_token": body["upload_token"]}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Avatar.objects.count(), 1)
        self.assertEqual(self.fake.keys("uploads/"), [])

    def test_confirm_without_uploading_fails(self):
        body = self.start_upload()
        response = self.client.post(CONFIRM, {"upload_token": body["upload_token"]}, format="json")
        self.assertEqual(response.status_code, 400)

    @override_settings(AVATAR_MAX_UPLOAD_BYTES=1000)
    def test_file_over_the_size_limit_is_rejected_and_removed(self):
        response = self.upload(make_image(size=(300, 300), color=(10, 200, 30)) + b"0" * 2000)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.fake.objects, {})

    def test_upload_token_of_another_user_is_rejected(self):
        body = self.start_upload()
        self.fake.objects[body["fields"]["key"]] = make_image()
        other_client = APIClient()
        other_client.force_authenticate(self.make_user("other@example.com"))
        response = other_client.post(CONFIRM, {"upload_token": body["upload_token"]}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Avatar.objects.count(), 0)

    def test_tampered_token_is_rejected(self):
        body = self.start_upload()
        response = self.client.post(CONFIRM, {"upload_token": body["upload_token"] + "x"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_upload_url_requests_are_rate_limited(self):
        statuses = [
            self.client.post(UPLOAD_URL, {"content_type": "image/png"}, format="json").status_code
            for _ in range(21)
        ]
        self.assertEqual(statuses[:20], [200] * 20)
        self.assertEqual(statuses[20], 429)


class ListTests(AvatarTestCase):
    def test_lists_own_pictures_with_current_flag(self):
        first = self.upload(make_image(color=(255, 0, 0))).json()
        second = self.upload(make_image(color=(0, 255, 0))).json()
        other_client = APIClient()
        other_user = self.make_user("other@example.com")
        other_client.force_authenticate(other_user)
        self.upload(make_image(color=(0, 0, 255)), client=other_client)

        data = self.client.get(LIST).json()
        self.assertEqual(data["max_avatars"], 10)
        self.assertEqual(data["current_avatar_id"], first["id"])
        self.assertEqual([item["id"] for item in data["results"]], [second["id"], first["id"]])  # newest first
        flags = {item["id"]: item["is_current"] for item in data["results"]}
        self.assertEqual(flags, {first["id"]: True, second["id"]: False})

    def test_requires_login(self):
        self.assertEqual(APIClient().get(LIST).status_code, 401)


class DeleteTests(AvatarTestCase):
    def test_delete_a_non_current_picture(self):
        self.upload(make_image(color=(255, 0, 0)))
        second = self.upload(make_image(color=(0, 255, 0))).json()
        self.invalidate.reset_mock()

        response = self.client.delete(f"/api/avatars/{second['id']}/")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(Avatar.objects.count(), 1)  # hidden from every normal lookup
        deleted = Avatar.all_objects.get(pk=second["id"])
        self.assertTrue(deleted.is_deleted)
        self.assertIsNotNone(deleted.deleted_at)
        self.assertTrue(any(second["id"] in key for key in self.fake.objects))  # soft delete keeps the files
        self.invalidate.assert_not_called()

    def test_deleting_the_current_picture_resets_to_default_and_invalidates_the_cdn(self):
        first = self.upload().json()
        self.invalidate.reset_mock()

        response = self.client.delete(f"/api/avatars/{first['id']}/")
        self.assertEqual(response.status_code, 204)
        self.assertIsNone(self.current_id())
        self.assertTrue(Avatar.all_objects.get(pk=first["id"]).is_deleted)
        self.assertTrue(any(first["id"] in key for key in self.fake.objects))  # soft delete keeps the files
        self.invalidate.assert_called_once_with(self.user.email_hash)

    def test_cannot_delete_someone_elses_picture(self):
        other = self.make_user("other@example.com")
        other_client = APIClient()
        other_client.force_authenticate(other)
        theirs = self.upload(client=other_client).json()

        response = self.client.delete(f"/api/avatars/{theirs['id']}/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Avatar.objects.count(), 1)

    def test_unknown_id_is_not_found(self):
        response = self.client.delete("/api/avatars/00000000-0000-0000-0000-000000000000/")
        self.assertEqual(response.status_code, 404)


class CurrentAvatarTests(AvatarTestCase):
    def test_choose_another_picture(self):
        self.upload(make_image(color=(255, 0, 0)))
        second = self.upload(make_image(color=(0, 255, 0))).json()
        self.invalidate.reset_mock()

        response = self.client.put(CURRENT, {"avatar_id": second["id"]}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"current_avatar_id": second["id"]})
        self.assertEqual(str(self.current_id()), second["id"])
        self.invalidate.assert_called_once_with(self.user.email_hash)

    def test_choosing_the_same_picture_changes_nothing(self):
        first = self.upload().json()
        self.invalidate.reset_mock()
        self.assertEqual(self.client.put(CURRENT, {"avatar_id": first["id"]}, format="json").status_code, 200)
        self.invalidate.assert_not_called()

    def test_null_goes_back_to_the_default_picture(self):
        self.upload()
        self.invalidate.reset_mock()
        response = self.client.put(CURRENT, {"avatar_id": None}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.current_id())
        self.invalidate.assert_called_once_with(self.user.email_hash)

    def test_cannot_choose_someone_elses_picture(self):
        other_client = APIClient()
        other_client.force_authenticate(self.make_user("other@example.com"))
        theirs = self.upload(client=other_client).json()
        response = self.client.put(CURRENT, {"avatar_id": theirs["id"]}, format="json")
        self.assertEqual(response.status_code, 404)
        self.assertIsNone(self.current_id())

    def test_invalid_id_is_rejected(self):
        self.assertEqual(self.client.put(CURRENT, {"avatar_id": "nope"}, format="json").status_code, 400)


class AccountDeletionTests(AvatarTestCase):
    def test_deleting_the_account_hides_everything_but_keeps_the_files(self):
        self.upload(make_image(color=(255, 0, 0)))
        self.upload(make_image(color=(0, 255, 0)))
        files_before = dict(self.fake.objects)

        response = self.client.delete("/api/me/", {"password": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())  # invisible to normal lookups
        self.assertTrue(User.all_objects.get(pk=self.user.pk).is_deleted)
        self.assertEqual(Avatar.objects.count(), 0)
        self.assertEqual(Avatar.all_objects.count(), 2)
        self.assertEqual(self.fake.objects, files_before)  # removed only by the purge job (see test_softdelete.py)