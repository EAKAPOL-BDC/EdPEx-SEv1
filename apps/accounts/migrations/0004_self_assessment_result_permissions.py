"""Explicit actions; no change to existing grants or assigned roles."""
from importlib import import_module
from django.db import migrations

previous = import_module('apps.accounts.migrations.0003_calculation_permissions')
OLD = previous.OLD_ACTIONS + ", 'calculation.run', 'calculation.source', 'calculation.validate'"
NEW = OLD + ", 'selfassessment.assign', 'result.submit', 'result.review', 'result.approve'"


class Migration(migrations.Migration):
    dependencies = [('accounts', '0003_calculation_permissions')]
    operations = [migrations.RunSQL(previous.FUNCTION % NEW, previous.FUNCTION % OLD)]
