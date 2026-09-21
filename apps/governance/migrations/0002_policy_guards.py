from importlib import import_module
from django.db import migrations

old_guard=import_module('apps.surveys.migrations.0002_store_guards').SQL.split('CREATE TRIGGER survey_profile_guard')[0]
new_guard=old_guard.replace('CREATE FUNCTION nexora_survey_guard()', 'CREATE OR REPLACE FUNCTION nexora_survey_guard()').replace("('F01','F02','F03','F04')", "('F01','F02','F03','F04','F05','F06')")
old_review=import_module('apps.calculations.migrations.0009_activity_guards').NEW
new_review=old_review.replace("('F01','F02','F03','F04')", "('F01','F02','F03','F04','F05','F06')")
SQL=r"""
CREATE FUNCTION nexora_current_collection_policy() RETURNS trigger AS $$
DECLARE r rounds_collectionround; p rounds_reportingperiod; rootp rounds_reportingperiod; basis text; code text; method text;
BEGIN
 IF TG_TABLE_NAME='surveys_anonymoussession' THEN
   IF NEW.draft<>'{}'::jsonb THEN RAISE EXCEPTION 'Do not retain answers linked to an invitation' USING ERRCODE='23514'; END IF;
   RETURN NEW;
 END IF;
 IF TG_TABLE_NAME IN ('selfassessments_selfassessmentassignment','selfassessments_selfassessmentrevision','calculations_activityrecord','calculations_activityrevision') THEN
   RAISE EXCEPTION 'Identified collection is historical; use anonymous intake' USING ERRCODE='23514';
 END IF;
 IF TG_TABLE_NAME='rounds_roundinstrument' THEN
   SELECT * INTO r FROM rounds_collectionround WHERE id=NEW.collection_round_id;
   SELECT i.code,v.assessment_method INTO code,method FROM catalog_instrumentversion v JOIN catalog_instrument i ON i.id=v.instrument_id WHERE v.id=NEW.instrument_version_id;
 ELSE
   SELECT rr.* INTO r FROM rounds_collectionround rr JOIN rounds_roundinstrument ri ON ri.collection_round_id=rr.id WHERE ri.id=NEW.binding_id;
   SELECT i.code,v.assessment_method INTO code,method FROM rounds_roundinstrument ri JOIN catalog_instrumentversion v ON v.id=ri.instrument_version_id JOIN catalog_instrument i ON i.id=v.instrument_id WHERE ri.id=NEW.binding_id;
 END IF;
 SELECT * INTO p FROM rounds_reportingperiod WHERE id=r.period_id;
 SELECT calendar_type INTO basis FROM rounds_calendar WHERE id=p.calendar_id;
 IF (code='F01' AND basis<>'academic') OR (code IN ('F02','F03','F04','F05','F06') AND basis<>'fiscal') THEN
   RAISE EXCEPTION 'Instrument reporting calendar does not match current policy' USING ERRCODE='23514';
 END IF;
 IF basis='fiscal' THEN
   SELECT * INTO rootp FROM rounds_reportingperiod WHERE id=COALESCE(p.parent_id,p.id);
   IF rootp.start_date<>make_date(rootp.reporting_year_be-544,10,1) OR rootp.end_date<>make_date(rootp.reporting_year_be-543,10,1) THEN
     RAISE EXCEPTION 'Fiscal years must run October to September' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='surveys_surveyprofile' AND ((code IN ('F05','F06') AND method<>'self_report') OR (code NOT IN ('F05','F06') AND method<>'survey')) THEN
   RAISE EXCEPTION 'Anonymous profile method mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER current_reporting_basis BEFORE INSERT ON rounds_roundinstrument FOR EACH ROW EXECUTE FUNCTION nexora_current_collection_policy();
CREATE TRIGGER current_survey_method BEFORE INSERT OR UPDATE ON surveys_surveyprofile FOR EACH ROW EXECUTE FUNCTION nexora_current_collection_policy();
CREATE TRIGGER current_response_basis BEFORE INSERT ON surveys_anonymousresponse FOR EACH ROW EXECUTE FUNCTION nexora_current_collection_policy();
CREATE TRIGGER unlinked_answers BEFORE INSERT OR UPDATE ON surveys_anonymoussession FOR EACH ROW EXECUTE FUNCTION nexora_current_collection_policy();
CREATE TRIGGER historical_f06_assignment BEFORE INSERT ON selfassessments_selfassessmentassignment FOR EACH ROW EXECUTE FUNCTION nexora_current_collection_policy();
CREATE TRIGGER historical_f06_revision BEFORE INSERT ON selfassessments_selfassessmentrevision FOR EACH ROW EXECUTE FUNCTION nexora_current_collection_policy();
CREATE TRIGGER historical_f05_record BEFORE INSERT ON calculations_activityrecord FOR EACH ROW EXECUTE FUNCTION nexora_current_collection_policy();
CREATE TRIGGER historical_f05_revision BEFORE INSERT ON calculations_activityrevision FOR EACH ROW EXECUTE FUNCTION nexora_current_collection_policy();
"""
REVERSE=r"""
DROP TRIGGER current_reporting_basis ON rounds_roundinstrument;
DROP TRIGGER current_survey_method ON surveys_surveyprofile;
DROP TRIGGER current_response_basis ON surveys_anonymousresponse;
DROP TRIGGER unlinked_answers ON surveys_anonymoussession;
DROP TRIGGER historical_f06_assignment ON selfassessments_selfassessmentassignment;
DROP TRIGGER historical_f06_revision ON selfassessments_selfassessmentrevision;
DROP TRIGGER historical_f05_record ON calculations_activityrecord;
DROP TRIGGER historical_f05_revision ON calculations_activityrevision;
DROP FUNCTION nexora_current_collection_policy();
"""
class Migration(migrations.Migration):
    dependencies=[('governance','0001_initial'),('surveys','0004_f04_target_guards'),('selfassessments','0003_disambiguate_question_alias'),('calculations','0009_activity_guards')]
    operations=[migrations.RunSQL(new_guard+new_review+SQL,REVERSE+old_review+old_guard.replace('CREATE FUNCTION','CREATE OR REPLACE FUNCTION',1))]
