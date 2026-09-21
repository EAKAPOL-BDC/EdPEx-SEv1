"""Permit aggregate-only setup before ready, then freeze admission context."""
from importlib import import_module
from django.db import migrations

previous=import_module('apps.participation.migrations.0004_access_guards').SQL.split('CREATE TRIGGER unlinked_pool_guard',1)[0]
replacement=previous.replace('CREATE FUNCTION nexora_unlinked_access_guard','CREATE OR REPLACE FUNCTION nexora_unlinked_access_guard')
replacement=replacement.replace("WHERE id=r.population_snapshot_id AND status='frozen'", "WHERE id=COALESCE(r.population_snapshot_id,(SELECT id FROM rounds_populationsnapshot WHERE collection_round_id=r.id AND status='frozen' ORDER BY version DESC LIMIT 1)) AND status='frozen'")
replacement=replacement.replace("r.status NOT IN ('ready','open')", "r.status NOT IN ('draft','ready','open')",1)
guards=r"""
CREATE FUNCTION nexora_unlinked_context_guard() RETURNS trigger AS $$
BEGIN
    IF TG_TABLE_NAME='rounds_collectionround' THEN
        IF NEW.status='draft' AND OLD.status<>'draft' AND EXISTS(SELECT 1 FROM participation_accesspool p JOIN rounds_roundinstrument b ON b.id=p.binding_id WHERE b.collection_round_id=NEW.id) THEN
            RAISE EXCEPTION 'Unlinked access context frozen; create a new collection' USING ERRCODE='23514'; END IF;
    ELSIF TG_TABLE_NAME='surveys_surveyprofile' THEN
        IF EXISTS(SELECT 1 FROM participation_accesspool WHERE binding_id=OLD.binding_id) THEN
            RAISE EXCEPTION 'Unlinked access profile frozen' USING ERRCODE='23514'; END IF;
    ELSE
        IF EXISTS(SELECT 1 FROM participation_accesspool WHERE binding_id=OLD.id) AND
           (NEW.instrument_version_id<>OLD.instrument_version_id OR NEW.translation_bundle_id<>OLD.translation_bundle_id OR NEW.context<>OLD.context OR NEW.collection_round_id<>OLD.collection_round_id) THEN
            RAISE EXCEPTION 'Unlinked access binding frozen' USING ERRCODE='23514'; END IF;
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER unlinked_round_context BEFORE UPDATE ON rounds_collectionround FOR EACH ROW EXECUTE FUNCTION nexora_unlinked_context_guard();
CREATE TRIGGER unlinked_profile_context BEFORE UPDATE OR DELETE ON surveys_surveyprofile FOR EACH ROW EXECUTE FUNCTION nexora_unlinked_context_guard();
CREATE TRIGGER unlinked_binding_context BEFORE UPDATE ON rounds_roundinstrument FOR EACH ROW EXECUTE FUNCTION nexora_unlinked_context_guard();
"""
reverse="""
DROP TRIGGER unlinked_round_context ON rounds_collectionround;
DROP TRIGGER unlinked_profile_context ON surveys_surveyprofile;
DROP TRIGGER unlinked_binding_context ON rounds_roundinstrument;
DROP FUNCTION nexora_unlinked_context_guard();
"""+previous.replace('CREATE FUNCTION nexora_unlinked_access_guard','CREATE OR REPLACE FUNCTION nexora_unlinked_access_guard')

class Migration(migrations.Migration):
    dependencies=[('participation','0004_access_guards')]
    operations=[migrations.RunSQL(replacement+guards,reverse)]
