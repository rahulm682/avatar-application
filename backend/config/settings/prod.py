"""Hosted settings. Used when DJANGO_SETTINGS_MODULE=config.settings.prod (the default for wsgi.py)."""
from .base import *  # noqa: F401,F403

DEBUG = False

# The API is served over HTTPS behind a proxy/CDN that sets X-Forwarded-Proto.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Cross-site refresh cookie (frontend and API on different domains). Needs HTTPS.
REFRESH_COOKIE_SECURE = True
REFRESH_COOKIE_SAMESITE = "None"
