"""Curation is a separate human sign-off, not a change to translated content.

Keep the gate that requires curation before publication and every published-source
immutability check. Only unchanged-content curation stops invalidating translations.
Existing rows and approval history are not rewritten by this migration.
"""
from importlib import import_module
from django.db import migrations

SOURCE = import_module('apps.catalog.migrations.0002_postgresql_guards').FORWARD_SQL
ORIGINAL = SOURCE[SOURCE.index('CREATE FUNCTION catalog_version_guard()'):SOURCE.index('CREATE TRIGGER catalog_version_immutable')]
ORIGINAL = ORIGINAL.replace('CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION', 1)
EXCLUDED = "ARRAY['status','checksum','published_at','created_at']"
assert ORIGINAL.count(EXCLUDED) == 2
UPDATED = ORIGINAL.replace(EXCLUDED, "ARRAY['status','checksum','published_at','created_at','instructions_curated']")


class Migration(migrations.Migration):
    dependencies = [('catalog', '0003_review_revisions')]
    operations = [migrations.RunSQL(UPDATED, ORIGINAL)]
