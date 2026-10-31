"""CDN invalidation (design doc, section 9.4).

Whenever what /avatar/{email_hash} returns may have changed (a new current picture, a deleted picture, an email
change, a deleted or deactivated account, ...), the code calls invalidate_email_hashes(). This module then asks the
CDN to forget every cached copy of that hash, whatever size or fallback parameters it was requested with.

The backend is chosen with settings.INVALIDATION_BACKEND:
    varnish     local development: a BAN request to the Varnish container (see cdn/default.vcl)
    cloudfront  hosted: CloudFront invalidation (Part B of the roadmap, not implemented yet)
    log         only writes a log line (useful for tests or when no CDN is running)

Two rules keep this safe:
- Nothing is sent until the database transaction has committed. Otherwise a request arriving between the ban and the
  commit could cache the OLD picture again (the Django admin deletes inside a transaction, for example).
- A failing CDN never breaks the request. Failed bans are retried in the background, and the cache lifetime
  (s-maxage) is the safety net if every retry fails.
"""
import logging
import re
import threading
import time

import requests
from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

BAN_TIMEOUT = 2  # seconds
RETRY_DELAYS = (2, 10, 30)  # seconds to wait before each background retry
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")


def invalidate_email_hashes(*email_hashes):
    """Asks the CDN to drop cached avatars for these email hashes (after the current transaction commits)."""
    hashes = list(dict.fromkeys(h for h in email_hashes if h))  # no empty values, no duplicates, keep order
    if hashes:
        transaction.on_commit(lambda: _invalidate(hashes))


def _invalidate(hashes):
    backend = (settings.INVALIDATION_BACKEND or "log").lower()

    if backend == "log":
        for email_hash in hashes:
            logger.info("CDN invalidation requested for /avatar/%s*", email_hash)
        return

    if backend == "cloudfront":
        logger.warning("INVALIDATION_BACKEND=cloudfront is not implemented yet (Part B); nothing was invalidated")
        return

    if backend != "varnish":
        logger.error("Unknown INVALIDATION_BACKEND %r; nothing was invalidated", backend)
        return

    if not settings.VARNISH_BAN_URL:
        logger.error("INVALIDATION_BACKEND=varnish but VARNISH_BAN_URL is not set; nothing was invalidated")
        return

    valid = []
    for email_hash in hashes:
        if _HASH_PATTERN.fullmatch(email_hash):
            valid.append(email_hash)
        else:
            logger.error("Refusing to invalidate a malformed email hash: %r", email_hash)

    failed = [email_hash for email_hash in valid if not _ban_varnish(email_hash)]
    if failed:
        _schedule_retry(failed)


def _ban_varnish(email_hash):
    """Sends one BAN request. Returns True on success. The regex covers every size and fallback variant."""
    url = settings.VARNISH_BAN_URL.rstrip("/") + "/"
    try:
        response = requests.request(
            "BAN", url, headers={"X-Ban-Pattern": f"^/avatar/{email_hash}"}, timeout=BAN_TIMEOUT
        )
    except requests.RequestException as exc:
        logger.warning("Varnish ban for /avatar/%s* failed: %s", email_hash, exc)
        return False
    if response.status_code != 200:
        logger.warning("Varnish ban for /avatar/%s* was refused: HTTP %s", email_hash, response.status_code)
        return False
    logger.info("Varnish ban sent for /avatar/%s*", email_hash)
    return True


def _schedule_retry(hashes):
    threading.Thread(target=_retry, args=(hashes,), daemon=True).start()


def _retry(hashes):
    pending = list(hashes)
    for delay in RETRY_DELAYS:
        time.sleep(delay)
        pending = [email_hash for email_hash in pending if not _ban_varnish(email_hash)]
        if not pending:
            return
    logger.error(
        "Giving up invalidating %s. The cached copies will expire on their own (s-maxage).", ", ".join(pending)
    )