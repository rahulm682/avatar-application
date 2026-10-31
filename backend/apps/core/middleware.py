import hmac
import hmac
import logging

from django.conf import settings
from django.http import HttpResponse

logger = logging.getLogger(__name__)

class OriginVerifyMiddleware:
    """Rejects /avatar/* requests that did not come through the CDN (design doc, section 9.5).

    The CDN adds the secret header X-Origin-Verify. If ORIGIN_VERIFY_SECRET is empty, the lock is disabled.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        secret = getattr(settings, "ORIGIN_VERIFY_SECRET", "")
        if secret and request.path.startswith("/avatar/"):
            supplied = request.headers.get("X-Origin-Verify", "")
            if not hmac.compare_digest(supplied.encode(), secret.encode()):
                logger.warning("Public avatar request rejected: origin verification failed")
                return HttpResponse("Forbidden", status=403, content_type="text/plain")
        return self.get_response(request)
