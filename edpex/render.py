"""Production runtime using Render's assigned HTTPS address when not overridden."""
import os
import re

from django.core.exceptions import ImproperlyConfigured

if os.environ.get('RENDER') != 'true':
    raise ImproperlyConfigured('This runtime requires the Render hosting environment.')

if 'DJANGO_ALLOWED_HOSTS' not in os.environ or 'NEXORA_PUBLIC_ORIGIN' not in os.environ:
    hostname = os.environ.get('RENDER_EXTERNAL_HOSTNAME', '')
    public_url = os.environ.get('RENDER_EXTERNAL_URL', '')
    if (not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.onrender\.com', hostname)
            or public_url != f'https://{hostname}'):
        raise ImproperlyConfigured('Render must supply a matching service hostname and HTTPS URL.')
    os.environ.setdefault('DJANGO_ALLOWED_HOSTS', hostname)
    os.environ.setdefault('NEXORA_PUBLIC_ORIGIN', public_url)

# Retain every production check, including strong secrets, TLS and database profile.
from .production import *  # noqa: E402,F403
