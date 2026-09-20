from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase
from django.core.management.base import CommandError
from apps.surveys.management.commands.upgrade_survey_schema import Command,ALLOWED

class SurveyUpgradeTests(SimpleTestCase):
    def executor(self, factory, names):
        executor=factory.return_value
        executor.loader.graph.leaf_nodes.return_value=list(ALLOWED)
        executor.migration_plan.return_value=[(SimpleNamespace(app_label=app,name=name),False) for app,name in names]
        return executor

    @patch('apps.surveys.management.commands.upgrade_survey_schema.MigrationExecutor')
    def test_pending_changes_are_read_only_without_apply(self,factory):
        executor=self.executor(factory,ALLOWED)
        with self.assertRaises(CommandError):Command(stdout=StringIO()).handle(apply=False)
        executor.migrate.assert_not_called()

    @patch('apps.surveys.management.commands.upgrade_survey_schema.MigrationExecutor')
    def test_unrelated_pending_migration_stops_before_any_apply(self,factory):
        executor=self.executor(factory,ALLOWED|{('accounts','unknown_future_migration')})
        with self.assertRaises(CommandError):Command(stdout=StringIO()).handle(apply=True)
        executor.migrate.assert_not_called()

    @patch('apps.surveys.management.commands.upgrade_survey_schema.MigrationExecutor')
    def test_explicit_apply_accepts_only_release_plan(self,factory):
        executor=self.executor(factory,ALLOWED)
        Command(stdout=StringIO()).handle(apply=True)
        executor.migrate.assert_called_once_with(list(ALLOWED))
