#!/usr/bin/env python3
"""S3 smoke test for the local Silo setup (design doc, section 13.6).

Checks the S3 features the application relies on. Prints PASS / WARN / FAIL lines
and exits non-zero if any check FAILs. Run it with:  make smoke
"""
import os
import secrets
import sys

import requests
from botocore.exceptions import ClientError

import s3_common as s3c

BUCKET = os.environ["AWS_STORAGE_BUCKET_NAME"]
INTERNAL = os.environ["AWS_S3_ENDPOINT_URL"].rstrip("/")
PUBLIC = (os.environ.get("AWS_S3_PUBLIC_ENDPOINT_URL") or INTERNAL).rstrip("/")
ORIGIN = os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",")[0].strip()
MAX_BYTES = 5 * 1024 * 1024

failures = 0
created_keys = []


def report(status, name, detail=""):
    global failures
    if status == "FAIL":
        failures += 1
    print(f"[{status}] {name}" + (f" - {detail}" if detail else ""))


def presigned_post(signer, key):
    """Build a presigned POST the way the real API will, and return it with the internal URL."""
    post = signer.generate_presigned_post(
        Bucket=BUCKET,
        Key=key,
        Fields=None,
        Conditions=[
            ["content-length-range", 1, MAX_BYTES],
            ["starts-with", "$Content-Type", "image/"],
        ],
        ExpiresIn=300,
    )
    # The browser would use the public URL. From inside Docker we post to the internal address;
    # a POST policy signature does not include the host, so the signature stays valid.
    return post, post["url"].replace(PUBLIC, INTERNAL, 1)


