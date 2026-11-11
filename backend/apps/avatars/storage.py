"""All S3 access for avatars (design doc, section 8.1). Works against Silo locally and AWS S3 when hosted.

Bucket layout:
    uploads/{user_id}/{upload_id}          raw browser uploads (temporary; a lifecycle rule expires them)
    originals/{user_id}/{avatar_id}.webp   validated, re-encoded, full-size image
    derived/{avatar_id}/{size}.webp        resized square copies (created on demand, see Step 5)
"""
import logging

from botocore.exceptions import ClientError
from django.conf import settings

from apps.core.s3 import get_s3_client

logger = logging.getLogger(__name__)

PRESIGN_EXPIRES = 600  # seconds the browser has to start an upload


class ObjectNotFound(Exception):
    pass


class ObjectTooLarge(Exception):
    pass


# ---- keys ----
def upload_key(user_id, upload_id):
    return f"uploads/{user_id}/{upload_id}"


def original_key(user_id, avatar_id):
    return f"originals/{user_id}/{avatar_id}.webp"


def derived_key(avatar_id, size):
    return f"derived/{avatar_id}/{size}.webp"


def derived_prefix(avatar_id):
    return f"derived/{avatar_id}/"


# ---- clients ----
def bucket():
    return settings.AWS_STORAGE_BUCKET_NAME


def _client():
    return get_s3_client()


def _signing_client():
    """Signs URLs with the address the BROWSER can reach (differs from the internal one locally)."""
    return get_s3_client(public=True)


# ---- presigned URLs ----
def create_presigned_upload(user_id, upload_id, content_type):
    """Returns (key, post) where post = {"url": ..., "fields": {...}} for a direct browser upload.

    The policy limits the file size and fixes the content type and key, so S3 itself rejects anything else.
    """
    key = upload_key(user_id, upload_id)
    post = _signing_client().generate_presigned_post(
        Bucket=bucket(),
        Key=key,
        Fields={"Content-Type": content_type},
        Conditions=[
            {"Content-Type": content_type},
            ["content-length-range", 1, settings.AVATAR_MAX_UPLOAD_BYTES],
        ],
        ExpiresIn=PRESIGN_EXPIRES,
    )
    return key, post


def presigned_get_url(key, expires=3600):
    return _signing_client().generate_presigned_url(
        "get_object", Params={"Bucket": bucket(), "Key": key}, ExpiresIn=expires
    )


# ---- reading and writing ----
def read_object(key, max_bytes):
    """Returns the object's bytes, without reading more than max_bytes."""
    client = _client()

    try:
        head = client.head_object(Bucket=bucket(), Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in (
            "404", "NoSuchKey", "NotFound"
        ):
            raise ObjectNotFound(key) from exc
        raise

    if head["ContentLength"] > max_bytes:
        raise ObjectTooLarge(key)

    response = client.get_object(Bucket=bucket(), Key=key)
    body = response["Body"]

    try:
        data = body.read(max_bytes + 1)
    finally:
        body.close()

    if len(data) > max_bytes:
        raise ObjectTooLarge(key)

    return data


def try_read_object(key, max_bytes):
    """Returns the object's bytes, or None if it does not exist. One S3 request (used on the public hot path)."""
    try:
        response = _client().get_object(Bucket=bucket(), Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "NotFound"):
            return None
        raise
    body = response["Body"]
    try:
        data = body.read(max_bytes + 1)
    finally:
        body.close()
    if len(data) > max_bytes:
        raise ObjectTooLarge(key)
    return data


def put_object(key, data, content_type):
    _client().put_object(Bucket=bucket(), Key=key, Body=data, ContentType=content_type)


def delete_objects(keys):
    """Best effort: a storage failure is logged but never breaks the request."""
    client = _client()
    for key in keys:
        try:
            client.delete_object(Bucket=bucket(), Key=key)
        except Exception:  # noqa: BLE001
            logger.exception("Could not delete S3 object %s", key)


def delete_prefix(prefix):
    """Deletes every object whose key starts with prefix. Best effort, like delete_objects."""
    client = _client()
    try:
        paginator = client.get_paginator("list_objects_v2")
        keys = [
            item["Key"]
            for page in paginator.paginate(Bucket=bucket(), Prefix=prefix)
            for item in page.get("Contents", [])
        ]
    except Exception:  # noqa: BLE001
        logger.exception("Could not list S3 objects under %s", prefix)
        return
    delete_objects(keys)