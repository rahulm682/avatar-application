"""Hosted settings. Used when DJANGO_SETTINGS_MODULE=config.settings.prod (the default for wsgi.py)."""
from .base import *  # noqa: F401,F403

DEBUG = False

# --------------------------------------------------
# Hosts
# --------------------------------------------------

# Set DJANGO_ALLOWED_HOSTS in the production environment.
# Example: avatar.example.com,www.avatar.example.com

# --------------------------------------------------
# HTTPS and reverse proxy
# --------------------------------------------------

# Nginx terminates HTTPS and forwards this header to Django.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Redirect HTTP requests to HTTPS.
SECURE_SSL_REDIRECT = True

# Cookies must only travel over HTTPS.
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
REFRESH_COOKIE_SECURE = True

# Frontend and API share the same site.
REFRESH_COOKIE_SAMESITE = "Lax"

# Additional browser security headers.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# Enable HSTS only after HTTPS is confirmed working.
# Start with a short duration and increase it later.
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False