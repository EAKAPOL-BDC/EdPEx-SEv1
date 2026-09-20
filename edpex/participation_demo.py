"""Opt-in disposable local UI demo. Never use for a deployed service."""
import os
from django.core.exceptions import ImproperlyConfigured
from .testing import *  # noqa

if DATABASES['default']['NAME'] != 'edpex_m1_f01_ui' or DATABASES['default']['PORT'] != '55469':
    raise ImproperlyConfigured('F01 demo requires its dedicated synthetic database on 55469.')
NEXORA_PARTICIPATION_ENABLED = True
NEXORA_PARTICIPATION_ALLOW_LIVE = False
NEXORA_UNLINKED_ACCESS_ENABLED = True
DEBUG = True
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
CSRF_COOKIE_NAME = 'nexora_f01_demo_csrf'
SESSION_COOKIE_NAME = 'nexora_f01_demo_staff'
SURVEY_SESSION_COOKIE_NAME = 'nexora_f01_demo_survey'
ROOT_URLCONF = 'edpex.participation_demo_urls'
# Interactive demo logins must not inherit the fast unit-test password hasher.
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.MD5PasswordHasher',  # legacy disposable fixtures only
]
