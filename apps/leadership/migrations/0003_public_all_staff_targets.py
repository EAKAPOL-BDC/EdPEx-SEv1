"""A distinct frozen policy for all-staff public assessment, without a roster."""
from importlib import import_module
from django.db import migrations

previous = import_module('apps.leadership.migrations.0002_register_guards').SQL.split('CREATE TRIGGER', 1)[0]
previous = previous.replace('CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION', 1)
updated = previous.replace("OR NOT EXISTS(SELECT 1 FROM leadership_eligibility WHERE target_id=NEW.id))", "OR (COALESCE(NEW.snapshot->>'respondent_policy','')<>'all_staff_public' AND NOT EXISTS(SELECT 1 FROM leadership_eligibility WHERE target_id=NEW.id)) OR (NEW.snapshot->>'respondent_policy'='all_staff_public' AND EXISTS(SELECT 1 FROM leadership_eligibility WHERE target_id=NEW.id)))")


class Migration(migrations.Migration):
    dependencies = [('leadership', '0002_register_guards'), ('participation', '0008_public_session_clock')]
    operations = [migrations.RunSQL(updated, previous)]
