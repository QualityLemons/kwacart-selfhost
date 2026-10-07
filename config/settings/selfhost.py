"""Settings for a persistent, independently operated KwaCart instance.

No cloud database, media provider, payment service or Replit account is required.
Use a reverse proxy for HTTPS and media delivery on a public server.
"""
import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403,F401

DEBUG = False
SECRET_KEY = os.environ.get('SECRET_KEY', '')
if not SECRET_KEY or SECRET_KEY.startswith('django-insecure-'):
    raise ImproperlyConfigured('Set a private SECRET_KEY for this self-hosted instance.')

ALLOWED_HOSTS = [
    host.strip() for host in os.environ.get(
        'ALLOWED_HOSTS', 'localhost,127.0.0.1',
    ).split(',') if host.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip() for origin in os.environ.get(
        'CSRF_TRUSTED_ORIGINS', '',
    ).split(',') if origin.strip()
]

DATA_DIR = Path(os.environ.get('KWACART_DATA_DIR', str(BASE_DIR / 'data'))).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASES = {
    'default': dj_database_url.parse(
        os.environ.get('DATABASE_URL', f'sqlite:///{DATA_DIR / "db.sqlite3"}'),
        conn_max_age=60,
    ),
}
MEDIA_ROOT = DATA_DIR / 'media'
STATIC_ROOT = DATA_DIR / 'static'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

# Public instances should run behind HTTPS. Only trust this header when your
# reverse proxy overwrites incoming X-Forwarded-Proto headers.
if os.environ.get('KWACART_TRUST_PROXY_SSL') == '1':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = os.environ.get('KWACART_LOCAL_HTTP') != '1'
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SECURE_SSL_REDIRECT = SESSION_COOKIE_SECURE
