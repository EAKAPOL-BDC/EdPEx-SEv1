"""Disposable PostgreSQL only. Cannot select the Supabase profile or a remote host."""
import os
from django.core.exceptions import ImproperlyConfigured

if os.environ.get('DJANGO_DATABASE_PROFILE', '').lower() == 'supabase':
    raise ImproperlyConfigured('M1 tests refuse the Supabase profile.')
if os.environ.get('POSTGRES_HOST', '127.0.0.1') not in {'127.0.0.1', 'localhost', '::1'}:
    raise ImproperlyConfigured('M1 tests require a loopback PostgreSQL host.')

from .settings import *  # noqa: E402,F403

name = os.environ.get('EDPEX_TEST_DB_NAME', 'edpex_m1_empty')
if not name.startswith('edpex_m1_') or not name.replace('_', '').isalnum():
    raise ImproperlyConfigured('Use a disposable database named edpex_m1_*.')
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql', 'HOST': '127.0.0.1',
    'PORT': os.environ.get('EDPEX_TEST_PORT', '55439'), 'NAME': name,
    'USER': os.environ.get('EDPEX_TEST_USER', 'postgres'),
    'PASSWORD': os.environ.get('EDPEX_TEST_PASSWORD', ''),
    'TEST': {'NAME': 'test_' + name},
}}
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
