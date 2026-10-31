"""JWT helpers: issuing tokens, the httpOnly refresh cookie, revocation, and the CSRF guard.

Design doc, section 6.1: the access token goes in the response body and is kept in memory by the frontend;
the refresh token only ever travels in an httpOnly cookie.
"""
from django.conf import settings
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken


def issue_tokens(user):
    """Returns (access_token, refresh_token) strings for a user."""
    refresh = RefreshToken.for_user(user)
    return str(refresh.access_token), str(refresh)


def _cookie_options():
    return {
        "path": settings.REFRESH_COOKIE_PATH,
        "secure": settings.REFRESH_COOKIE_SECURE,
        "httponly": True,
        "samesite": settings.REFRESH_COOKIE_SAMESITE,
    }


def set_refresh_cookie(response, refresh_token):
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        refresh_token,
        max_age=settings.REFRESH_COOKIE_MAX_AGE,
        **_cookie_options(),
    )


def clear_refresh_cookie(response):
    # Expire it with the same attributes it was set with, otherwise browsers may ignore the deletion.
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        "",
        max_age=0,
        expires="Thu, 01 Jan 1970 00:00:00 GMT",
        **_cookie_options(),
    )


def revoke_all_refresh_tokens(user):
    """Blacklist every outstanding refresh token of a user (password change/reset)."""
    pending = OutstandingToken.objects.filter(user=user).exclude(blacklistedtoken__isnull=False)
    BlacklistedToken.objects.bulk_create(
        [BlacklistedToken(token=token) for token in pending], ignore_conflicts=True
    )


def require_trusted_origin(request):
    """CSRF protection for endpoints that act on the refresh cookie (design doc, section 6.1).

    SameSite=None cookies are attached to requests from any site, so these endpoints require an allowed
    Origin header and a JSON content type (which cross-site HTML forms cannot send).
    """
    if request.headers.get("Origin", "") not in settings.CORS_ALLOWED_ORIGINS:
        raise PermissionDenied("Untrusted origin.")
    if not (request.content_type or "").startswith("application/json"):
        raise PermissionDenied("Content-Type must be application/json.")
