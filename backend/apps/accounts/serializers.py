from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .emailhash import normalize_email
from .models import User


def check_password_strength(password, user=None):
    """Runs Django's password validators and converts failures to API errors."""
    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(list(exc.messages)) from exc


class NormalizedEmailField(serializers.EmailField):
    """An email field that trims and lowercases its value (the same rule as the public hash)."""

    def to_internal_value(self, data):
        return normalize_email(super().to_internal_value(data))


def password_field(**kwargs):
    return serializers.CharField(
        write_only=True, trim_whitespace=False, max_length=128, style={"input_type": "password"}, **kwargs
    )


# ---------- generic responses (for the API schema) ----------
class DetailSerializer(serializers.Serializer):
    detail = serializers.CharField()


class AccessTokenSerializer(serializers.Serializer):
    access = serializers.CharField()


# ---------- profile ----------
class ProfileSerializer(serializers.ModelSerializer):
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "email_hash", "display_name", "bio", "email_verified_at", "created_at", "avatar_url"]
        read_only_fields = ["id", "email", "email_hash", "email_verified_at", "created_at", "avatar_url"]

    def get_avatar_url(self, user) -> str:
        base = (settings.AVATAR_BASE_URL or "").rstrip("/")
        return f"{base}/avatar/{user.email_hash}"


class LoginResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    user = ProfileSerializer()


# ---------- requests ----------
class RegisterSerializer(serializers.Serializer):
    email = NormalizedEmailField(max_length=254)
    password = password_field()

    def validate(self, attrs):
        try:
            # An unsaved user lets the "too similar to your email" validator work.
            check_password_strength(attrs["password"], User(email=attrs["email"]))
        except serializers.ValidationError as exc:
            raise serializers.ValidationError({"password": exc.detail}) from exc
        return attrs


class LoginSerializer(serializers.Serializer):
    email = serializers.CharField(max_length=254)
    password = password_field()


class EmailSerializer(serializers.Serializer):
    email = NormalizedEmailField(max_length=254)


class TokenSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=2048)


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField(max_length=128)
    token = serializers.CharField(max_length=256)
    new_password = password_field()


class ChangePasswordSerializer(serializers.Serializer):
    current_password = password_field()
    new_password = password_field()


class EmailChangeRequestSerializer(serializers.Serializer):
    new_email = NormalizedEmailField(max_length=254)
    password = password_field()


class DeleteAccountSerializer(serializers.Serializer):
    password = password_field()
