"""Per-user rate limits for avatar endpoints (design doc, section 11). Rates are set on the classes."""
from rest_framework.throttling import SimpleRateThrottle


class _UserThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        user = getattr(request, "user", None)
        ident = user.pk if user is not None and user.is_authenticated else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class UploadUrlThrottle(_UserThrottle):
    scope = "avatar_upload_url"
    rate = "20/hour"


class ConfirmThrottle(_UserThrottle):
    scope = "avatar_confirm"
    rate = "30/hour"


class ManageThrottle(_UserThrottle):
    """Deleting pictures and choosing the current one."""

    scope = "avatar_manage"
    rate = "60/hour"