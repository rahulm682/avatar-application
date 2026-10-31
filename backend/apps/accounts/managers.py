from django.contrib.auth.base_user import BaseUserManager
from django.utils import timezone

from apps.core.softdelete import SoftDeleteManagerMixin

from .emailhash import normalize_email


class UserManager(SoftDeleteManagerMixin, BaseUserManager):
    """`User.objects` hides soft-deleted accounts; use `User.all_objects` to see them."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        email = normalize_email(email)
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=email, **extra_fields)
        user.set_password(password)  # password=None stores an unusable password
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        # Admins created from the command line can log in right away.
        extra_fields.setdefault("email_verified_at", timezone.now())
        if not extra_fields["is_staff"] or not extra_fields["is_superuser"]:
            raise ValueError("A superuser must have is_staff=True and is_superuser=True.")
        return self._create_user(email, password, **extra_fields)

    def get_by_email(self, email):
        """Look a user up by email, applying the same normalization as when it was stored."""
        return self.get(email=normalize_email(email))