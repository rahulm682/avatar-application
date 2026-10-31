"""Local development settings (Docker Compose)."""
import os
from .base import *  # noqa: F401,F403
from .base import env_bool

DEBUG = env_bool("DJANGO_DEBUG", True)

# Plain HTTP on localhost: a Secure cookie would not be stored. Different ports on localhost
# count as the same site, so Lax works. The real SameSite=None; Secure setup is tested after deployment.
REFRESH_COOKIE_SECURE = False
REFRESH_COOKIE_SAMESITE = "Lax"

# More detailed application logs during development.
LOGGING["loggers"]["apps"]["level"] = os.environ.get(
    "DJANGO_LOG_LEVEL", "DEBUG"
).upper()
