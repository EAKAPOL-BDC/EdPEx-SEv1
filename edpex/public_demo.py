"""Separate public-entry preview database. Does not change the active F01 demo."""
from django.core.exceptions import ImproperlyConfigured
from .testing import *  # noqa

if DATABASES['default']['NAME'] != 'edpex_m1_public_ui' or DATABASES['default']['PORT'] != '55469':
    raise ImproperlyConfigured('Public preview requires its separate synthetic database on 55469.')
NEXORA_PARTICIPATION_ENABLED = True
NEXORA_PARTICIPATION_ALLOW_LIVE = False
NEXORA_UNLINKED_ACCESS_ENABLED = True
NEXORA_PUBLIC_ASSESSMENTS_ENABLED = True
NEXORA_CONFIRM_IMPORTANT_ACTIONS = True
DEBUG = True
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
CSRF_COOKIE_NAME = 'nexora_public_preview_csrf'
SESSION_COOKIE_NAME = 'nexora_public_preview_staff'
SURVEY_SESSION_COOKIE_NAME = 'nexora_public_preview_survey'
PASSWORD_HASHERS = ['django.contrib.auth.hashers.PBKDF2PasswordHasher', 'django.contrib.auth.hashers.MD5PasswordHasher']
