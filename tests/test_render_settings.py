"""Validate assigned and custom hosting origins without connecting to a database."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


class RenderSettingsTests(unittest.TestCase):
    def run_settings(self, overrides=None, expected='https://nexora-test.onrender.com'):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('DJANGO_', 'NEXORA_', 'SUPABASE_DEV_', 'RENDER'))}
        env.update({
            'RENDER': 'true', 'RENDER_EXTERNAL_HOSTNAME': 'nexora-test.onrender.com',
            'RENDER_EXTERNAL_URL': 'https://nexora-test.onrender.com',
            'NEXORA_ENVIRONMENT': 'production', 'DJANGO_DEBUG': 'false',
            'DJANGO_SECRET_KEY': 'configuration-test-only-0123456789-abcdefghijklmnopqrstuvwxyz',
            'DJANGO_DATABASE_PROFILE': 'supabase', 'SUPABASE_DEV_DB_HOST': 'db.example.test',
            'SUPABASE_DEV_DB_PORT': '5432', 'SUPABASE_DEV_DB_NAME': 'postgres',
            'SUPABASE_DEV_DB_USER': 'runtime', 'SUPABASE_DEV_DB_PASSWORD': 'test-placeholder',
            **(overrides or {}),
        })
        return subprocess.run([sys.executable, '-B', '-c',
            'import sys; from edpex import render as p; '
            'assert p.CSRF_TRUSTED_ORIGINS == [sys.argv[1]]; '
            'assert p.ALLOWED_HOSTS == [sys.argv[1].removeprefix("https://")]; '
            'assert p.SESSION_COOKIE_SECURE and p.SECURE_SSL_REDIRECT; '
            'assert not p.NEXORA_PARTICIPATION_ALLOW_LIVE', expected],
            cwd=Path(__file__).resolve().parents[1], env=env,
            capture_output=True, text=True, timeout=20)

    def test_assigned_https_origin(self):
        result = self.run_settings()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_explicit_custom_origin_is_preserved(self):
        result = self.run_settings({'DJANGO_ALLOWED_HOSTS': 'nexora.example.test',
            'NEXORA_PUBLIC_ORIGIN': 'https://nexora.example.test'},
            expected='https://nexora.example.test')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_or_untrusted_platform_origin_is_rejected(self):
        for overrides in (
            {'RENDER': 'false'}, {'RENDER_EXTERNAL_HOSTNAME': ''},
            {'RENDER_EXTERNAL_URL': 'http://nexora-test.onrender.com'},
            {'RENDER_EXTERNAL_URL': 'https://other.onrender.com'},
            {'RENDER_EXTERNAL_HOSTNAME': '*.onrender.com', 'RENDER_EXTERNAL_URL': 'https://*.onrender.com'},
            {'RENDER_EXTERNAL_HOSTNAME': 'nexora.onrender.com.attacker.test',
             'RENDER_EXTERNAL_URL': 'https://nexora.onrender.com.attacker.test'},
        ):
            with self.subTest(overrides=overrides):
                result = self.run_settings(overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('ImproperlyConfigured', result.stderr)

    def test_production_guards_remain_enforced(self):
        for overrides in ({'DJANGO_DEBUG': 'true'}, {'DJANGO_SECRET_KEY': 'weak'},
                          {'DJANGO_DATABASE_PROFILE': 'temporary'},
                          {'DJANGO_ALLOWED_HOSTS': '*'},
                          {'NEXORA_PUBLIC_ORIGIN': 'https://other.example.test'}):
            with self.subTest(overrides=overrides):
                result = self.run_settings(overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('ImproperlyConfigured', result.stderr)
