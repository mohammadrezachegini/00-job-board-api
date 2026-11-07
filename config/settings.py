import os
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from pythonjsonlogger.core import RESERVED_ATTRS

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    """Read a setting from the environment. No default = required; empty counts as missing."""
    value = os.environ.get(name)
    if value is None or value == "":
        if default is None:
            raise ImproperlyConfigured(f"Missing required environment variable: {name}")
        return default
    return value


def env_bool(name, default=False):
    return env(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

AWS_REGION = env("AWS_REGION")
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME")
AWS_S3_REGION_NAME = AWS_REGION
AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL", "") or None
AWS_S3_PUBLIC_ENDPOINT_URL = env("AWS_S3_PUBLIC_ENDPOINT_URL", "") or AWS_S3_ENDPOINT_URL
AWS_DEFAULT_ACL = None
AWS_S3_FILE_OVERWRITE = False
AWS_QUERYSTRING_AUTH = True
RESUME_URL_EXPIRE_SECONDS = 300
JOB_LIST_CACHE_SECONDS = 60
AWS_SQS_ENDPOINT_URL = env("AWS_SQS_ENDPOINT_URL", "") or None
SQS_QUEUE_NAME = env("SQS_QUEUE_NAME")
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "Job Board <no-reply@jobboard.test>")
# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "django_prometheus",
    "drf_spectacular",
    "jobs",
]

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "config.urls"

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

WSGI_APPLICATION = "config.wsgi.application"


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django_prometheus.db.backends.postgresql",
        "NAME": env("POSTGRES_DB"),
        "USER": env("POSTGRES_USER"),
        "PASSWORD": env("POSTGRES_PASSWORD"),
        "HOST": env("POSTGRES_HOST"),
        "PORT": env("POSTGRES_PORT", "5432"),
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL"),
        "KEY_PREFIX": "jobboard",
        "TIMEOUT": 300,
        "OPTIONS": {
            "socket_connect_timeout": 1,
            "socket_timeout": 1,
        },
    }
}

# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = "static/"

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "jobs.User"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Job Board API",
    "DESCRIPTION": "Companies post jobs; candidates apply with a resume. JWT auth: get a token from /api/auth/token/ and click Authorize.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

STORAGES = {
    "default": {"BACKEND": "storages.backends.s3.S3Storage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

LOG_LEVEL = env("LOG_LEVEL", "INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.json.JsonFormatter",
            "fmt": "%(levelname)s %(name)s %(message)s",
            "rename_fields": {"levelname": "level", "name": "logger"},
            "timestamp": True,
            "reserved_attrs": [*RESERVED_ATTRS, "request"],
        },
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "json",
        },
    },
    "root": {"handlers": ["stdout"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"handlers": ["stdout"], "level": LOG_LEVEL, "propagate": False},
        "django.server": {"handlers": ["stdout"], "level": "INFO", "propagate": False},
        "botocore": {"level": "WARNING"},
        "urllib3": {"level": "WARNING"},
    },
}