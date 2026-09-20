"""Static asset build only: no production credentials or remote database."""
import os

os.environ['NEXORA_ENVIRONMENT'] = 'development'
os.environ['DJANGO_DATABASE_PROFILE'] = 'temporary'
from .settings import *  # noqa: E402,F403

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
