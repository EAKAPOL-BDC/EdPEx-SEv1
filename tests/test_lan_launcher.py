import argparse
import contextlib
import getpass
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import start_nexora_lan as launcher


class LANLauncherTests(unittest.TestCase):
    def credentials(self):
        return dict(SUPABASE_DEV_DB_HOST='db.example.invalid', SUPABASE_DEV_DB_PORT='5432',
                    SUPABASE_DEV_DB_NAME='postgres', SUPABASE_DEV_DB_USER='postgres.synthetic',
                    SUPABASE_DEV_DB_PASSWORD='Synthetic-secret-only')

    def test_only_private_ipv4_is_accepted(self):
        for address in ['10.51.72.130', '172.16.1.5', '192.168.1.8']:
            self.assertEqual(launcher.lan_ip(address), address)
        for address in ['0.0.0.0', '127.0.0.1', '8.8.8.8', '::1', 'bad', '10.1.1.2:8000']:
            with self.assertRaises(argparse.ArgumentTypeError): launcher.lan_ip(address)

    def test_missing_credentials_are_prompted_password_not_printed(self):
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch('builtins.input', side_effect=['db.example.invalid', '', '', 'postgres.synthetic']), patch.object(getpass, 'getpass', return_value='Synthetic-secret-only') as secret, contextlib.redirect_stdout(output):
            result = launcher.environment(Path('/app'), '10.51.72.130')
        self.assertEqual(result['SUPABASE_DEV_DB_HOST'], 'db.example.invalid')
        self.assertEqual(result['SUPABASE_DEV_DB_PORT'], '5432')
        self.assertEqual(result['SUPABASE_DEV_DB_PASSWORD'], 'Synthetic-secret-only')
        self.assertNotIn('Synthetic-secret-only', output.getvalue())
        secret.assert_called_once()

    def test_existing_credentials_preserved_and_stale_settings_isolated(self):
        original = dict(self.credentials(), PYTHONPATH='/wrong', DATABASE_URL='unrelated',
                        DJANGO_SETTINGS_MODULE='wrong.settings', DJANGO_SECRET_KEY='preserve-key',
                        POSTGRES_DB='wrong', EDPEX_TEST_READONLY='true')
        with patch.dict(os.environ, original, clear=True), patch('builtins.input') as prompt:
            result = launcher.environment(Path('/installed'), '10.51.72.130')
            self.assertEqual(dict(os.environ), original)
        prompt.assert_not_called()
        self.assertEqual(result['DJANGO_SECRET_KEY'], 'preserve-key')
        self.assertEqual(result['PYTHONPATH'], '/installed')
        self.assertEqual(result['DJANGO_ALLOWED_HOSTS'], 'localhost,127.0.0.1,10.51.72.130')
        for key in ('DATABASE_URL','POSTGRES_DB','EDPEX_TEST_READONLY'):
            self.assertNotIn(key, result)

    def test_production_proxy_and_unmasked_password_are_refused(self):
        for setting in ({'NEXORA_ENVIRONMENT':'production'}, {'NEXORA_TRUST_HTTPS_PROXY':'true'}):
            with patch.dict(os.environ, setting, clear=True), self.assertRaises(launcher.LaunchError):
                launcher.environment(Path('/app'), '10.51.72.130')
        values = self.credentials(); values.pop('SUPABASE_DEV_DB_PASSWORD')
        with patch.dict(os.environ, values, clear=True), patch.object(getpass, 'getpass', side_effect=getpass.GetPassWarning()), self.assertRaises(launcher.LaunchError):
            launcher.environment(Path('/app'), '10.51.72.130')

    def test_launch_uses_installed_checkout_and_only_runs_server(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder); (project/'manage.py').touch(); (project/'edpex').mkdir(); (project/'edpex/settings.py').touch()
            with patch.dict(os.environ, self.credentials(), clear=True), patch.object(launcher.subprocess, 'call', return_value=0) as call, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(launcher.main(['--project', folder, '--ip', '10.51.72.130']), 0)
            args, kwargs = call.call_args
            self.assertEqual(args[0][1:], [str(project/'manage.py'), 'runserver', '10.51.72.130:8000', '--settings=edpex.settings', '--noreload'])
            self.assertEqual(kwargs['cwd'], project)
            self.assertNotIn('Synthetic-secret-only', ' '.join(args[0]))

    def test_missing_checkout_stops_before_credentials_or_database(self):
        with tempfile.TemporaryDirectory() as folder, patch('builtins.input') as prompt, patch.object(launcher.subprocess,'call') as call, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(launcher.main(['--project', folder, '--ip', '10.51.72.130']), 1)
            prompt.assert_not_called(); call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
