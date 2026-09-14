import importlib
import os
from unittest import TestCase, mock

from django.core.exceptions import ImproperlyConfigured


class DatabaseSettingsTests(TestCase):
    def test_default_profile_uses_temporary_postgres(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = importlib.reload(importlib.import_module("edpex.settings"))
        self.assertEqual(settings.DATABASES["default"]["HOST"], "127.0.0.1")
        self.assertNotIn("sslmode", settings.DATABASES["default"].get("OPTIONS", {}))

    def test_supabase_profile_requires_secrets(self):
        with mock.patch.dict(os.environ, {"DJANGO_DATABASE_PROFILE": "supabase"}, clear=True):
            with self.assertRaises(ImproperlyConfigured):
                importlib.reload(importlib.import_module("edpex.settings"))

    def test_supabase_profile_requires_tls(self):
        environment = {"DJANGO_DATABASE_PROFILE": "supabase"}
        environment.update({name: "value" for name in (
            "SUPABASE_DEV_DB_HOST", "SUPABASE_DEV_DB_PORT", "SUPABASE_DEV_DB_NAME",
            "SUPABASE_DEV_DB_USER", "SUPABASE_DEV_DB_PASSWORD",
        )})
        with mock.patch.dict(os.environ, environment, clear=True):
            settings = importlib.reload(importlib.import_module("edpex.settings"))
        self.assertEqual(settings.DATABASES["default"]["OPTIONS"]["sslmode"], "require")
