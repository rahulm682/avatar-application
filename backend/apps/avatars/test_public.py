"""Tests for the public endpoint GET /avatar/{email_hash} (Step 5). S3 is replaced by an in-memory fake."""
import hashlib
import io
import uuid
from unittest.mock import patch

from django.conf import settings
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from PIL import Image

from apps.accounts.emailhash import hash_email
from apps.accounts.models import User

from . import fallbacks, imaging, storage
from .models import Avatar
from .tests import S3_SETTINGS, FakeStorage, make_image

PASSWORD = "correct-horse-battery-staple-9"
EMAIL = "user@example.com"


class PublicFake(FakeStorage):
    def __init__(self):
        super().__init__()
        self.reads = []

    def try_read_object(self, key, max_bytes):
        self.reads.append(key)
        return self.objects.get(key)


def open_image(response):
    return Image.open(io.BytesIO(response.content))


# The container's .env enables the origin lock; switch it off here (one test turns it on again).
@override_settings(ORIGIN_VERIFY_SECRET="", **S3_SETTINGS)
class PublicAvatarTestCase(TestCase):
    def setUp(self):
        self.fake = PublicFake()
        patcher = patch.multiple(
            storage,
            read_object=self.fake.read_object,
            try_read_object=self.fake.try_read_object,
            put_object=self.fake.put_object,
            delete_objects=self.fake.delete_objects,
            delete_prefix=self.fake.delete_prefix,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        self.client = Client()
        self.user = User.objects.create_user(EMAIL, PASSWORD, email_verified_at=timezone.now())

    def url(self, email=EMAIL):
        return f"/avatar/{hash_email(email)}"

    def make_avatar(self, color=(255, 0, 0), size=(400, 100), user=None, make_current=True):
        """Creates an avatar the way the upload flow would (original file in 'S3' plus the database row)."""
        user = user or self.user
        processed = imaging.process_upload(make_image(size=size, color=color), 4096)
        avatar_id = uuid.uuid4()
        key = storage.original_key(user.pk, avatar_id)
        self.fake.objects[key] = processed.data
        avatar = Avatar.objects.create(
            id=avatar_id,
            user=user,
            storage_key=key,
            content_hash=hashlib.sha256(processed.data).hexdigest(),
            size_bytes=len(processed.data),
            width=processed.width,
            height=processed.height,
        )
        if make_current:
            user.current_avatar = avatar
            user.save(update_fields=["current_avatar", "updated_at"])
        return avatar


class RoutingAndParameterTests(PublicAvatarTestCase):
    def test_only_lowercase_64_character_hashes_are_routed(self):
        digest = hash_email(EMAIL)
        for path in ("/avatar/abc", f"/avatar/{digest.upper()}", "/avatar/" + "g" * 64, f"/avatar/{digest}/"):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_size_is_rounded_up_to_a_supported_size(self):
        cases = {"1": 40, "40": 40, "41": 80, "100": 160, "320": 320, "321": 640, "640": 640, "9999": 640}
        for raw, expected in cases.items():
            response = self.client.get(self.url("nobody@example.com"), {"s": raw})
            self.assertEqual(open_image(response).size, (expected, expected), raw)

    def test_invalid_sizes_use_the_default_size(self):
        for raw in ("abc", "-5", "0", "", "1.5", "9" * 5000):
            response = self.client.get(self.url("nobody@example.com"), {"s": raw})
            self.assertEqual(open_image(response).size, (80, 80), raw)

    def test_responses_do_not_vary_on_origin(self):
        # "Vary: Origin" would split the CDN cache by the Origin request header.
        response = self.client.get(self.url(), HTTP_ORIGIN="https://some-other-site.example")
        self.assertNotIn("Origin", response.get("Vary", ""))
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")

    def test_only_get_and_head_are_allowed(self):
        self.assertEqual(self.client.post(self.url()).status_code, 405)
        self.assertEqual(self.client.head(self.url()).status_code, 200)

    @override_settings(ORIGIN_VERIFY_SECRET="s3cret")
    def test_requests_that_skip_the_cdn_are_refused(self):
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.assertEqual(self.client.get(self.url(), HTTP_X_ORIGIN_VERIFY="wrong").status_code, 403)
        self.assertEqual(self.client.get(self.url(), HTTP_X_ORIGIN_VERIFY="s3cret").status_code, 200)


class FallbackTests(PublicAvatarTestCase):
    def test_unknown_hash_gets_the_default_image_with_cache_headers(self):
        response = self.client.get(self.url("nobody@example.com"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/webp")
        self.assertEqual(response.content, fallbacks.default_image(80))
        self.assertEqual(response["Cache-Control"], settings.AVATAR_CACHE_CONTROL)
        self.assertTrue(response["ETag"])
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        self.assertEqual(response["Cross-Origin-Resource-Policy"], "cross-origin")

    def test_d_404_returns_a_briefly_cached_404(self):
        response = self.client.get(self.url("nobody@example.com"), {"d": "404"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["Cache-Control"], "public, max-age=60, s-maxage=60")

    def test_identicon_is_deterministic_and_specific_to_the_hash(self):
        first = self.client.get(self.url("a@example.com"), {"d": "identicon", "s": "160"})
        again = self.client.get(self.url("a@example.com"), {"d": "identicon", "s": "160"})
        other = self.client.get(self.url("b@example.com"), {"d": "identicon", "s": "160"})
        self.assertEqual(first.content, again.content)
        self.assertNotEqual(first.content, other.content)
        self.assertEqual(open_image(first).size, (160, 160))
        self.assertEqual(first["Cache-Control"], settings.AVATAR_CACHE_CONTROL)

    def test_unknown_d_value_means_default(self):
        response = self.client.get(self.url("nobody@example.com"), {"d": "wat"})
        self.assertEqual(response.content, fallbacks.default_image(80))

    def test_a_user_without_a_picture_looks_exactly_like_an_unknown_hash(self):
        # The public endpoint must not reveal whether an email is registered.
        known = self.client.get(self.url(EMAIL), {"d": "identicon"})
        unknown_hash = hash_email("nobody@example.com")
        unknown = self.client.get(f"/avatar/{unknown_hash}", {"d": "identicon"})
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known["Cache-Control"], unknown["Cache-Control"])
        self.assertEqual(known.content, fallbacks.identicon(hash_email(EMAIL), 80))
        for d in ("default", "404"):
            a = self.client.get(self.url(EMAIL), {"d": d})
            b = self.client.get(f"/avatar/{unknown_hash}", {"d": d})
            self.assertEqual((a.status_code, a.content), (b.status_code, b.content))


class ServingAvatarTests(PublicAvatarTestCase):
    def test_serves_the_current_avatar_cropped_to_a_square(self):
        avatar = self.make_avatar(size=(400, 100))
        response = self.client.get(self.url(), {"s": "160"})
        self.assertEqual(response.status_code, 200)
        image = open_image(response)
        self.assertEqual((image.format, image.size), ("WEBP", (160, 160)))
        self.assertNotEqual(response.content, fallbacks.default_image(160))
        self.assertEqual(response["ETag"], f'"{avatar.content_hash[:32]}-160"')
        self.assertEqual(response["Cache-Control"], settings.AVATAR_CACHE_CONTROL)

    def test_d_is_ignored_when_a_picture_exists(self):
        self.make_avatar()
        self.assertEqual(self.client.get(self.url(), {"d": "404"}).status_code, 200)

    def test_resized_copy_is_stored_once_and_reused(self):
        avatar = self.make_avatar()
        with patch.object(imaging, "make_square", wraps=imaging.make_square) as make_square:
            first = self.client.get(self.url(), {"s": "80"})
            second = self.client.get(self.url(), {"s": "80"})
        self.assertEqual(make_square.call_count, 1)
        self.assertEqual(first.content, second.content)
        self.assertIn(f"derived/{avatar.pk}/80.webp", self.fake.objects)

    def test_email_is_matched_after_normalization(self):
        user = User.objects.create_user("  Mixed.Case@Example.com", PASSWORD, email_verified_at=timezone.now())
        self.make_avatar(user=user)
        response = self.client.get(f"/avatar/{hash_email('mixed.case@EXAMPLE.com')}")
        self.assertNotEqual(response.content, fallbacks.default_image(80))

    def test_changing_the_current_avatar_changes_the_answer(self):
        first = self.make_avatar(color=(255, 0, 0), size=(100, 100))
        before = self.client.get(self.url())
        second = self.make_avatar(color=(0, 0, 255), size=(100, 100))
        after = self.client.get(self.url())
        self.assertNotEqual(first.pk, second.pk)
        self.assertNotEqual(before["ETag"], after["ETag"])
        self.assertNotEqual(before.content, after.content)

    def test_matching_etag_gets_304_without_touching_s3(self):
        self.make_avatar()
        first = self.client.get(self.url(), {"s": "160"})
        self.fake.reads.clear()

        again = self.client.get(self.url(), {"s": "160"}, HTTP_IF_NONE_MATCH=first["ETag"])
        self.assertEqual(again.status_code, 304)
        self.assertEqual(again.content, b"")
        self.assertEqual(again["ETag"], first["ETag"])
        self.assertEqual(again["Cache-Control"], settings.AVATAR_CACHE_CONTROL)
        self.assertEqual(self.fake.reads, [])

    def test_fallback_images_support_304_too(self):
        first = self.client.get(self.url("nobody@example.com"))
        again = self.client.get(self.url("nobody@example.com"), HTTP_IF_NONE_MATCH=first["ETag"])
        self.assertEqual(again.status_code, 304)

    def test_inactive_or_unverified_users_are_not_served(self):
        self.make_avatar()
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertEqual(self.client.get(self.url()).content, fallbacks.default_image(80))
        User.objects.filter(pk=self.user.pk).update(is_active=True, email_verified_at=None)
        self.assertEqual(self.client.get(self.url()).content, fallbacks.default_image(80))

    def test_missing_files_fall_back_to_the_default_image(self):
        avatar = self.make_avatar()
        self.fake.objects.clear()  # the database row exists, the files do not
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, fallbacks.default_image(80))
        self.assertNotIn(f"derived/{avatar.pk}/80.webp", self.fake.objects)

    def test_storage_outage_gives_an_uncacheable_503(self):
        self.make_avatar()
        with patch.object(storage, "try_read_object", side_effect=RuntimeError("S3 is down")):
            response = self.client.get(self.url())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Cache-Control"], "no-store")