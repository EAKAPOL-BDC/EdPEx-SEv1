"""Public intake remains balanced with anonymous answers at transaction commit."""
from importlib import import_module
from django.db import migrations

SQL = r"""
CREATE FUNCTION nexora_public_guard() RETURNS trigger AS $$
DECLARE b rounds_roundinstrument; r rounds_collectionround; p participation_publiccollection;
BEGIN
    SELECT * INTO b FROM rounds_roundinstrument WHERE id=COALESCE(NEW.binding_id,OLD.binding_id);
    SELECT * INTO r FROM rounds_collectionround WHERE id=b.collection_round_id FOR UPDATE;
    IF TG_TABLE_NAME='participation_publiccollection' THEN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Public contract retained' USING ERRCODE='23514'; END IF;
        IF TG_OP='INSERT' THEN
            IF r.status<>'draft' OR NEW.published OR NEW.contract_version<>'2026-09-19'
               OR EXISTS(SELECT 1 FROM participation_accesspool WHERE binding_id=b.id)
               OR EXISTS(SELECT 1 FROM surveys_invitation WHERE binding_id=b.id)
               OR EXISTS(SELECT 1 FROM surveys_anonymousresponse WHERE binding_id=b.id)
               OR NOT EXISTS(SELECT 1 FROM surveys_surveyprofile WHERE binding_id=b.id AND group_code IN
                 ('C1','C2.1','C2.2','C3.1','C4.1','C5.1','C5.2','C5.3','S1','S3-1','S3-2','CO-1','CO-2','CO-3','CO-4','ST1','ST2')) THEN
                RAISE EXCEPTION 'Fresh public draft required' USING ERRCODE='23514'; END IF;
        ELSIF (to_jsonb(NEW)-'published') IS DISTINCT FROM (to_jsonb(OLD)-'published') THEN
            RAISE EXCEPTION 'Public contract immutable' USING ERRCODE='23514';
        END IF;
        IF NEW.published AND (r.status NOT IN ('ready','open') OR r.close_at<=CURRENT_TIMESTAMP
           OR NOT EXISTS(SELECT 1 FROM participation_receiptpolicy WHERE binding_id=b.id AND enabled AND expires_at>CURRENT_TIMESTAMP)
           OR NOT EXISTS(SELECT 1 FROM rounds_populationsnapshot s JOIN rounds_datasource d ON d.id=s.source_id
                         WHERE s.id=r.population_snapshot_id AND s.status='frozen' AND d.source_type='aggregate')
           OR EXISTS(SELECT 1 FROM rounds_populationmember WHERE snapshot_id=r.population_snapshot_id)) THEN
            RAISE EXCEPTION 'Public collection not ready' USING ERRCODE='23514'; END IF;
        RETURN NEW;
    END IF;
    SELECT * INTO p FROM participation_publiccollection WHERE binding_id=b.id;
    IF TG_OP='DELETE' THEN
        IF OLD.spent THEN RAISE EXCEPTION 'Spent public slot retained' USING ERRCODE='23514'; END IF;
        RETURN OLD;
    END IF;
    IF NOT p.published OR r.status<>'open' OR CURRENT_TIMESTAMP<r.open_at OR CURRENT_TIMESTAMP>=r.close_at THEN
        RAISE EXCEPTION 'Public collection unavailable' USING ERRCODE='23514'; END IF;
    IF TG_OP='INSERT' THEN
        IF NEW.spent OR NEW.secret_hash IS NULL OR NEW.secret_hash !~ '^[0-9a-f]{64}$'
           OR NEW.expires_at IS NULL OR NEW.expires_at>CURRENT_TIMESTAMP+interval '24 hours'
           OR NEW.expires_at>r.close_at OR NEW.expires_at<=CURRENT_TIMESTAMP THEN
            RAISE EXCEPTION 'Invalid public session' USING ERRCODE='23514'; END IF;
    ELSE
        IF OLD.spent OR NOT NEW.spent OR NEW.binding_id<>OLD.binding_id OR NEW.id<>OLD.id
           OR NEW.secret_hash IS NOT NULL OR NEW.expires_at IS NOT NULL OR NEW.year<>'' THEN
            RAISE EXCEPTION 'Public session may only be consumed and cleared' USING ERRCODE='23514'; END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER public_collection_guard BEFORE INSERT OR UPDATE OR DELETE ON participation_publiccollection FOR EACH ROW EXECUTE FUNCTION nexora_public_guard();
CREATE TRIGGER public_session_guard BEFORE INSERT OR UPDATE OR DELETE ON participation_publicsession FOR EACH ROW EXECUTE FUNCTION nexora_public_guard();

CREATE OR REPLACE FUNCTION nexora_survey_balance() RETURNS trigger AS $$
DECLARE spent_count bigint; response_count bigint;
BEGIN
    SELECT (SELECT count(*) FROM surveys_invitation WHERE binding_id=NEW.binding_id AND spent)+
           (SELECT count(*) FROM participation_accesspass WHERE binding_id=NEW.binding_id AND spent)+
           (SELECT count(*) FROM participation_publicsession WHERE binding_id=NEW.binding_id AND spent) INTO spent_count;
    SELECT count(*) INTO response_count FROM surveys_anonymousresponse WHERE binding_id=NEW.binding_id;
    IF spent_count<>response_count THEN RAISE EXCEPTION 'Access spend and anonymous response must commit together' USING ERRCODE='23514'; END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
CREATE CONSTRAINT TRIGGER public_spend_balance AFTER INSERT OR UPDATE ON participation_publicsession DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION nexora_survey_balance();

CREATE FUNCTION nexora_public_context_guard() RETURNS trigger AS $$
BEGIN
    IF TG_TABLE_NAME='rounds_collectionround' THEN
        IF NEW.status='draft' AND OLD.status<>'draft' AND EXISTS(SELECT 1 FROM participation_publiccollection p JOIN rounds_roundinstrument b ON b.id=p.binding_id WHERE b.collection_round_id=NEW.id) THEN
            RAISE EXCEPTION 'Public contract frozen' USING ERRCODE='23514'; END IF;
    ELSIF TG_TABLE_NAME='surveys_surveyprofile' THEN
        IF EXISTS(SELECT 1 FROM participation_publiccollection WHERE binding_id=OLD.binding_id) THEN
            RAISE EXCEPTION 'Public profile frozen' USING ERRCODE='23514'; END IF;
    ELSIF TG_TABLE_NAME IN ('surveys_invitation','participation_accesspool') THEN
        IF EXISTS(SELECT 1 FROM participation_publiccollection WHERE binding_id=NEW.binding_id) THEN
            RAISE EXCEPTION 'Public collections cannot acquire invitations' USING ERRCODE='23514'; END IF;
    ELSE
        IF EXISTS(SELECT 1 FROM participation_publiccollection WHERE binding_id=OLD.id) AND
           (NEW.instrument_version_id<>OLD.instrument_version_id OR NEW.translation_bundle_id<>OLD.translation_bundle_id OR NEW.context<>OLD.context OR NEW.collection_round_id<>OLD.collection_round_id) THEN
            RAISE EXCEPTION 'Public binding frozen' USING ERRCODE='23514'; END IF;
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER public_round_context BEFORE UPDATE ON rounds_collectionround FOR EACH ROW EXECUTE FUNCTION nexora_public_context_guard();
CREATE TRIGGER public_profile_context BEFORE UPDATE OR DELETE ON surveys_surveyprofile FOR EACH ROW EXECUTE FUNCTION nexora_public_context_guard();
CREATE TRIGGER public_binding_context BEFORE UPDATE ON rounds_roundinstrument FOR EACH ROW EXECUTE FUNCTION nexora_public_context_guard();
CREATE TRIGGER public_no_invitation BEFORE INSERT ON surveys_invitation FOR EACH ROW EXECUTE FUNCTION nexora_public_context_guard();
CREATE TRIGGER public_no_pool BEFORE INSERT ON participation_accesspool FOR EACH ROW EXECUTE FUNCTION nexora_public_context_guard();
"""

previous = import_module('apps.participation.migrations.0004_access_guards').SQL
restore = 'CREATE OR REPLACE FUNCTION nexora_survey_balance' + previous.split('CREATE OR REPLACE FUNCTION nexora_survey_balance', 1)[1].split('CREATE CONSTRAINT TRIGGER', 1)[0]
REVERSE = """
DROP TRIGGER public_spend_balance ON participation_publicsession;
DROP TRIGGER public_collection_guard ON participation_publiccollection;
DROP TRIGGER public_session_guard ON participation_publicsession;
DROP TRIGGER public_round_context ON rounds_collectionround;
DROP TRIGGER public_profile_context ON surveys_surveyprofile;
DROP TRIGGER public_binding_context ON rounds_roundinstrument;
DROP TRIGGER public_no_invitation ON surveys_invitation;
DROP TRIGGER public_no_pool ON participation_accesspool;
DROP FUNCTION nexora_public_guard();
DROP FUNCTION nexora_public_context_guard();
""" + restore


class Migration(migrations.Migration):
    dependencies = [('participation', '0006_publiccollection_publicsession'), ('surveys', '0005_remove_surveyprofile_f04_target_group_collection_and_more')]
    operations = [migrations.RunSQL(SQL, REVERSE)]
