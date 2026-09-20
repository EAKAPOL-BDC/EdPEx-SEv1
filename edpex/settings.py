"""Django settings for EdPEx (System Blueprint 1.2 / Instruments 1.1)."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "development-only-not-for-production")
DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [host for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host]
NEXORA_ENVIRONMENT = os.getenv('NEXORA_ENVIRONMENT', 'development').lower()
if NEXORA_ENVIRONMENT not in {'development', 'production'}:
    raise ImproperlyConfigured('NEXORA_ENVIRONMENT must be development or production.')
PRODUCTION = NEXORA_ENVIRONMENT == 'production'
if PRODUCTION:
    if DEBUG or len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith('development-'):
        raise ImproperlyConfigured('Production requires DEBUG=false and a strong, private DJANGO_SECRET_KEY.')
    if not os.getenv('DJANGO_ALLOWED_HOSTS') or '*' in ALLOWED_HOSTS:
        raise ImproperlyConfigured('Production requires explicit DJANGO_ALLOWED_HOSTS; wildcard hosts are not allowed.')

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 15}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = PRODUCTION
CSRF_COOKIE_SECURE = PRODUCTION
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SECURE_SSL_REDIRECT = PRODUCTION
SECURE_HSTS_SECONDS = 3600 if PRODUCTION else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
STATIC_ROOT = BASE_DIR / 'staticfiles'
# Enable only behind a proxy that strips client-supplied forwarding headers.
if os.getenv('NEXORA_TRUST_HTTPS_PROXY') == 'true':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts",
    "apps.catalog",
    "apps.rounds",
    "apps.auditlog",
    "apps.calculations",
    "apps.selfassessments",
    "apps.surveys",
    "apps.participation",
    "apps.leadership",
    "apps.governance",
    "apps.manuals",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.accounts.security.HealthMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.security.PortalSecurityMiddleware",
    "apps.accounts.middleware.PortalLanguageMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.governance.confirmation.ConfirmationMiddleware",
]
ROOT_URLCONF = "edpex.urls"
# Staged rollout: the new proof APIs are unavailable until explicitly enabled.
# Test-realm proofs are never acceptable to live-realm verifier clients.
NEXORA_PARTICIPATION_ENABLED = os.getenv('NEXORA_PARTICIPATION_ENABLED', 'false').lower() == 'true'
NEXORA_PARTICIPATION_ALLOW_LIVE = os.getenv('NEXORA_PARTICIPATION_ALLOW_LIVE', 'false').lower() == 'true'
NEXORA_UNLINKED_ACCESS_ENABLED = os.getenv('NEXORA_UNLINKED_ACCESS_ENABLED', 'false').lower() == 'true'
NEXORA_PUBLIC_ASSESSMENTS_ENABLED = os.getenv('NEXORA_PUBLIC_ASSESSMENTS_ENABLED', 'false').lower() == 'true'
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "edpex.wsgi.application"


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ImproperlyConfigured(f"Required environment variable is missing: {name}")
    return value


if os.getenv("DJANGO_DATABASE_PROFILE", "temporary").lower() == "supabase":
    # Opt-in prevents ordinary tests from ever creating a test DB on Supabase.
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": _required("SUPABASE_DEV_DB_HOST"),
        "PORT": _required("SUPABASE_DEV_DB_PORT"),
        "NAME": _required("SUPABASE_DEV_DB_NAME"),
        "USER": _required("SUPABASE_DEV_DB_USER"),
        "PASSWORD": _required("SUPABASE_DEV_DB_PASSWORD"),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {"sslmode": "require", "connect_timeout": 5},
    }}
else:
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
        "NAME": os.getenv("POSTGRES_DB", "edpex_test"),
        "USER": os.getenv("POSTGRES_USER", "postgres"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "postgres"),
        "OPTIONS": {"connect_timeout": 5},
    }}

LANGUAGE_CODE = "th"
LANGUAGES = [("th", "ไทย"), ("en", "English")]
TIME_ZONE = "Asia/Bangkok"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "workspace"
LOGOUT_REDIRECT_URL = "home"

# Outbound email is configured by the deployment operator, never stored in code.
NEXORA_PUBLIC_ORIGIN = os.getenv('NEXORA_PUBLIC_ORIGIN', '')
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('NEXORA_SMTP_HOST', 'localhost')
EMAIL_PORT = int(os.getenv('NEXORA_SMTP_PORT', '587'))
EMAIL_HOST_USER = os.getenv('NEXORA_SMTP_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('NEXORA_SMTP_PASSWORD', '')
EMAIL_USE_TLS = os.getenv('NEXORA_SMTP_TLS', 'true').lower() == 'true'
EMAIL_USE_SSL = os.getenv('NEXORA_SMTP_SSL', 'false').lower() == 'true'
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = os.getenv('NEXORA_FROM_EMAIL', 'noreply@localhost')
