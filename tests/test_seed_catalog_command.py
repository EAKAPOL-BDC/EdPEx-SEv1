from io import StringIO
from unittest.mock import patch
from django.core.management import call_command
from django.test import SimpleTestCase
from apps.catalog.management.commands.seed_catalog import Command


class SeedCommandTests(SimpleTestCase):
    def test_parser_keeps_django_version_and_accepts_catalog_version(self):
        parser = Command().create_parser('manage.py', 'seed_catalog')
        args = parser.parse_args(['--scope-id', 'scope', '--actor-user-id', '1', '--catalog-version', '1.1'])
        self.assertEqual(args.catalog_version, '1.1')
        self.assertIn('--version', parser.format_help())
        self.assertIn('--catalog-version', parser.format_help())

    def test_cli_dispatches_catalog_version_to_service(self):
        module = 'apps.catalog.management.commands.seed_catalog.'
        with patch(module + 'AccessScope.objects.get') as scope, patch(module + 'get_user_model') as user, patch(module + 'seed_catalog', return_value={'created_instruments': 6}) as seed:
            output = StringIO()
            call_command('seed_catalog', '--scope-id', 'scope', '--actor-user-id', '1', '--catalog-version', '1.1', stdout=output)
            seed.assert_called_once_with(scope.return_value, user.return_value.objects.get.return_value, version='1.1')
            self.assertIn('Created 6 draft instrument versions', output.getvalue())
