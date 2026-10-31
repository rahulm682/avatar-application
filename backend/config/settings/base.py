"""Settings shared by every environment. Environment-specific values live in dev.py and prod.py."""
import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # the backend/ folder


def env_bool(name, default=False):
    return os.environ.get(name, str(int(default))).strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]  # fail loudly if missing
DEBUG = False  # dev.py turns it on
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost")

# ---------------------------------------------------------------------------
# Applications and middleware
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",  # server-side refresh-token blacklist
    "drf_spectacular",
    # project apps
    "apps.core",
    "apps.accounts",
    "apps.avatars",
    "apps.moderation",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "apps.core.middleware.OriginVerifyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "avatar"),
        "USER": os.environ.get("POSTGRES_USER", "avatar"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        # Needed later if the database sits behind a transaction pooler (e.g. Supabase):
        # "DISABLE_SERVER_SIDE_CURSORS": True,
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Users and passwords (design doc, section 6)
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",  # Argon2id
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",  # fallback for any old hashes
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Lifetimes of the stateless signed tokens used in emailed links (seconds)
EMAIL_VERIFICATION_MAX_AGE = 60 * 60 * 24  # 24 hours
EMAIL_CHANGE_MAX_AGE = 60 * 60 * 24  # 24 hours
PASSWORD_RESET_TIMEOUT = 60 * 60  # 1 hour (used by Django's PasswordResetTokenGenerator)
UNVERIFIED_ACCOUNT_TTL_HOURS = 24  # unverified accounts older than this are cleaned up
SOFT_DELETE_RETENTION_DAYS = 30

# ---------------------------------------------------------------------------
# REST framework, JWT and OpenAPI
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Rate limits (design doc, section 11). Counters live in Django's cache; the default in-memory cache is
    # per process, so for several Gunicorn workers switch to a shared cache (database cache or Redis).
    "DEFAULT_THROTTLE_RATES": {
        "register": "5/hour",
        "login_ip": "20/min",
        "login_email": "5/min",
        "resend_ip": "10/hour",
        "resend_email": "3/hour",
        "reset_ip": "10/hour",
        "reset_email": "3/hour",
        "token_confirm": "20/hour",
        "refresh": "30/min",
        "sensitive_user": "10/hour",
    },
    # 0 = trust only the connecting address and ignore X-Forwarded-For (which clients can fake).
    # When running behind N trusted proxies, set N instead.
    "NUM_PROXIES": 0,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Avatar Service API",
    "DESCRIPTION": "Management API for the Avatar Service. The public avatar endpoint (/avatar/{email_hash}) is not part of this schema.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# The refresh token travels only in an httpOnly cookie (design doc, section 6.1).
# SECURE and SAMESITE differ per environment, so they are set in dev.py and prod.py.
REFRESH_COOKIE_NAME = os.environ.get("REFRESH_COOKIE_NAME", "refresh_token")
REFRESH_COOKIE_PATH = os.environ.get("REFRESH_COOKIE_PATH", "/api/auth/")
REFRESH_COOKIE_MAX_AGE = int(SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds())

# ---------------------------------------------------------------------------
# CORS and CSRF (design doc, section 10): exact origins, credentials allowed for the refresh cookie
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
CORS_ALLOW_CREDENTIALS = True
CORS_URLS_REGEX = r"^/api/.*$"
CORS_PREFLIGHT_MAX_AGE = 600
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS

# ---------------------------------------------------------------------------
# Origin lock (design doc, section 9.5): /avatar/* only accepted via the CDN. Empty = disabled.
# ---------------------------------------------------------------------------
ORIGIN_VERIFY_SECRET = os.environ.get("ORIGIN_VERIFY_SECRET", "")

# ---------------------------------------------------------------------------
# S3 (Silo locally, AWS S3 when hosted)
# ---------------------------------------------------------------------------
AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_STORAGE_BUCKET_NAME", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
AWS_S3_ENDPOINT_URL = os.environ.get("AWS_S3_ENDPOINT_URL", "") or None
AWS_S3_PUBLIC_ENDPOINT_URL = os.environ.get("AWS_S3_PUBLIC_ENDPOINT_URL", "") or None
AWS_S3_ADDRESSING_STYLE = os.environ.get("AWS_S3_ADDRESSING_STYLE", "auto")
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")

# ---------------------------------------------------------------------------
# Avatars (design doc, sections 8 and 9). Used from Step 4 onwards.
# ---------------------------------------------------------------------------
AVATAR_SIZES = (40, 80, 160, 320, 640)
AVATAR_DEFAULT_SIZE = 80
AVATAR_MAX_UPLOAD_BYTES = 5 * 1024 * 1024
AVATAR_MAX_PER_USER = 10
AVATAR_MAX_DIMENSION = 4096  # pixels, per side
AVATAR_CACHE_CONTROL = "public, max-age=300, s-maxage=86400"

# ---------------------------------------------------------------------------
# CDN invalidation (implemented in Step 6)
# ---------------------------------------------------------------------------
AVATAR_BASE_URL = os.environ.get("AVATAR_BASE_URL", "")
INVALIDATION_BACKEND = os.environ.get("INVALIDATION_BACKEND", "log")
VARNISH_BAN_URL = os.environ.get("VARNISH_BAN_URL", "")

# ---------------------------------------------------------------------------
# Email (Mailpit locally)
# ---------------------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "1025"))
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", False)
# Send emails from a background thread so the response time does not reveal whether an address is registered.
# Tests turn this off. A real task queue is a future improvement.
EMAIL_SEND_ASYNC = env_bool("EMAIL_SEND_ASYNC", True)
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "Avatar Service <no-reply@avatar.local>")
FRONTEND_BASE_URL = os.environ.get("FRONTEND_BASE_URL", "http://localhost:5173")

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = 'Asia/Kolkata'  
USE_I18N = False
USE_TZ = True

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

APP_LOG_LEVEL = os.environ.get("DJANGO_LOG_LEVEL", "INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,

    "formatters": {
        "standard": {
            "format": (
                "%(asctime)s | %(levelname)s | "
                "%(name)s | pid=%(process)d | %(message)s"
            ),
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },

    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "standard",
        },
        "console_errors": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
            "formatter": "standard",
            "level": "ERROR",
        },
    },

    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },

    "loggers": {
        # Application modules: apps.accounts, apps.avatars, etc.
        "apps": {
            "handlers": ["console"],
            "level": APP_LOG_LEVEL,
            "propagate": False,
        },

        # General Django framework logs.
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },

        # HTTP request errors and unhandled view exceptions.
        "django.request": {
            "handlers": ["console_errors"],
            "level": "ERROR",
            "propagate": False,
        },

        # Development and production server logs.
        "django.server": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },

        # Security-related warnings.
        "django.security": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },

        # Avoid verbose SQL query logging in normal operation.
        "django.db.backends": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
