"""POST /api/reports/: anyone can report a picture (design doc, sections 7 and 11)."""
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from apps.accounts.serializers import DetailSerializer
from apps.avatars.public_views import find_current_avatar

from .models import Report
from .serializers import ReportSerializer

REPORT_MESSAGE = "Thank you. A moderator will review this picture."


class ReportThrottle(SimpleRateThrottle):
    scope = "report"
    rate = "10/hour"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class ReportView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ReportThrottle]

    @extend_schema(
        request=ReportSerializer,
        responses={202: DetailSerializer, 400: DetailSerializer},
        auth=[],
        description="Reports the picture that is currently served for an email hash. The answer is the same whether "
        "or not there is a picture, so this cannot be used to find out which emails are registered.",
    )
    def post(self, request):
        serializer = ReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email_hash = serializer.validated_data["email_hash"]

        avatar = find_current_avatar(email_hash)
        if avatar is not None:
            Report.objects.create(
                avatar_uuid=avatar.pk,
                user_uuid=avatar.user_id,
                email_hash=email_hash,
                reason=serializer.validated_data["reason"],
            )
        return Response({"detail": REPORT_MESSAGE}, status=status.HTTP_202_ACCEPTED)