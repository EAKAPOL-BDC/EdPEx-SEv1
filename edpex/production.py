"""Production runtime. Requires explicit secrets, database and HTTPS origin."""
from urllib.parse import urlsplit

from .settings import *  # noqa: F403

if not PRODUCTION:  # noqa: F405
    raise ImproperlyConfigured('Set NEXORA_ENVIRONMENT=production for this runtime.')  # noqa: F405
if os.getenv('DJANGO_DATABASE_PROFILE', '').lower() != 'supabase':  # noqa: F405
    raise ImproperlyConfigured('Production requires the explicit Supabase database profile.')  # noqa: F405

origin = urlsplit(NEXORA_PUBLIC_ORIGIN)  # noqa: F405
if (origin.scheme != 'https' or not origin.hostname or origin.username or origin.password
        or origin.path not in {'', '/'} or origin.query or origin.fragment
        or origin.hostname not in ALLOWED_HOSTS):  # noqa: F405
    raise ImproperlyConfigured('NEXORA_PUBLIC_ORIGIN must be an HTTPS origin matching DJANGO_ALLOWED_HOSTS.')  # noqa: F405
CSRF_TRUSTED_ORIGINS = [f'https://{origin.netloc}']
MIDDLEWARE = [MIDDLEWARE[0], 'whitenoise.middleware.WhiteNoiseMiddleware', *MIDDLEWARE[1:]]  # noqa: F405
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
# Small pooler-backed deployments must not pin a connection per idle worker.
DATABASES['default']['CONN_MAX_AGE'] = 0  # noqa: F405
