from importlib import import_module
from django.db import migrations

# Preserve all independent-review and append-only guards; extend only source eligibility.
ORIGINAL = import_module('apps.calculations.migrations.0004_result_review_guards').SQL
FUNCTION = ORIGINAL.split('CREATE TRIGGER stored_source_guard')[0].replace('CREATE FUNCTION','CREATE OR REPLACE FUNCTION',1)
UPDATED = FUNCTION.replace("IF NEW.source_kind<>'f06_revisions' OR NOT EXISTS (", "IF NOT EXISTS (").replace(
    "AND ri.collection_round_id=run.collection_round_id AND i.code='F06')",
    "AND ri.collection_round_id=run.collection_round_id AND ((NEW.source_kind='f06_revisions' AND i.code='F06') OR (NEW.source_kind='anonymous_surveys' AND i.code IN ('F01','F02','F03','F04') AND EXISTS(SELECT 1 FROM surveys_surveyprofile p WHERE p.binding_id=ri.id))))")
class Migration(migrations.Migration):
    dependencies=[('calculations','0004_result_review_guards'),('surveys','0002_store_guards')]
    operations=[migrations.RunSQL(UPDATED,FUNCTION)]
