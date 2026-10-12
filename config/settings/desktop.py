"""Fixed loopback-only settings for the bundled desktop distribution."""
import os
from .base import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
CSRF_TRUSTED_ORIGINS = []
DATA_DIR = Path(os.environ['KWACART_DATA_DIR']).resolve()
SECRET_KEY = os.environ['SECRET_KEY']
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.sqlite3',
    'NAME': DATA_DIR / 'db.sqlite3',
    'OPTIONS': {'timeout': 20},
}}
MEDIA_ROOT = DATA_DIR / 'media'
STATIC_ROOT = DATA_DIR / 'static'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
SECURE_PROXY_SSL_HEADER = None
ROOT_URLCONF = 'desktop.urls'
MIDDLEWARE = MIDDLEWARE + ['desktop.setup.FirstAccountMiddleware']
# WhiteNoise serves only collected assets; user media is served explicitly.
WHITENOISE_USE_FINDERS = False
SETUP_TICKET = os.environ.get('KWACART_SETUP_TICKET', '')
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
