import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.validators import MaxLengthValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from .emailhash import hash_email, normalize_email
from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    """One email per user. The email is the login name and the source of the public avatar hash.

    current_avatar is the picture other applications receive (see apps.avatars).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(max_length=254, unique=True)
    email_hash = models.CharField(max_length=64, unique=True, editable=False)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    display_name = models.CharField(max_length=80, blank=True)
    bio = models.TextField(blank=True, validators=[MaxLengthValidator(500)])
    # The picture served at /avatar/{email_hash}. SET_NULL: deleting that picture falls back to the default image.
    current_avatar = models.ForeignKey(
        "avatars.Avatar", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Soft delete (see apps.core.softdelete). While an account is deleted, its email is replaced by a placeholder so the
    # address is free again; the real one is kept in original_email so the account can be restored.
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    original_email = models.EmailField(max_length=254, blank=True)

    objects = UserManager()  # hides deleted accounts. It must stay the first manager: Django uses it as the default
    all_objects = models.Manager()  # includes deleted accounts (admin, restore, purge)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        constraints = [
            # Emails are always stored lowercase, so uniqueness is effectively case-insensitive.
            models.CheckConstraint(condition=Q(email=Lower("email")), name="user_email_is_lowercase"),
        ]

    def __str__(self):
        return self.email

    @property
    def is_email_verified(self):
        return self.email_verified_at is not None

    def save(self, *args, **kwargs):
        # Keep the stored email normalized and the hash in sync, whatever code changes the email.
        self.email = normalize_email(self.email)
        self.email_hash = hash_email(self.email)
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "email" in update_fields:
            kwargs["update_fields"] = set(update_fields) | {"email_hash"}
        super().save(*args, **kwargs)