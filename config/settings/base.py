"""
Base settings shared by all environments.

Settings are split across three files:
- base.py (this file)   — values common to development, testing, and production.
- production.py         — production-only overrides (database, ALLOWED_HOSTS,
                          static file storage, HTTPS enforcement).
- test.py               — test runner overrides when needed.

Per-environment files import from base.py via ``from .base import *``, then
override specific values.  The active settings module is selected by the
``DJANGO_SETTINGS_MODULE`` environment variable.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# KwaCart's downloadable/self-hosted edition has no payment requirement.
# Keep historical billing data intact; legacy billing code is disabled.
BILLING_ENABLED = False
KWACART_SOURCE_URL = os.environ.get(
    'KWACART_SOURCE_URL', 'https://github.com/QualityLemons/kwacart-selfhost',
)

# SECRET_KEY must be set via the SECRET_KEY environment variable in production.
# The hard-coded fallback is intentionally broken-looking so it is never
# mistakenly used outside a local development environment.
SECRET_KEY = os.environ.get(
    'SECRET_KEY',
    'django-insecure-dev-key-replace-in-production-0000000000000000000000000000'
)

# INSTALLED_APPS is split into Django built-ins (top) and project apps
# (bottom).  Django's built-ins are listed first so their migrations are
# applied before any app that depends on contrib.auth or contrib.contenttypes.
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Project apps — ordered so that migrations do not circular-import.
    # accounts must come before archive and tools because both apps define
    # ForeignKey relationships to the custom User model.
    'accounts',
    'academy',
    'archive',
    'tools',

    # Cloudinary media storage — must come after project apps so that
    # the custom storage backend can override DEFAULT_FILE_STORAGE.
    'cloudinary',
    'cloudinary_storage',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # WhiteNoise must come immediately after SecurityMiddleware so it can serve
    # compressed static files before any other middleware runs.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'accounts.middleware.PaidWorkspaceMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'archive.views.staff_feedback_context',
                'config.context_processors.product',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database — single configuration point for the entire project.
# SQLite is used for development and testing.  To switch to PostgreSQL in any
# environment, set a DATABASE_URL environment variable; production.py detects
# it and overrides this block via dj-database-url.  No other file defines
# DATABASES, so this is the only location that needs to change.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
# USE_TZ=True activates timezone-aware datetimes throughout.  The timer widget
# serialises server_now via timezone.now().isoformat(), which requires this.
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
# Only add 'static/' to STATICFILES_DIRS when it exists.  Missing the directory
# entirely is valid in a freshly-cloned environment before assets are generated.
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Reject oversized request bodies before Django spends memory parsing them.
# Uploaded files larger than the in-memory threshold are streamed to a
# temporary file, while the overall request limit caps multipart form data.
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# Only these direct reverse-proxy networks may supply client-address chains to
# the rate limiter. Local development uses loopback; production overrides this
# with the deployment proxy networks.
RATE_LIMIT_TRUSTED_PROXY_NETWORKS = (
    '127.0.0.0/8',
    '::1/128',
)

# Data lifecycle defaults.  The cleanup_retention command is deliberately a
# dry-run unless --delete is supplied.  "none" retains a category indefinitely.


def _retention_days(name, default):
    value = os.environ.get(name, str(default)).strip()
    return None if value.lower() == 'none' else int(value)


RETENTION_TOOL_DATA_DAYS = _retention_days('RETENTION_TOOL_DATA_DAYS', 365)
RETENTION_AUDIT_LOG_DAYS = _retention_days('RETENTION_AUDIT_LOG_DAYS', 730)
RETENTION_FEEDBACK_DAYS = _retention_days('RETENTION_FEEDBACK_DAYS', 730)
RETENTION_RATE_LIMIT_DAYS = _retention_days('RETENTION_RATE_LIMIT_DAYS', 7)
RETENTION_DRAWING_ORPHAN_GRACE_HOURS = int(
    os.environ.get('RETENTION_DRAWING_ORPHAN_GRACE_HOURS', '24')
)
RETENTION_CLEANUP_BATCH_SIZE = int(
    os.environ.get('RETENTION_CLEANUP_BATCH_SIZE', '100')
)

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# AUTH_USER_MODEL swaps Django's built-in User for the custom model defined
# in accounts/models.py.  Must be set before the first migration is run and
# cannot be changed after migrations have been applied without resetting the DB.
AUTH_USER_MODEL = 'accounts.User'
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'tools:catalog'
LOGOUT_REDIRECT_URL = 'accounts:login'

# These IDs are a fallback for deployments where Stripe metadata listing is
# temporarily unavailable.  Normal checkout lookup uses the Stripe catalog
# metadata, so the catalog remains the source of truth.
STRIPE_PRICE_IDS = {
    'solo': {
        'month': 'price_1UA7id7EuiGGkEAFaE3n5bLG',
        'year': 'price_1UA7ie7EuiGGkEAFghTFsz2M',
    },
    'organisation': {
        'month': 'price_1UA7if7EuiGGkEAFFvwQWcsx',
        'year': 'price_1UA7if7EuiGGkEAFGXEVnZV5',
    },
}
