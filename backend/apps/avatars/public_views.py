"""The public avatar endpoint: GET /avatar/{email_hash}?s=160&d=identicon  (design doc, section 9).

No authentication. In every environment it is meant to be reached through the CDN, which caches the answer.
Everything the CDN needs is in the response headers (Cache-Control, ETag).
"""
import logging

from django.conf import settings
from django.http import HttpResponse
from django.utils.cache import get_conditional_response
from django.utils.http import quote_etag
from django.views.decorators.http import require_safe

from apps.accounts.models import User

from . import fallbacks, imaging, storage

logger = logging.getLogger(__name__)

FALLBACK_DEFAULT = "default"
FALLBACK_IDENTICON = "identicon"
FALLBACK_404 = "404"
NOT_FOUND_CACHE_CONTROL = "public, max-age=60, s-maxage=60"  # a "no picture" answer is cached only briefly
DERIVED_READ_LIMIT = 5 * 1024 * 1024
ORIGINAL_READ_LIMIT = 32 * 1024 * 1024


def snap_size(raw, sizes, default):
    """Rounds the requested size UP to the nearest supported size (capped at the largest). Junk gives the default."""
    try:
        requested = int(raw)
    except (TypeError, ValueError):
        return default
    if requested <= 0:
        return default
    for size in sorted(sizes):
        if size >= requested:
            return size
    return max(sizes)


def parse_fallback(raw):
    return raw if raw in (FALLBACK_DEFAULT, FALLBACK_IDENTICON, FALLBACK_404) else FALLBACK_DEFAULT


def find_current_avatar(email_hash):
    """The one place that decides which picture a hash resolves to. Returns an Avatar or None.

    Only active users with a verified email are served. Soft-deleted accounts are invisible to User.objects, and a
    soft-deleted picture is never served.
    """
    user = (
        User.objects.filter(email_hash=email_hash, is_active=True, email_verified_at__isnull=False)
        .select_related("current_avatar")
        .first()
    )
    avatar = user.current_avatar if user is not None else None
    return None if avatar is None or avatar.is_deleted else avatar


def avatar_bytes(avatar, size):
    """The avatar at the requested size. Uses the derived/ copy if present; otherwise makes and stores it."""
    derived = storage.derived_key(avatar.pk, size)
    data = storage.try_read_object(derived, DERIVED_READ_LIMIT)
    if data is not None:
        return data

    original = storage.try_read_object(avatar.storage_key, ORIGINAL_READ_LIMIT)
    if original is None:
        logger.error("Original file missing for avatar %s (%s)", avatar.pk, avatar.storage_key)
        return None
    data = imaging.make_square(original, size)
    try:
        storage.put_object(derived, data, "image/webp")
    except Exception:  # noqa: BLE001 - still serve the image; the next request will try again
        logger.exception("Could not store derived image %s", derived)
    return data


def _finish(response, etag, cache_control):
    """Headers every avatar response carries, including 304s."""
    response["Cache-Control"] = cache_control
    if etag:
        response["ETag"] = etag
    response["Access-Control-Allow-Origin"] = "*"  # lets any site read the image via fetch/canvas
    response["Cross-Origin-Resource-Policy"] = "cross-origin"
    return response


def _image_response(request, etag, make_body):
    """Answers 304 if the client already has this exact image, otherwise 200 with the body make_body() returns."""
    not_modified = get_conditional_response(request, etag=etag)
    if not_modified is not None:
        return _finish(not_modified, etag, settings.AVATAR_CACHE_CONTROL)
    body = make_body()
    if body is None:
        return None
    return _finish(HttpResponse(body, content_type="image/webp"), etag, settings.AVATAR_CACHE_CONTROL)


@require_safe
def public_avatar(request, email_hash):
    size = snap_size(request.GET.get("s"), settings.AVATAR_SIZES, settings.AVATAR_DEFAULT_SIZE)
    fallback = parse_fallback(request.GET.get("d"))

    try:
        avatar = find_current_avatar(email_hash)
        if avatar is not None:
            etag = quote_etag(f"{avatar.content_hash[:32]}-{size}")
            response = _image_response(request, etag, lambda: avatar_bytes(avatar, size))
            if response is not None:
                return response
            # The files are missing although the database says there is a picture: log (done) and fall back.
    except Exception:  # noqa: BLE001 - e.g. S3 is unreachable
        logger.exception("Could not serve avatar %s", email_hash)
        # Never cache this: answering with a fallback here would hide the picture for a day.
        response = HttpResponse("Temporarily unavailable", status=503, content_type="text/plain")
        response["Cache-Control"] = "no-store"
        response["Retry-After"] = "5"
        return response

    # ---- no picture: the user has none, or the hash is unknown (both look exactly the same) ----
    if fallback == FALLBACK_404:
        return _finish(
            HttpResponse("Not found", status=404, content_type="text/plain"), None, NOT_FOUND_CACHE_CONTROL
        )
    if fallback == FALLBACK_IDENTICON:
        etag = quote_etag(f"identicon-{email_hash[:16]}-{size}")
        return _image_response(request, etag, lambda: fallbacks.identicon(email_hash, size))
    etag = quote_etag(f"default-{fallbacks.DEFAULT_VERSION}-{size}")
    return _image_response(request, etag, lambda: fallbacks.default_image(size))