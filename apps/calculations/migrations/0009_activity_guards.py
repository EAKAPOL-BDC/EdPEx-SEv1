from importlib import import_module
from django.db import migrations

OLD=import_module('apps.calculations.migrations.0006_admin_self_review').UPDATED
needle="(NEW.source_kind='f06_revisions' AND i.code='F06')"
assert needle in OLD
NEW=OLD.replace(needle,"(NEW.source_kind='f05_activity_revisions' AND i.code='F05') OR "+needle)
GUARDS=r'''
CREATE FUNCTION f05_immutable_guard() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'F05 history is append only'; END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER f05_record_immutable BEFORE UPDATE OR DELETE ON calculations_activityrecord
FOR EACH ROW EXECUTE FUNCTION f05_immutable_guard();
CREATE TRIGGER f05_revision_immutable BEFORE UPDATE OR DELETE ON calculations_activityrevision
FOR EACH ROW EXECUTE FUNCTION f05_immutable_guard();
CREATE FUNCTION f05_record_scope_guard() RETURNS trigger AS $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM rounds_roundinstrument ri
 JOIN catalog_instrumentversion iv ON iv.id=ri.instrument_version_id
 JOIN catalog_instrument i ON i.id=iv.instrument_id
 JOIN rounds_collectionround r ON r.id=ri.collection_round_id
 JOIN rounds_populationmember m ON m.id=NEW.member_id
 JOIN rounds_respondentgroup g ON g.id=m.group_id
 WHERE ri.id=NEW.round_instrument_id AND i.code='F05'
 AND m.snapshot_id=r.population_snapshot_id AND g.code IN ('ST1','ST2'))
 THEN RAISE EXCEPTION 'F05 requires a pinned staff population'; END IF;
 RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER f05_record_scope BEFORE INSERT ON calculations_activityrecord
FOR EACH ROW EXECUTE FUNCTION f05_record_scope_guard();
'''
REVERSE='''DROP TRIGGER f05_record_scope ON calculations_activityrecord;
DROP FUNCTION f05_record_scope_guard();
DROP TRIGGER f05_record_immutable ON calculations_activityrecord;
DROP TRIGGER f05_revision_immutable ON calculations_activityrevision;
DROP FUNCTION f05_immutable_guard();'''
class Migration(migrations.Migration):
    dependencies=[('calculations','0008_activity_sources')]
    operations=[migrations.RunSQL(NEW+GUARDS,REVERSE+OLD)]
