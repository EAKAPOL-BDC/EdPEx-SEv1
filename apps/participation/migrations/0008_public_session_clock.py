"""Use wall clock for transient session expiry, including long transactions."""
from importlib import import_module
from django.db import migrations

previous = import_module('apps.participation.migrations.0007_public_guards').SQL.split('CREATE TRIGGER public_collection_guard', 1)[0]
previous = previous.replace('CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION', 1)
updated = previous.replace('CURRENT_TIMESTAMP', 'clock_timestamp()')
updated = updated.replace("WHERE binding_id=b.id AND group_code IN", "WHERE binding_id=b.id AND intake_method='public' AND group_code IN")


class Migration(migrations.Migration):
    dependencies = [('participation', '0007_public_guards')]
    operations = [migrations.RunSQL(updated, previous)]
