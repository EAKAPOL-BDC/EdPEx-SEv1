"""Production configuration must fail closed without touching a database."""
import os
import subprocess
import sys
from pathlib import Path
from django.test import SimpleTestCase


class ProductionSettingsTests(SimpleTestCase):
    def run_settings(self, **overrides):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('DJANGO_', 'NEXORA_', 'SUPABASE_DEV_'))}
        env.update({
            'NEXORA_ENVIRONMENT': 'production', 'DJANGO_DEBUG': 'false',
            'DJANGO_SECRET_KEY': 'configuration-test-only-0123456789-abcdefghijklmnopqrstuvwxyz',
            'DJANGO_ALLOWED_HOSTS': 'nexora.example.test', 'NEXORA_PUBLIC_ORIGIN': 'https://nexora.example.test',
            'DJANGO_DATABASE_PROFILE': 'supabase', 'SUPABASE_DEV_DB_HOST': 'db.example.test',
            'SUPABASE_DEV_DB_PORT': '5432', 'SUPABASE_DEV_DB_NAME': 'postgres',
            'SUPABASE_DEV_DB_USER': 'runtime', 'SUPABASE_DEV_DB_PASSWORD': 'test-placeholder',
            **overrides,
        })
        return subprocess.run([sys.executable, '-B', '-c',
            'from edpex import production as p; assert p.SESSION_COOKIE_SECURE; '
            'assert p.CSRF_TRUSTED_ORIGINS == ["https://nexora.example.test"]; '
            'assert not p.NEXORA_PARTICIPATION_ALLOW_LIVE; '
            'assert p.DATABASES["default"]["CONN_MAX_AGE"] == 0'],
            cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True)

    def test_explicit_production_configuration(self):
        result = self.run_settings()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unsafe_settings_are_rejected(self):
        for override in (
            {'NEXORA_ENVIRONMENT': 'development'}, {'DJANGO_DEBUG': 'true'},
            {'DJANGO_SECRET_KEY': 'weak'}, {'DJANGO_ALLOWED_HOSTS': '*'},
            {'DJANGO_DATABASE_PROFILE': 'temporary'},
            {'NEXORA_PUBLIC_ORIGIN': 'http://nexora.example.test'},
            {'NEXORA_PUBLIC_ORIGIN': 'https://other.example.test'},
            {'NEXORA_PUBLIC_ORIGIN': 'https://nexora.example.test/path'},
        ):
            with self.subTest(override=override):
                result = self.run_settings(**override)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('ImproperlyConfigured', result.stderr)
