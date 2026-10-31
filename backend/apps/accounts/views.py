"""Authentication and account endpoints (design doc, sections 6 and 7)."""
from functools import lru_cache

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import RefreshToken

from apps.core.cdn import invalidate_email_hashes

from . import mailer, tokens
from .authtokens import (
    clear_refresh_cookie,
    issue_tokens,
    require_trusted_origin,
    revoke_all_refresh_tokens,
    set_refresh_cookie,
)
from .emailhash import normalize_email
from .models import User
from .services import soft_delete_user
from .serializers import (
    AccessTokenSerializer,
    ChangePasswordSerializer,
    DeleteAccountSerializer,
    DetailSerializer,
    EmailChangeRequestSerializer,
    EmailSerializer,
    LoginResponseSerializer,
    LoginSerializer,
    PasswordResetConfirmSerializer,
    ProfileSerializer,
    RegisterSerializer,
    TokenSerializer,
)
from .throttles import (
    LoginEmailThrottle,
    LoginIPThrottle,
    RefreshThrottle,
    RegisterThrottle,
    ResendEmailThrottle,
    ResendIPThrottle,
    ResetEmailThrottle,
    ResetIPThrottle,
    SensitiveUserThrottle,
    TokenConfirmThrottle,
)

# Messages that are deliberately identical for every case, so responses reveal nothing about accounts.
SIGNUP_MESSAGE = "Check your email to finish creating your account."
RESEND_MESSAGE = "If that account is waiting for verification, a new link has been sent."
RESET_MESSAGE = "If that email belongs to an account, a reset link has been sent."
EMAIL_CHANGE_MESSAGE = "Check your new email address for a confirmation link."
BAD_LOGIN_MESSAGE = "Email or password is wrong."
BAD_LINK_MESSAGE = "This link is invalid or has expired."


def detail(message, http_status=status.HTTP_200_OK):
    return Response({"detail": message}, status=http_status)


@lru_cache(maxsize=1)
def _dummy_password_hash():
    return make_password("dummy-password-used-for-constant-time-login")


def _password_errors(password, user):
    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        return list(exc.messages)
    return None


class PublicView(APIView):
    """Base for endpoints that need no login. Ignoring any Authorization header avoids spurious 401s."""

    authentication_classes = []
    permission_classes = [AllowAny]


# ---------------------------------------------------------------------------
# Sign-up and verification
# ---------------------------------------------------------------------------
class RegisterView(PublicView):
    throttle_classes = [RegisterThrottle]

    @extend_schema(request=RegisterSerializer, responses={202: DetailSerializer}, auth=[])
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        # Hash once in every branch, so response time does not reveal whether the email is registered.
        hashed_password = make_password(serializer.validated_data["password"])

        existing = User.objects.filter(email=email).first()
        if existing is not None and (existing.is_email_verified or existing.is_staff):
            mailer.send_registration_notice(email)
        else:
            try:
                with transaction.atomic():
                    if existing is not None:
                        existing.delete()  # a stale unverified sign-up never blocks the real owner
                    user = User(email=email, password=hashed_password)
                    user.save()
            except IntegrityError:
                mailer.send_registration_notice(email)  # lost a race with another sign-up
            else:
                mailer.send_verification_email(user)
        return detail(SIGNUP_MESSAGE, status.HTTP_202_ACCEPTED)


class VerifyEmailView(PublicView):
    throttle_classes = [TokenConfirmThrottle]

    @extend_schema(request=TokenSerializer, responses={200: DetailSerializer, 400: DetailSerializer}, auth=[])
    def post(self, request):
        serializer = TokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = tokens.read_verification_token(serializer.validated_data["token"])
        user = User.objects.filter(pk=payload["uid"]).first() if payload else None
        if user is None or user.email != payload["email"]:
            return detail(BAD_LINK_MESSAGE, status.HTTP_400_BAD_REQUEST)
        if user.email_verified_at is None:
            user.email_verified_at = timezone.now()
            user.save(update_fields=["email_verified_at", "updated_at"])
        return detail("Email verified. You can log in now.")


class ResendVerificationView(PublicView):
    throttle_classes = [ResendIPThrottle, ResendEmailThrottle]

    @extend_schema(request=EmailSerializer, responses={202: DetailSerializer}, auth=[])
    def post(self, request):
        serializer = EmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(
            email=serializer.validated_data["email"], email_verified_at__isnull=True, is_active=True
        ).first()
        if user is not None:
            mailer.send_verification_email(user)
        return detail(RESEND_MESSAGE, status.HTTP_202_ACCEPTED)


