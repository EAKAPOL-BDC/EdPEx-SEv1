"""Repair the trigger function for both fresh and already-migrated development DBs."""
from importlib import import_module
from django.db import migrations

original = import_module('apps.selfassessments.migrations.0002_immutable_guards')
# q is a PL/pgSQL row variable later in the revision-validation branch. Give
# assignment-validation subqueries a distinct alias so PostgreSQL can resolve it.
OLD_FUNCTION = original.SQL.split('CREATE TRIGGER', 1)[0].replace(
    'CREATE FUNCTION edpex_self_report_guard()', 'CREATE OR REPLACE FUNCTION edpex_self_report_guard()')
NEW_FUNCTION = OLD_FUNCTION.replace('catalog_question q', 'catalog_question candidate_question')
for field in ('version_id', 'active', 'group_codes', 'question_id'):
    NEW_FUNCTION = NEW_FUNCTION.replace('q.' + field, 'candidate_question.' + field)


class Migration(migrations.Migration):
    dependencies = [('selfassessments', '0002_immutable_guards')]
    operations = [migrations.RunSQL(NEW_FUNCTION, OLD_FUNCTION)]
