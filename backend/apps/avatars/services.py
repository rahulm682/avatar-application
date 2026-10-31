"""Avatar business logic (design doc, sections 8 and 9.4)."""
import hashlib
import logging
import uuid

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core.cdn import invalidate_email_hashes

from . import imaging, storage
from .models import Avatar

logger = logging.getLogger(__name__)

PREVIEW_SIZE = 160  # a derived copy of this size is created for every new avatar; the picture list shows it
_UPLOAD_SALT = "avatars.upload"
_UPLOAD_TOKEN_MAX_AGE = 60 * 60  # 1 hour (the bucket's lifecycle rule removes abandoned uploads after a day)


class AvatarError(Exception):
    """A problem the user can understand and fix. message is safe to return in the API response."""

    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---- upload tokens (stateless, like the email tokens) ----
def make_upload_token(user, key):
    return signing.dumps({"uid": str(user.pk), "key": key, "purpose": "avatar_upload"}, salt=_UPLOAD_SALT)


def read_upload_token(token):
    try:
        payload = signing.loads(token, salt=_UPLOAD_SALT, max_age=_UPLOAD_TOKEN_MAX_AGE)
    except signing.BadSignature:
        return None
    if not isinstance(payload, dict) or payload.get("purpose") != "avatar_upload":
        return None
    return payload


def avatar_count(user):
    return Avatar.objects.filter(user=user).count()


def limit_message():
    return f"You can have at most {settings.AVATAR_MAX_PER_USER} pictures. Delete one first."


# ---- confirm an upload ----
def confirm_upload(user, key):
    """Validates, cleans and registers an uploaded file. Returns (avatar, created).

    created is False when the same picture was already uploaded (the existing one is returned).
    The first picture a user ever uploads becomes their current avatar.
    """
    max_bytes = settings.AVATAR_MAX_UPLOAD_BYTES
    try:
        raw = storage.read_object(key, max_bytes)
    except storage.ObjectNotFound:
        raise AvatarError("Upload not found. Upload the file first, then confirm.") from None
    except storage.ObjectTooLarge:
        storage.delete_objects([key])
        raise AvatarError(f"The file is larger than {max_bytes // (1024 * 1024)} MB.") from None

    try:
        processed = imaging.process_upload(raw, settings.AVATAR_MAX_DIMENSION)
    except imaging.InvalidImage as exc:
        storage.delete_objects([key])
        raise AvatarError(str(exc)) from None

    content_hash = hashlib.sha256(processed.data).hexdigest()
    avatar_id = uuid.uuid4()
    became_current = False

    with transaction.atomic():
        # Lock the user row so two simultaneous confirms cannot exceed the limit.
        locked_user = User.objects.select_for_update().get(pk=user.pk)

        existing = Avatar.objects.filter(user=locked_user, content_hash=content_hash).first()
        if existing is not None:
            storage.delete_objects([key])
            return existing, False

        if avatar_count(locked_user) >= settings.AVATAR_MAX_PER_USER:
            storage.delete_objects([key])
            raise AvatarError(limit_message())

        original = storage.original_key(user.pk, avatar_id)
        storage.put_object(original, processed.data, "image/webp")
        storage.put_object(
            storage.derived_key(avatar_id, PREVIEW_SIZE),
            imaging.make_square(processed.data, PREVIEW_SIZE),
            "image/webp",
        )
        avatar = Avatar.objects.create(
            id=avatar_id,
            user=locked_user,
            storage_key=original,
            content_hash=content_hash,
            mime_type="image/webp",
            size_bytes=len(processed.data),
            width=processed.width,
            height=processed.height,
        )
        if locked_user.current_avatar_id is None:
            locked_user.current_avatar = avatar
            locked_user.save(update_fields=["current_avatar", "updated_at"])
            became_current = True

    storage.delete_objects([key])  # the raw upload is no longer needed
    if became_current:
        # Responses cached for this email hash so far were fallback images.
        invalidate_email_hashes(user.email_hash)
    return avatar, True


# ---- choose the current avatar ----
def set_current_avatar(user, avatar):
    """avatar may be None (back to the default picture). Returns True if anything changed."""
    new_id = avatar.pk if avatar is not None else None
    if user.current_avatar_id == new_id:
        return False
    user.current_avatar = avatar
    user.save(update_fields=["current_avatar", "updated_at"])
    invalidate_email_hashes(user.email_hash)
    return True


# ---- deletion ----
def delete_avatar(avatar):
    """Soft delete: the picture disappears for everyone, but its row and S3 files stay until the purge job runs.

    If it was the current picture, the user goes back to the default image and the CDN copies are cleared.
    """
    user = avatar.user
    was_current = user.current_avatar_id == avatar.pk
    avatar.is_deleted = True
    avatar.deleted_at = timezone.now()
    avatar.save(update_fields=["is_deleted", "deleted_at"])
    if was_current:
        user.current_avatar = None
        user.save(update_fields=["current_avatar", "updated_at"])
        invalidate_email_hashes(user.email_hash)


def restore_avatar(avatar):
    """Brings a soft-deleted picture back (it does not become the current picture again)."""
    if not avatar.is_deleted:
        return
    user = avatar.user
    if user.is_deleted:
        raise AvatarError("Restore the account first.", 409)
    if avatar_count(user) >= settings.AVATAR_MAX_PER_USER:
        raise AvatarError(limit_message(), 409)
    if Avatar.objects.filter(user=user, content_hash=avatar.content_hash).exists():
        raise AvatarError("The user already has this picture.", 409)
    avatar.is_deleted = False
    avatar.deleted_at = None
    avatar.save(update_fields=["is_deleted", "deleted_at"])


def purge_avatar(avatar):
    """Removes a picture for good: the row, the S3 files, and (if it was current) the CDN copies."""
    user = avatar.user
    was_current = user.current_avatar_id == avatar.pk
    avatar_id, original, email_hash = avatar.pk, avatar.storage_key, user.email_hash

    avatar.delete()  # User.current_avatar is set to NULL automatically
    storage.delete_objects([original])
    storage.delete_prefix(storage.derived_prefix(avatar_id))
    if was_current:
        invalidate_email_hashes(email_hash)


def delete_all_files_for_user(user):
    """Removes every S3 file of a user, including the files of soft-deleted pictures. Never raises."""
    try:
        for avatar_id in Avatar.all_objects.filter(user=user).values_list("id", flat=True):
            storage.delete_prefix(storage.derived_prefix(avatar_id))
        storage.delete_prefix(f"originals/{user.pk}/")
        storage.delete_prefix(f"uploads/{user.pk}/")
    except Exception:  # noqa: BLE001
        logger.exception("Could not delete all files for user %s", user.pk)