from django.conf import settings
from rest_framework import serializers

from . import storage
from .imaging import ALLOWED_CONTENT_TYPES
from .models import Avatar
from .services import PREVIEW_SIZE


class UploadUrlRequestSerializer(serializers.Serializer):
    content_type = serializers.ChoiceField(choices=ALLOWED_CONTENT_TYPES)
    size = serializers.IntegerField(min_value=1, required=False, help_text="File size in bytes (optional early check).")

    def validate_size(self, value):
        if value > settings.AVATAR_MAX_UPLOAD_BYTES:
            raise serializers.ValidationError(
                f"The file is larger than {settings.AVATAR_MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
            )
        return value


class UploadUrlResponseSerializer(serializers.Serializer):
    url = serializers.CharField()
    fields = serializers.DictField(child=serializers.CharField())
    upload_token = serializers.CharField()
    expires_in = serializers.IntegerField()
    max_bytes = serializers.IntegerField()


class ConfirmUploadSerializer(serializers.Serializer):
    upload_token = serializers.CharField(max_length=2048)


class AvatarSerializer(serializers.ModelSerializer):
    """Needs context['current_avatar_id'] to fill in is_current."""

    is_current = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()

    class Meta:
        model = Avatar
        fields = ["id", "width", "height", "size_bytes", "created_at", "is_current", "preview_url"]
        read_only_fields = fields

    def get_is_current(self, avatar) -> bool:
        return avatar.pk == self.context.get("current_avatar_id")

    def get_preview_url(self, avatar) -> str:
        """A temporary link (valid for an hour) to the 160 px preview. Only the owner receives it."""
        return storage.presigned_get_url(storage.derived_key(avatar.pk, PREVIEW_SIZE))


class AvatarListSerializer(serializers.Serializer):
    results = AvatarSerializer(many=True)
    current_avatar_id = serializers.UUIDField(allow_null=True)
    max_avatars = serializers.IntegerField()


class CurrentAvatarRequestSerializer(serializers.Serializer):
    avatar_id = serializers.UUIDField(allow_null=True)


class CurrentAvatarResponseSerializer(serializers.Serializer):
    current_avatar_id = serializers.UUIDField(allow_null=True)