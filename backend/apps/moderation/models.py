import uuid

from django.db import models


class Report(models.Model):
    """A report about a picture (design doc, section 4.3).

    It stores the picture's and the user's IDs as plain values instead of foreign keys, on purpose: a moderation
    record is an audit trail and must survive when the picture or the account is deleted.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ACTIONED = "actioned", "Actioned"
        DISMISSED = "dismissed", "Dismissed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    avatar_uuid = models.UUIDField(db_index=True)  # the picture that was current when it was reported
    user_uuid = models.UUIDField(db_index=True)  # the owner of that picture
    email_hash = models.CharField(max_length=64)  # the public address that was reported
    reason = models.CharField(max_length=500)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    handled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_status_display()} report on {self.avatar_uuid}"