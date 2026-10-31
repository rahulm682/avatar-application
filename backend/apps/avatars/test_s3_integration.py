"""Opt-in test against the REAL S3 server (Silo). Run it with:

    docker compose exec -e RUN_S3_TESTS=1 backend python manage.py test apps.avatars.test_s3_integration

It uses the dev bucket and deletes everything it creates.
"""
import io
import os
import unittest

import requests
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.models import User

from . import services, storage
from .models import Avatar


def png_bytes(size=(300, 200), color=(10, 120, 200)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def internal(url):
    """Rewrites a browser-facing URL to the address reachable from inside the container."""
    return url.replace(settings.AWS_S3_PUBLIC_ENDPOINT_URL, settings.AWS_S3_ENDPOINT_URL, 1)


@unittest.skipUnless(os.environ.get("RUN_S3_TESTS") == "1", "set RUN_S3_TESTS=1 to run against the real S3 server")
class RealS3FlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("s3test@example.com", "correct-horse-battery-staple-9",
                                             email_verified_at=timezone.now())
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.addCleanup(lambda: services.delete_all_files_for_user(self.user))

    def presign(self):
        response = self.client.post("/api/avatars/upload-url/", {"content_type": "image/png"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def browser_upload(self, body, data):
        """Does what the browser will do: POST the fields, then the file as the last field."""
        return requests.post(internal(body["url"]), data=body["fields"], files={"file": ("a.png", data)}, timeout=30)

    def test_full_flow_against_real_s3(self):
        body = self.presign()
        upload = self.browser_upload(body, png_bytes())
        self.assertIn(upload.status_code, (200, 201, 204), upload.text)

        confirm = self.client.post("/api/avatars/confirm/", {"upload_token": body["upload_token"]}, format="json")
        self.assertEqual(confirm.status_code, 201, confirm.content)
        avatar = Avatar.objects.get()

        # original and preview exist; the raw upload is gone
        self.assertTrue(storage.read_object(avatar.storage_key, 10_000_000))
        preview_key = storage.derived_key(avatar.pk, services.PREVIEW_SIZE)
        self.assertTrue(storage.read_object(preview_key, 10_000_000))
        with self.assertRaises(storage.ObjectNotFound):
            storage.read_object(body["fields"]["key"], 10_000_000)

        # the presigned preview URL from the list works for a browser (the signed Host header is the public one)
        listing = self.client.get("/api/avatars/").json()
        preview_url = listing["results"][0]["preview_url"]
        host = settings.AWS_S3_PUBLIC_ENDPOINT_URL.split("//", 1)[1]
        response = requests.get(internal(preview_url), headers={"Host": host}, timeout=30)
        self.assertEqual(response.status_code, 200, response.text[:200])
        image = Image.open(io.BytesIO(response.content))
        self.assertEqual((image.format, image.size), ("WEBP", (160, 160)))

        # deleting is a soft delete: the picture is hidden but its files stay in S3
        self.assertEqual(self.client.delete(f"/api/avatars/{avatar.pk}/").status_code, 204)
        self.assertEqual(Avatar.objects.count(), 0)
        self.assertTrue(storage.read_object(avatar.storage_key, 10_000_000))

        # the purge job (or "delete permanently" in the admin) removes the files for good
        services.purge_avatar(Avatar.all_objects.get(pk=avatar.pk))
        with self.assertRaises(storage.ObjectNotFound):
            storage.read_object(avatar.storage_key, 10_000_000)
        with self.assertRaises(storage.ObjectNotFound):
            storage.read_object(preview_key, 10_000_000)

    def test_s3_rejects_files_over_the_policy_limit_and_wrong_content_type(self):
        body = self.presign()
        too_big = b"x" * (settings.AVATAR_MAX_UPLOAD_BYTES + 1)
        self.assertGreaterEqual(self.browser_upload(body, too_big).status_code, 400)

        body = self.presign()
        fields = {**body["fields"], "Content-Type": "text/plain"}
        response = requests.post(internal(body["url"]), data=fields, files={"file": ("a.txt", b"hi")}, timeout=30)
        self.assertGreaterEqual(response.status_code, 400)