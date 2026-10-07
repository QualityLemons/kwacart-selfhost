"""Production settings for the KwaCart Django application.

Inherits all defaults from ``config.settings.base`` and overrides values
that must differ in the live environment:
- ``DEBUG`` is forced to ``False``.
- ``SECRET_KEY``, ``ALLOWED_HOSTS``, and ``CSRF_TRUSTED_ORIGINS`` are read
  from environment variables so they can be rotated without a code deploy.
- HTTPS redirect is deliberately disabled because Replit's proxy terminates
  SSL before requests reach Gunicorn; the connection is already secure.
"""
import os
from urllib.parse import urlparse
from django.core.exceptions import ImproperlyConfigured
from .base import *  # noqa: F401,F403,F405

DEBUG = False

# In production SECRET_KEY must be set via the environment — an empty key will
# cause Django to raise ImproperlyConfigured on the first request.
SECRET_KEY = os.environ.get('SECRET_KEY', '')

# ALLOWED_HOSTS is read from a comma-separated environment variable so it can
# be updated without a code deploy.
_allowed = os.environ.get('ALLOWED_HOSTS', '')
ALLOWED_HOSTS = [h.strip() for h in _allowed.split(',') if h.strip()]

# CSRF_TRUSTED_ORIGINS is similarly env-driven; required when Django runs
# behind a proxy and requests arrive via a non-standard port or HTTPS scheme.
_csrf = os.environ.get('CSRF_TRUSTED_ORIGINS', '')
CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf.split(',') if o.strip()]

# Heroku (and Replit) terminate SSL at the proxy layer and forward the original
# protocol in the X-Forwarded-Proto header.  Telling Django to trust this header
# ensures request.build_absolute_uri() produces https:// URLs, which is required
# for QR codes to be recognised as links by phone cameras rather than search queries.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_PRELOAD = True
SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# Production data must use durable PostgreSQL storage.  Refuse to start rather
# than silently inheriting base.py's local SQLite database.
import dj_database_url as _dj_db_url  # noqa: E402
_db_url = os.environ.get('DATABASE_URL', '').strip()
if not _db_url:
    raise ImproperlyConfigured(
        'DATABASE_URL is required in production and must point to PostgreSQL.'
    )

_database = _dj_db_url.parse(_db_url, conn_max_age=600)
if _database.get('ENGINE') != 'django.db.backends.postgresql':
    raise ImproperlyConfigured(
        'DATABASE_URL must point to PostgreSQL in production; local SQLite is not durable.'
    )
DATABASES = {'default': _database}

# Django 4.2+ uses the STORAGES dict instead of the deprecated
# STATICFILES_STORAGE / DEFAULT_FILE_STORAGE string settings.
# Static files are served by WhiteNoise with content-hash filenames;
# production media must use Cloudinary because deployment filesystems are
# ephemeral.
_cloudinary_url = os.environ.get('CLOUDINARY_URL', '').strip()
_cloudinary = urlparse(_cloudinary_url)
if not (
    _cloudinary.scheme == 'cloudinary'
    and _cloudinary.username
    and _cloudinary.password
    and _cloudinary.hostname
):
    raise ImproperlyConfigured(
        'CLOUDINARY_URL is required in production and must contain a Cloudinary '
        'API key, secret, and cloud name.'
    )

STORAGES = {
    'default': {'BACKEND': 'cloudinary_storage.storage.RawMediaCloudinaryStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

# W008: Replit's proxy handles SSL termination; redirect at app level would loop
SILENCED_SYSTEM_CHECKS = ['security.W008']

# Replit's reverse proxy reaches the application over private networking.
# Operators can narrow these CIDRs further without a code change when their
# deployment exposes the exact ingress ranges.
RATE_LIMIT_TRUSTED_PROXY_NETWORKS = tuple(
    value.strip()
    for value in os.environ.get(
        'RATE_LIMIT_TRUSTED_PROXY_NETWORKS',
        '10.0.0.0/8,172.16.0.0/12,192.168.0.0/16',
    ).split(',')
    if value.strip()
)
