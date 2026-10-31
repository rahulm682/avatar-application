"""Rate limits (design doc, section 11). Rates are configured in REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']."""
import hashlib

from rest_framework.throttling import SimpleRateThrottle

from .emailhash import normalize_email


class _IPThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class _EmailThrottle(SimpleRateThrottle):
    """Limits by the email address in the request body (stored hashed in the cache)."""

    def get_cache_key(self, request, view):
        data = request.data if isinstance(request.data, dict) else {}
        email = normalize_email(str(data.get("email", "")))
        if not email:
            return None  # nothing to limit on; validation will reject the request anyway
        ident = hashlib.sha256(email.encode("utf-8")).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": ident}


class RegisterThrottle(_IPThrottle):
    scope = "register"


class LoginIPThrottle(_IPThrottle):
    scope = "login_ip"


class LoginEmailThrottle(_EmailThrottle):
    scope = "login_email"


class ResendIPThrottle(_IPThrottle):
    scope = "resend_ip"


class ResendEmailThrottle(_EmailThrottle):
    scope = "resend_email"


class ResetIPThrottle(_IPThrottle):
    scope = "reset_ip"


class ResetEmailThrottle(_EmailThrottle):
    scope = "reset_email"


class TokenConfirmThrottle(_IPThrottle):
    scope = "token_confirm"


class RefreshThrottle(_IPThrottle):
    scope = "refresh"


class SensitiveUserThrottle(SimpleRateThrottle):
    """Per logged-in user: change password, change email, delete account."""

    scope = "sensitive_user"

    def get_cache_key(self, request, view):
        user = getattr(request, "user", None)
        ident = user.pk if user is not None and user.is_authenticated else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}
