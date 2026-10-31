"""Avatar management endpoints (design doc, section 7). All require a logged-in user."""
import uuid
import logging

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.serializers import DetailSerializer

from . import services, storage
from .models import Avatar
from .serializers import (
    AvatarListSerializer,
    AvatarSerializer,
    ConfirmUploadSerializer,
    CurrentAvatarRequestSerializer,
    CurrentAvatarResponseSerializer,
    UploadUrlRequestSerializer,
    UploadUrlResponseSerializer,
)
from .throttles import ConfirmThrottle, ManageThrottle, UploadUrlThrottle

logger = logging.getLogger(__name__)

NOT_FOUND = "Picture not found."
BAD_UPLOAD = "This upload is invalid or has expired. Please upload the file again."


def _detail(message, http_status):
    return Response({"detail": message}, status=http_status)


class UploadUrlView(APIView):
    throttle_classes = [UploadUrlThrottle]

    @extend_schema(
        request=UploadUrlRequestSerializer,
        responses={200: UploadUrlResponseSerializer, 400: DetailSerializer},
        description="Step 1 of an upload: returns a presigned POST for uploading straight to S3. "
        "Send every returned field, then the file as the LAST form field named 'file'.",
    )
    def post(self, request):
        serializer = UploadUrlRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if services.avatar_count(request.user) >= settings.AVATAR_MAX_PER_USER:
            logger.info(
                "Avatar upload limit reached for user_id=%s",
                request.user.pk,
            )
            return _detail(services.limit_message(), status.HTTP_400_BAD_REQUEST)

        key, post = storage.create_presigned_upload(
            request.user.pk, uuid.uuid4(), serializer.validated_data["content_type"]
        )
        logger.info("Avatar upload initiated for user_id=%s", request.user.pk)
        return Response(
            {
                "url": post["url"],
                "fields": post["fields"],
                "upload_token": services.make_upload_token(request.user, key),
                "expires_in": storage.PRESIGN_EXPIRES,
                "max_bytes": settings.AVATAR_MAX_UPLOAD_BYTES,
            }
        )


class ConfirmUploadView(APIView):
    throttle_classes = [ConfirmThrottle]

    @extend_schema(
        request=ConfirmUploadSerializer,
        responses={201: AvatarSerializer, 200: AvatarSerializer, 400: DetailSerializer},
        description="Step 2 of an upload: validates and cleans the uploaded file and registers it. "
        "Returns 200 instead of 201 if the same picture was already uploaded. "
        "The first picture a user uploads becomes their current avatar.",
    )
    def post(self, request):
        serializer = ConfirmUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payload = services.read_upload_token(serializer.validated_data["upload_token"])
        own_prefix = f"uploads/{request.user.pk}/"
        if payload is None or payload["uid"] != str(request.user.pk) or not payload["key"].startswith(own_prefix):
            logger.info("Avatar upload confirmation rejected for user_id=%s", request.user.pk)
            return _detail(BAD_UPLOAD, status.HTTP_400_BAD_REQUEST)

        try:
            avatar, created = services.confirm_upload(request.user, payload["key"])
        except services.AvatarError as exc:
            logger.info(
                "Avatar upload confirmation failed for user_id=%s status=%s",
                request.user.pk,
                exc.status_code,
            )
            return _detail(exc.message, exc.status_code)

        request.user.refresh_from_db(fields=["current_avatar"])
        data = AvatarSerializer(avatar, context={"current_avatar_id": request.user.current_avatar_id}).data
        logger.info(
            "Avatar upload confirmed for user_id=%s avatar_id=%s created=%s",
            request.user.pk,
            avatar.pk,
            created,
        )
        return Response(data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class AvatarListView(APIView):
    @extend_schema(responses={200: AvatarListSerializer})
    def get(self, request):
        avatars = Avatar.objects.filter(user=request.user)
        context = {"current_avatar_id": request.user.current_avatar_id}
        return Response(
            {
                "results": AvatarSerializer(avatars, many=True, context=context).data,
                "current_avatar_id": request.user.current_avatar_id,
                "max_avatars": settings.AVATAR_MAX_PER_USER,
            }
        )


class AvatarDetailView(APIView):
    throttle_classes = [ManageThrottle]

    @extend_schema(responses={204: None, 404: DetailSerializer})
    def delete(self, request, pk):
        avatar = Avatar.objects.filter(pk=pk, user=request.user).select_related("user").first()
        if avatar is None:
            return _detail(NOT_FOUND, status.HTTP_404_NOT_FOUND)
        services.delete_avatar(avatar)
        logger.info(
            "Avatar deleted for user_id=%s avatar_id=%s",
            request.user.pk,
            avatar.pk,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class CurrentAvatarView(APIView):
    throttle_classes = [ManageThrottle]

    @extend_schema(
        request=CurrentAvatarRequestSerializer,
        responses={200: CurrentAvatarResponseSerializer, 404: DetailSerializer},
        description="Chooses the picture that other applications receive. Send null to go back to the default picture.",
    )
    def put(self, request):
        serializer = CurrentAvatarRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        avatar_id = serializer.validated_data["avatar_id"]

        avatar = None
        if avatar_id is not None:
            avatar = Avatar.objects.filter(pk=avatar_id, user=request.user).first()
            if avatar is None:
                logger.info(
                    "Current avatar update rejected: avatar not found for user_id=%s",
                    request.user.pk,
                )
                return _detail(NOT_FOUND, status.HTTP_404_NOT_FOUND)

        services.set_current_avatar(request.user, avatar)
        logger.info(
            "Current avatar updated for user_id=%s avatar_id=%s",
            request.user.pk,
            avatar.pk if avatar is not None else None,
        )
        return Response({"current_avatar_id": request.user.current_avatar_id})