import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.softdelete import SoftDeleteManagerMixin


class AvatarManager(SoftDeleteManagerMixin, models.Manager):
    """`Avatar.objects` hides soft-deleted pictures; use `Avatar.all_objects` to see them."""


class Avatar(models.Model):
    """One uploaded picture. The user's CURRENT picture is User.current_avatar."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="avatars")
    storage_key = models.CharField(max_length=255)  # originals/{user_id}/{avatar_id}.webp
    content_hash = models.CharField(max_length=64)  # SHA-256 of the processed image, used to detect duplicates
    mime_type = models.CharField(max_length=50, default="image/webp")
    size_bytes = models.PositiveIntegerField()
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    # Soft delete (see apps.core.softdelete): a deleted picture keeps its row and its S3 files until the purge job runs.
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = AvatarManager()  # hides deleted pictures; must stay the first manager
    all_objects = models.Manager()  # includes deleted pictures (admin, restore, purge)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Only live pictures must be unique, so a deleted picture can be uploaded again.
            models.UniqueConstraint(
                fields=["user", "content_hash"],
                condition=Q(is_deleted=False),
                name="unique_live_avatar_content_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.user_id}/{self.id}"