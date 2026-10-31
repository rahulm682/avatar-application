"""Account-level soft delete, restore and permanent removal (design doc, section 4.5)."""
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.avatars.models import Avatar
from apps.avatars.services import delete_all_files_for_user
from apps.core.cdn import invalidate_email_hashes

from .authtokens import revoke_all_refresh_tokens
from .models import User

logger = logging.getLogger(__name__)


class RestoreError(Exception):
    """The account cannot be restored. The message is meant for an administrator."""


def tombstone_email(user):
    return f"deleted-{user.pk}@deleted.invalid"  # .invalid can never be a real address


def soft_delete_user(user):
    """Marks the account and all its pictures as deleted. Nothing is removed yet.

    - the account can no longer log in, and its tokens stop working (User.objects no longer finds it)
    - the email address is freed, so a new account can be created with it
    - the public avatar disappears immediately (the CDN is told, and the hash changes with the email)
    - S3 files are kept until the retention period is over (manage.py purge_deleted)
    """
    now = timezone.now()
    old_hash = user.email_hash
    with transaction.atomic():
        user.original_email = user.email
        user.email = tombstone_email(user)  # save() recomputes email_hash from it
        user.is_deleted = True
        user.deleted_at = now
        user.save()
        # Only pictures that are still alive get the account's timestamp; that is how restore finds them again.
        Avatar.objects.filter(user=user).update(is_deleted=True, deleted_at=now)
        revoke_all_refresh_tokens(user)
    invalidate_email_hashes(old_hash)


def restore_user(user):
    """Brings a soft-deleted account back, with the pictures that were deleted together with it."""
    if not user.is_deleted:
        return
    email = user.original_email
    if not email:
        raise RestoreError("The original email address is unknown.")
    if User.objects.filter(email=email).exists():
        raise RestoreError(f"A new account already uses {email}. Remove or rename that account first.")

    deleted_at = user.deleted_at
    try:
        with transaction.atomic():
            user.email = email
            user.original_email = ""
            user.is_deleted = False
            user.deleted_at = None
            user.save()
            Avatar.all_objects.filter(user=user, is_deleted=True, deleted_at=deleted_at).update(
                is_deleted=False, deleted_at=None
            )
    except IntegrityError:
        raise RestoreError(f"A new account already uses {email}.") from None
    invalidate_email_hashes(user.email_hash)


def purge_user(user):
    """Removes an account for good: S3 files, pictures and the account row. Reports about it are kept."""
    email_hash = user.email_hash
    delete_all_files_for_user(user)  # includes the files of soft-deleted pictures
    user.delete()  # the avatar rows go with it
    invalidate_email_hashes(email_hash)