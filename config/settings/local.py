import os
from .base import *  # noqa

DEBUG = os.environ.get('DEBUG', 'True') == 'True'

_replit_domains = os.environ.get('REPLIT_DOMAINS', '')
if _replit_domains:
    _domain_list = _replit_domains.split(',')
    ALLOWED_HOSTS = _domain_list + ['localhost', '127.0.0.1']
    CSRF_TRUSTED_ORIGINS = ['https://' + d for d in _domain_list]
else:
    ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0']
    CSRF_TRUSTED_ORIGINS = ['http://localhost:5000', 'http://127.0.0.1:5000']