def main():
    root = s3c.root_client()
    s3c.wait_for_s3(root)

    if not os.environ.get("AWS_ACCESS_KEY_ID"):
        report("FAIL", "application access key", "AWS_ACCESS_KEY_ID is empty in .env")
        return
    app = s3c.app_client()
    signer = s3c.public_signing_client()

    # 1. bucket exists
    try:
        root.head_bucket(Bucket=BUCKET)
        report("PASS", "bucket exists", BUCKET)
    except ClientError as exc:
        report("FAIL", "bucket exists", f"{exc} (run: make bucket)")
        return

    # 2. application key works
    try:
        app.list_objects_v2(Bucket=BUCKET, MaxKeys=1)
        report("PASS", "application key can list the bucket")
    except ClientError as exc:
        report("FAIL", "application key can list the bucket", f"{exc} (run: make app-key)")
        return

    # 3. least privilege: the app key must not be able to create buckets
    probe = "smoke-denied-" + secrets.token_hex(4)
    try:
        app.create_bucket(Bucket=probe)
        report("FAIL", "application key is restricted", "it was able to create another bucket")
        root.delete_bucket(Bucket=probe)
    except ClientError:
        report("PASS", "application key is restricted (cannot create buckets)")

    # 4. bucket is private
    key = "smoke/private-" + secrets.token_hex(4) + ".txt"
    created_keys.append(key)
    app.put_object(Bucket=BUCKET, Key=key, Body=b"private")
    resp = requests.get(f"{INTERNAL}/{BUCKET}/{key}", timeout=10)
    if resp.status_code in (401, 403):
        report("PASS", "anonymous reads are denied", f"HTTP {resp.status_code}")
    else:
        report("FAIL", "anonymous reads are denied", f"got HTTP {resp.status_code}")

    # 5. valid presigned POST
    key = "uploads/smoke/" + secrets.token_hex(4)
    created_keys.append(key)
    post, url = presigned_post(signer, key)
    resp = requests.post(
        url,
        data={**post["fields"], "Content-Type": "image/png"},
        files={"file": ("smoke.png", b"not-really-a-png")},
        timeout=20,
    )
    if resp.status_code in (200, 201, 204):
        try:
            app.head_object(Bucket=BUCKET, Key=key)
            report("PASS", "presigned POST upload works", f"HTTP {resp.status_code}")
        except ClientError as exc:
            report("FAIL", "presigned POST upload works", f"upload accepted but object not found: {exc}")
    else:
        report("FAIL", "presigned POST upload works", f"HTTP {resp.status_code}: {resp.text[:200]}")

    # 6. oversized upload is rejected
    key = "uploads/smoke/" + secrets.token_hex(4)
    post, url = presigned_post(signer, key)
    resp = requests.post(
        url,
        data={**post["fields"], "Content-Type": "image/png"},
        files={"file": ("big.png", b"x" * (MAX_BYTES + 1))},
        timeout=60,
    )
    if resp.status_code >= 400:
        report("PASS", "presigned POST rejects files over 5 MB", f"HTTP {resp.status_code}")
    else:
        created_keys.append(key)
        report("FAIL", "presigned POST rejects files over 5 MB", f"HTTP {resp.status_code}")

    # 7. wrong content type is rejected
    key = "uploads/smoke/" + secrets.token_hex(4)
    post, url = presigned_post(signer, key)
    resp = requests.post(
        url,
        data={**post["fields"], "Content-Type": "text/plain"},
        files={"file": ("note.txt", b"hello")},
        timeout=20,
    )
    if resp.status_code >= 400:
        report("PASS", "presigned POST rejects non-image content types", f"HTTP {resp.status_code}")
    else:
        created_keys.append(key)
        report("FAIL", "presigned POST rejects non-image content types", f"HTTP {resp.status_code}")

    # 8. CORS: allowed origin
    pre = requests.options(
        url,
        headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"},
        timeout=10,
    )
    allow = pre.headers.get("Access-Control-Allow-Origin")
    if allow in (ORIGIN, "*"):
        report("PASS", "CORS preflight allows the frontend origin", f"{ORIGIN} -> {allow}")
    else:
        report("FAIL", "CORS preflight allows the frontend origin", f"HTTP {pre.status_code}, header={allow!r}")

    # 9. CORS: a foreign origin should not be allowed (warning only: a server-wide CORS setting may be permissive)
    pre = requests.options(
        url,
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        timeout=10,
    )
    allow = pre.headers.get("Access-Control-Allow-Origin")
    if allow in (None, ""):
        report("PASS", "CORS preflight denies other origins")
    else:
        report("WARN", "CORS preflight denies other origins",
               f"server answered {allow!r}; the server-wide CORS setting may be overriding the bucket rule")

    # 10. lifecycle rule stored
    try:
        rules = root.get_bucket_lifecycle_configuration(Bucket=BUCKET).get("Rules", [])
        ok = any(
            r.get("Status") == "Enabled"
            and (r.get("Filter", {}).get("Prefix") or r.get("Prefix")) == "uploads/"
            and r.get("Expiration", {}).get("Days") == 1
            for r in rules
        )
        report("PASS" if ok else "FAIL", "lifecycle rule for uploads/ is stored")
    except ClientError as exc:
        report("FAIL", "lifecycle rule for uploads/ is stored", str(exc))

    # 11. read, list, delete with the application key
    try:
        body = app.get_object(Bucket=BUCKET, Key=created_keys[0])["Body"].read()
        listed = app.list_objects_v2(Bucket=BUCKET, Prefix="smoke/").get("KeyCount", 0)
        app.delete_object(Bucket=BUCKET, Key=created_keys[0])
        report("PASS", "application key can read, list and delete", f"read {len(body)} bytes, listed {listed}")
    except ClientError as exc:
        report("FAIL", "application key can read, list and delete", str(exc))


if __name__ == "__main__":
    try:
        main()
    finally:
        # Clean up anything the test created.
        try:
            client = s3c.app_client()
            for k in created_keys:
                try:
                    client.delete_object(Bucket=BUCKET, Key=k)
                except ClientError:
                    pass
        except Exception:  # noqa: BLE001
            pass
    print()
    print("Smoke test finished with %d failure(s)." % failures)
    sys.exit(1 if failures else 0)
