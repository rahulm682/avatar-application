#!/usr/bin/env python3
"""Watch CDN invalidation work, live (design doc, section 9.4).

Usage (from the project root):
    docker compose run --rm silo-init python /scripts/demo_invalidation.py EMAIL PASSWORD

It uploads two temporary pictures, then changes and deletes the current one while fetching the public avatar
through the CDN (Varnish) after every step. For each fetch it prints X-Cache (MISS = came from the origin,
HIT = served from the CDN's cache), Age and ETag. After a change the very next fetch must be a MISS with a new
ETag: that proves the CDN was told to forget the old picture. Your account is left as it was found.
"""
import hashlib
import os
import random
import sys
from io import BytesIO

import requests
from PIL import Image, ImageDraw

API = os.environ.get("API_BASE_URL", "http://backend:8000")
CDN = os.environ.get("CDN_URL", os.environ.get("VARNISH_BAN_URL", "http://varnish:80")).rstrip("/")
S3_INTERNAL = os.environ["AWS_S3_ENDPOINT_URL"]
S3_PUBLIC = os.environ.get("AWS_S3_PUBLIC_ENDPOINT_URL") or S3_INTERNAL

problems = []


def fail(message, response=None):
    print(f"[FAIL] {message}")
    if response is not None:
        print(f"       HTTP {response.status_code}: {response.text[:300]}")
    sys.exit(1)


def random_picture():
    color = tuple(random.randint(30, 225) for _ in range(3))
    image = Image.new("RGB", (600, 400), color)
    ImageDraw.Draw(image).ellipse((150, 50, 450, 350), fill=tuple(255 - c for c in color))
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


class Api:
    def __init__(self, email, password):
        self.session = requests.Session()
        response = self.session.post(f"{API}/api/auth/login/", json={"email": email, "password": password}, timeout=30)
        if response.status_code != 200:
            fail("Login failed (is the account verified?)", response)
        self.auth = {"Authorization": "Bearer " + response.json()["access"]}

    def call(self, method, path, expected, **kwargs):
        response = self.session.request(method, f"{API}{path}", headers=self.auth, timeout=60, **kwargs)
        if response.status_code not in expected:
            fail(f"{method} {path} gave an unexpected answer", response)
        return response

    def upload_new_picture(self):
        response = self.call("POST", "/api/avatars/upload-url/", (200,), json={"content_type": "image/png"})
        upload = response.json()
        stored = requests.post(
            upload["url"].replace(S3_PUBLIC, S3_INTERNAL, 1),
            data=upload["fields"],
            files={"file": ("upload", random_picture())},
            timeout=60,
        )
        if stored.status_code not in (200, 201, 204):
            fail("S3 rejected the upload", stored)
        return self.call("POST", "/api/avatars/confirm/", (200, 201), json={"upload_token": upload["upload_token"]}).json()

    def listing(self):
        return self.call("GET", "/api/avatars/", (200,)).json()

    def set_current(self, avatar_id):
        self.call("PUT", "/api/me/current-avatar/", (200,), json={"avatar_id": avatar_id})

    def delete(self, avatar_id):
        self.call("DELETE", f"/api/avatars/{avatar_id}/", (204,))


def fetch(url, label):
    # Django only accepts the hosts listed in DJANGO_ALLOWED_HOSTS. A browser reaches the CDN as "localhost",
    # but inside Docker it is "varnish", so present the same Host header a browser would.
    response = requests.get(url, headers={"Host": "localhost:8080"}, timeout=30)
    info = {
        "status": response.status_code,
        "cache": response.headers.get("X-Cache", "?"),
        "age": response.headers.get("Age", "-"),
        "etag": response.headers.get("ETag", "-"),
    }
    print(f"    {label:<34} HTTP {info['status']}  X-Cache: {info['cache']:<4}  Age: {info['age']:<3}  ETag: {info['etag']}")
    return info


def expect(condition, description):
    print(f"    {'OK ' if condition else 'BAD'} {description}")
    if not condition:
        problems.append(description)


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    email, password = sys.argv[1], sys.argv[2]
    email_hash = hashlib.sha256(email.strip().lower().encode()).hexdigest()
    url = f"{CDN}/avatar/{email_hash}?s=160"

    api = Api(email, password)
    before = api.listing()
    if before["max_avatars"] - len(before["results"]) < 2:
        fail(f"This script needs room for 2 more pictures (you have {len(before['results'])}/{before['max_avatars']}).")
    original_current = before["current_avatar_id"]
    print(f"Public URL: {url}\nCurrent picture before the demo: {original_current or 'none'}\n")

    picture_a = api.upload_new_picture()
    picture_b = api.upload_new_picture()
    print("1. Make picture A the current one, then fetch twice")
    api.set_current(picture_a["id"])
    first = fetch(url, "fetch #1 (cold)")
    second = fetch(url, "fetch #2")
    expect(first["cache"] == "MISS", "the first fetch had to go to the origin")
    expect(second["cache"] == "HIT", "the second fetch came from the CDN cache")
    expect(first["etag"] == second["etag"], "same picture, same ETag")

    print("\n2. Switch the current picture to B (the API asks the CDN to forget A)")
    api.set_current(picture_b["id"])
    after_switch = fetch(url, "fetch right after the switch")
    again = fetch(url, "fetch again")
    expect(after_switch["cache"] == "MISS", "the cached copy of A was removed, so this was a MISS")
    expect(after_switch["etag"] != first["etag"], "the new answer is a different picture (new ETag)")
    expect(again["cache"] == "HIT", "the new picture is cached again")

    print("\n3. Delete B, the current picture (the user falls back to the default image)")
    api.delete(picture_b["id"])
    after_delete = fetch(url, "fetch right after the delete")
    expect(after_delete["cache"] == "MISS", "the cached copy of B was removed")
    expect(after_delete["etag"] != after_switch["etag"], "the answer is now the default image (new ETag)")

    print("\n4. Clean up: delete A and restore your previous current picture")
    api.delete(picture_a["id"])
    if original_current:
        still_there = {item["id"] for item in api.listing()["results"]}
        api.set_current(original_current if original_current in still_there else None)
    final = fetch(url, "fetch after clean-up")
    if original_current:
        expect(final["cache"] == "MISS", "restoring your previous picture invalidated the cache")
    else:
        # Nothing public changed (the default image is still what everyone gets), so the cache is still valid.
        expect(final["cache"] == "HIT", "nothing changed publicly, so the cached default image is still served")

    print()
    if problems:
        print(f"{len(problems)} check(s) did not behave as expected. Look at the backend logs (make logs).")
        sys.exit(1)
    print("All checks passed: the CDN forgets a picture as soon as it changes.")


if __name__ == "__main__":
    main()