# ---------------------------------------------------------------------------
# Login, refresh, logout
# ---------------------------------------------------------------------------
class LoginView(PublicView):
    throttle_classes = [LoginIPThrottle, LoginEmailThrottle]

    @extend_schema(
        request=LoginSerializer,
        responses={200: LoginResponseSerializer, 401: DetailSerializer},
        auth=[],
        description="Returns the access token in the body and sets the refresh token as an httpOnly cookie.",
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = normalize_email(serializer.validated_data["email"])
        password = serializer.validated_data["password"]

        user = User.objects.filter(email=email).first()
        # Always verify a hash (a dummy one for unknown emails) so timing does not reveal registered emails.
        password_ok = check_password(password, user.password if user else _dummy_password_hash())
        if not (user and password_ok and user.is_active and user.is_email_verified):
            # Same answer for: unknown email, wrong password, and unverified account.
            return detail(BAD_LOGIN_MESSAGE, status.HTTP_401_UNAUTHORIZED)

        access, refresh = issue_tokens(user)
        response = Response({"access": access, "user": ProfileSerializer(user).data})
        set_refresh_cookie(response, refresh)
        return response


class RefreshView(PublicView):
    throttle_classes = [RefreshThrottle]

    @extend_schema(
        request=None,
        responses={200: AccessTokenSerializer, 401: DetailSerializer, 403: DetailSerializer},
        auth=[],
        description="Reads the refresh cookie, rotates it, and returns a new access token. "
        "Requires an allowed Origin header and Content-Type: application/json.",
    )
    def post(self, request):
        require_trusted_origin(request)
        raw_token = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if not raw_token:
            return detail("Not logged in.", status.HTTP_401_UNAUTHORIZED)

        try:
            old_refresh = RefreshToken(raw_token)  # checks signature, expiry and the blacklist
            user = User.objects.filter(pk=old_refresh[jwt_settings.USER_ID_CLAIM]).first()
        except TokenError:
            return _logged_out_response()

        if user is None or not user.is_active or not user.is_email_verified:
            return _logged_out_response()

        access, new_refresh = issue_tokens(user)
        old_refresh.blacklist()  # rotation: each refresh token works exactly once
        response = Response({"access": access})
        set_refresh_cookie(response, new_refresh)
        return response


class LogoutView(PublicView):
    throttle_classes = [RefreshThrottle]

    @extend_schema(request=None, responses={204: None, 403: DetailSerializer}, auth=[])
    def post(self, request):
        require_trusted_origin(request)
        raw_token = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if raw_token:
            try:
                RefreshToken(raw_token).blacklist()
            except TokenError:
                pass  # already invalid: nothing to revoke
        response = Response(status=status.HTTP_204_NO_CONTENT)
        clear_refresh_cookie(response)
        return response


def _logged_out_response():
    response = detail("Session expired. Please log in again.", status.HTTP_401_UNAUTHORIZED)
    clear_refresh_cookie(response)
    return response


# ---------------------------------------------------------------------------
# Password reset and change
# ---------------------------------------------------------------------------
class PasswordResetRequestView(PublicView):
    throttle_classes = [ResetIPThrottle, ResetEmailThrottle]

    @extend_schema(request=EmailSerializer, responses={202: DetailSerializer}, auth=[])
    def post(self, request):
        serializer = EmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(email=serializer.validated_data["email"]).first()
        if user is not None and user.is_active and user.is_email_verified:
            mailer.send_password_reset_email(user)
        return detail(RESET_MESSAGE, status.HTTP_202_ACCEPTED)


class PasswordResetConfirmView(PublicView):
    throttle_classes = [TokenConfirmThrottle]

    @extend_schema(
        request=PasswordResetConfirmSerializer,
        responses={200: DetailSerializer, 400: DetailSerializer},
        auth=[],
    )
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = tokens.user_from_uid(data["uid"])
        if user is None or not tokens.check_password_reset_token(user, data["token"]):
            return detail(BAD_LINK_MESSAGE, status.HTTP_400_BAD_REQUEST)

        errors = _password_errors(data["new_password"], user)
        if errors:
            return Response({"new_password": errors}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(data["new_password"])
        user.save(update_fields=["password", "updated_at"])
        revoke_all_refresh_tokens(user)  # every device must log in again
        return detail("Password updated. You can log in now.")


class ChangePasswordView(APIView):
    throttle_classes = [SensitiveUserThrottle]

    @extend_schema(
        request=ChangePasswordSerializer,
        responses={200: AccessTokenSerializer, 400: DetailSerializer},
        description="Changes the password, revokes all sessions, and starts a fresh session for this device.",
    )
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = request.user

        if not user.check_password(data["current_password"]):
            return detail("Current password is incorrect.", status.HTTP_400_BAD_REQUEST)
        errors = _password_errors(data["new_password"], user)
        if errors:
            return Response({"new_password": errors}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(data["new_password"])
        user.save(update_fields=["password", "updated_at"])
        revoke_all_refresh_tokens(user)

        access, refresh = issue_tokens(user)
        response = Response({"access": access})
        set_refresh_cookie(response, refresh)
        return response


# ---------------------------------------------------------------------------
# Email change
# ---------------------------------------------------------------------------
class EmailChangeRequestView(APIView):
    throttle_classes = [SensitiveUserThrottle]

    @extend_schema(request=EmailChangeRequestSerializer, responses={202: DetailSerializer, 400: DetailSerializer})
    def post(self, request):
        serializer = EmailChangeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_email = serializer.validated_data["new_email"]
        user = request.user

        if not user.check_password(serializer.validated_data["password"]):
            return detail("Password is incorrect.", status.HTTP_400_BAD_REQUEST)
        if new_email == user.email:
            return detail("That is already your email address.", status.HTTP_400_BAD_REQUEST)

        other = User.objects.filter(email=new_email).first()
        if other is not None and (other.is_email_verified or other.is_staff):
            # Same response as success, so this cannot be used to discover which emails are registered.
            mailer.send_email_in_use_notice(new_email)
        else:
            mailer.send_email_change_email(user, new_email)
        return detail(EMAIL_CHANGE_MESSAGE, status.HTTP_202_ACCEPTED)


class EmailChangeConfirmView(PublicView):
    throttle_classes = [TokenConfirmThrottle]

    @extend_schema(request=TokenSerializer, responses={200: DetailSerializer, 400: DetailSerializer}, auth=[])
    def post(self, request):
        serializer = TokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = tokens.read_email_change_token(serializer.validated_data["token"])
        user = User.objects.filter(pk=payload["uid"]).first() if payload else None
        # The link only works while the account still has the email it was issued for.
        if user is None or user.email_hash != payload["old_email_hash"]:
            return detail(BAD_LINK_MESSAGE, status.HTTP_400_BAD_REQUEST)

        new_email = payload["new_email"]
        old_hash = user.email_hash
        try:
            with transaction.atomic():
                other = User.objects.filter(email=new_email).first()
                if other is not None:
                    if other.is_email_verified or other.is_staff:
                        return detail(BAD_LINK_MESSAGE, status.HTTP_400_BAD_REQUEST)
                    other.delete()  # stale unverified sign-up
                user.email = new_email
                user.email_verified_at = timezone.now()  # clicking the link proves ownership of the new address
                user.save()  # recomputes email_hash
        except IntegrityError:
            return detail(BAD_LINK_MESSAGE, status.HTTP_400_BAD_REQUEST)

        invalidate_email_hashes(old_hash, user.email_hash)
        return detail("Email address updated.")


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------
class MeView(APIView):
    def get_throttles(self):
        return [SensitiveUserThrottle()] if self.request.method == "DELETE" else []

    @extend_schema(responses={200: ProfileSerializer})
    def get(self, request):
        return Response(ProfileSerializer(request.user).data)

    @extend_schema(request=ProfileSerializer, responses={200: ProfileSerializer})
    def patch(self, request):
        serializer = ProfileSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @extend_schema(request=DeleteAccountSerializer, responses={204: None, 400: DetailSerializer})
    def delete(self, request):
        serializer = DeleteAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        if not user.check_password(serializer.validated_data["password"]):
            return detail("Password is incorrect.", status.HTTP_400_BAD_REQUEST)

        soft_delete_user(user)  # hidden at once; permanently removed after the retention period

        response = Response(status=status.HTTP_204_NO_CONTENT)
        clear_refresh_cookie(response)
        return response