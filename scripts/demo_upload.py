#!/usr/bin/env python3
"""End-to-end demo of the avatar upload flow against the running stack (real API, real Silo).

Usage (from the project root):
    docker compose run --rm silo-init python /scripts/demo_upload.py EMAIL PASSWORD [IMAGE_FILE]

Without IMAGE_FILE it generates a random test picture, so every run uploads a new one.
It does exactly what the React app will do: log in, ask for a presigned upload, POST the file
straight to S3, confirm it with the API, and list the pictures.
"""
import os
import random
import sys
from io import BytesIO

import requests
from PIL import Image, ImageDraw

API = os.environ.get("API_BASE_URL", "http://backend:8000")
S3_INTERNAL = os.environ["AWS_S3_ENDPOINT_URL"]
S3_PUBLIC = os.environ.get("AWS_S3_PUBLIC_ENDPOINT_URL") or S3_INTERNAL
CONTENT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def fail(message, response=None):
    print(f"[FAIL] {message}")
    if response is not None:
        print(f"       HTTP {response.status_code}: {response.text[:300]}")
    sys.exit(1)


def random_picture():
    color = tuple(random.randint(30, 225) for _ in range(3))
    accent = tuple(255 - c for c in color)
    image = Image.new("RGB", (600, 400), color)
    draw = ImageDraw.Draw(image)
    draw.ellipse((150, 50, 450, 350), fill=accent)
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue(), "image/png"


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    email, password = sys.argv[1], sys.argv[2]
    if len(sys.argv) > 3:
        path = sys.argv[3]
        content_type = CONTENT_TYPES.get(os.path.splitext(path)[1].lower())
        if content_type is None:
            fail("Use a .png, .jpg or .webp file.")
        data = open(path, "rb").read()
    else:
        data, content_type = random_picture()

    session = requests.Session()
    response = session.post(f"{API}/api/auth/login/", json={"email": email, "password": password}, timeout=30)
    if response.status_code != 200:
        fail("Login failed (is the account verified?)", response)
    auth = {"Authorization": "Bearer " + response.json()["access"]}
    print("[ok] logged in")

    response = session.post(f"{API}/api/avatars/upload-url/", json={"content_type": content_type}, headers=auth, timeout=30)
    if response.status_code != 200:
        fail("Could not get an upload URL", response)
    upload = response.json()
    print(f"[ok] got a presigned upload for key {upload['fields']['key']}")

    # The browser would post to the public address; from inside Docker we use the internal one.
    response = requests.post(
        upload["url"].replace(S3_PUBLIC, S3_INTERNAL, 1),
        data=upload["fields"],
        files={"file": ("upload", data)},
        timeout=60,
    )
    if response.status_code not in (200, 201, 204):
        fail("S3 rejected the upload", response)
    print(f"[ok] uploaded {len(data)} bytes straight to S3")

    response = session.post(f"{API}/api/avatars/confirm/", json={"upload_token": upload["upload_token"]}, headers=auth, timeout=60)
    if response.status_code not in (200, 201):
        fail("Confirm failed", response)
    avatar = response.json()
    state = "created" if response.status_code == 201 else "already existed"
    print(f"[ok] picture {state}: {avatar['width']}x{avatar['height']}, current={avatar['is_current']}")

    response = session.get(f"{API}/api/avatars/", headers=auth, timeout=30)
    listing = response.json()
    print(f"\nYou now have {len(listing['results'])} picture(s) (max {listing['max_avatars']}):")
    for item in listing["results"]:
        marker = "  <- current" if item["is_current"] else ""
        print(f"  {item['id']}  {item['width']}x{item['height']}{marker}")
        print(f"    preview (valid 1 hour, open in your browser): {item['preview_url']}")


if __name__ == "__main__":
    main()
