from importlib import import_module
from django.db import migrations

SQL=r"""
CREATE FUNCTION nexora_unlinked_access_guard() RETURNS trigger AS $$
DECLARE b rounds_roundinstrument; r rounds_collectionround; pool participation_accesspool;
        pass participation_accesspass; p surveys_surveyprofile; lim integer; total bigint;
BEGIN
    IF TG_TABLE_NAME='participation_accesssession' THEN
        IF TG_OP='DELETE' THEN RETURN OLD; END IF;
        SELECT * INTO pass FROM participation_accesspass WHERE id=NEW.invitation_id;
        SELECT * INTO b FROM rounds_roundinstrument WHERE id=pass.binding_id;
    ELSE
        SELECT * INTO b FROM rounds_roundinstrument WHERE id=COALESCE(NEW.binding_id,OLD.binding_id);
    END IF;
    SELECT * INTO r FROM rounds_collectionround WHERE id=b.collection_round_id FOR UPDATE;
    SELECT * INTO pool FROM participation_accesspool WHERE binding_id=b.id;
    SELECT * INTO p FROM surveys_surveyprofile WHERE binding_id=b.id;
    IF TG_TABLE_NAME='surveys_invitation' THEN
        IF pool.binding_id IS NOT NULL AND TG_OP='INSERT' THEN
            SELECT (SELECT count(*) FROM surveys_invitation WHERE binding_id=b.id)+
                   (SELECT count(*) FROM participation_accesspass WHERE binding_id=b.id) INTO total;
            IF total>=pool.capacity THEN RAISE EXCEPTION 'Invitation capacity exhausted' USING ERRCODE='23514'; END IF;
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Access history retained' USING ERRCODE='23514'; END IF;
    IF TG_TABLE_NAME='participation_accesspool' THEN
        IF TG_OP='UPDATE' THEN
            IF NEW.binding_id<>OLD.binding_id OR NEW.capacity<>OLD.capacity THEN
                RAISE EXCEPTION 'Access capacity and binding immutable' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END IF;
        SELECT (counts_by_group->>p.group_code)::integer INTO lim FROM rounds_populationsnapshot WHERE id=r.population_snapshot_id AND status='frozen';
        SELECT count(*) INTO total FROM surveys_invitation WHERE binding_id=b.id;
        IF lim IS NULL OR NEW.capacity>lim OR NEW.capacity<total OR r.status NOT IN ('ready','open') OR r.close_at<=CURRENT_TIMESTAMP
           OR p.group_code<>'C1' OR NOT EXISTS(SELECT 1 FROM catalog_instrumentversion v JOIN catalog_instrument i ON i.id=v.instrument_id WHERE v.id=b.instrument_version_id AND i.code='F01')
           OR NOT EXISTS(SELECT 1 FROM participation_receiptpolicy WHERE binding_id=b.id AND realm='test' AND enabled AND expires_at>CURRENT_TIMESTAMP) THEN
            RAISE EXCEPTION 'Invalid unlinked access configuration' USING ERRCODE='23514'; END IF;
        RETURN NEW;
    END IF;
    IF TG_TABLE_NAME='participation_accesspass' THEN
        IF TG_OP='INSERT' THEN
            SELECT (SELECT count(*) FROM surveys_invitation WHERE binding_id=b.id)+
                   (SELECT count(*) FROM participation_accesspass WHERE binding_id=b.id) INTO total;
            IF pool.binding_id IS NULL OR NOT pool.enabled OR total>=pool.capacity OR NEW.spent OR NEW.revoked
               OR r.status NOT IN ('ready','open') OR r.close_at<=CURRENT_TIMESTAMP THEN
                RAISE EXCEPTION 'Access pass unavailable or capacity exhausted' USING ERRCODE='23514'; END IF;
        ELSE
            IF (to_jsonb(NEW)-'spent'-'revoked') IS DISTINCT FROM (to_jsonb(OLD)-'spent'-'revoked') OR OLD.spent OR (OLD.revoked AND NOT NEW.revoked) THEN
                RAISE EXCEPTION 'Access pass immutable; terminal states cannot be undone' USING ERRCODE='23514'; END IF;
            IF NEW.spent AND (NEW.revoked OR NOT pool.enabled OR r.status<>'open' OR CURRENT_TIMESTAMP<r.open_at OR CURRENT_TIMESTAMP>=r.close_at) THEN
                RAISE EXCEPTION 'Cannot spend unavailable access' USING ERRCODE='23514'; END IF;
        END IF;
        IF NEW.token_hash !~ '^[0-9a-f]{64}$' OR NEW.expires_at IS DISTINCT FROM r.close_at THEN
            RAISE EXCEPTION 'Invalid access hash or expiry' USING ERRCODE='23514'; END IF;
    ELSE
        IF TG_OP<>'INSERT' OR NEW.secret_hash !~ '^[0-9a-f]{64}$' OR NEW.revision<>0 OR NOT pool.enabled
           OR pass.spent OR pass.revoked OR NEW.expires_at>pass.expires_at OR NEW.expires_at<=CURRENT_TIMESTAMP
           OR r.status<>'open' OR CURRENT_TIMESTAMP<r.open_at OR CURRENT_TIMESTAMP>=r.close_at THEN
            RAISE EXCEPTION 'Invalid unlinked session' USING ERRCODE='23514'; END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER unlinked_pool_guard BEFORE INSERT OR UPDATE OR DELETE ON participation_accesspool FOR EACH ROW EXECUTE FUNCTION nexora_unlinked_access_guard();
CREATE TRIGGER unlinked_pass_guard BEFORE INSERT OR UPDATE OR DELETE ON participation_accesspass FOR EACH ROW EXECUTE FUNCTION nexora_unlinked_access_guard();
CREATE TRIGGER unlinked_session_guard BEFORE INSERT OR UPDATE OR DELETE ON participation_accesssession FOR EACH ROW EXECUTE FUNCTION nexora_unlinked_access_guard();
CREATE TRIGGER unlinked_legacy_capacity BEFORE INSERT ON surveys_invitation FOR EACH ROW EXECUTE FUNCTION nexora_unlinked_access_guard();

CREATE OR REPLACE FUNCTION nexora_survey_balance() RETURNS trigger AS $$
DECLARE spent_count bigint; response_count bigint;
BEGIN
    SELECT (SELECT count(*) FROM surveys_invitation WHERE binding_id=NEW.binding_id AND spent)+
           (SELECT count(*) FROM participation_accesspass WHERE binding_id=NEW.binding_id AND spent) INTO spent_count;
    SELECT count(*) INTO response_count FROM surveys_anonymousresponse WHERE binding_id=NEW.binding_id;
    IF spent_count<>response_count THEN RAISE EXCEPTION 'Invitation spend and anonymous response must commit together' USING ERRCODE='23514'; END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
CREATE CONSTRAINT TRIGGER unlinked_spend_balance AFTER INSERT OR UPDATE ON participation_accesspass DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION nexora_survey_balance();
"""

original=import_module('apps.surveys.migrations.0002_store_guards').SQL
restore='CREATE OR REPLACE FUNCTION nexora_survey_balance'+original.split('CREATE FUNCTION nexora_survey_balance',1)[1].split('CREATE CONSTRAINT TRIGGER',1)[0]
REVERSE="""
DROP TRIGGER unlinked_spend_balance ON participation_accesspass;
DROP TRIGGER unlinked_pool_guard ON participation_accesspool;
DROP TRIGGER unlinked_pass_guard ON participation_accesspass;
DROP TRIGGER unlinked_session_guard ON participation_accesssession;
DROP TRIGGER unlinked_legacy_capacity ON surveys_invitation;
DROP FUNCTION nexora_unlinked_access_guard();
"""+restore

class Migration(migrations.Migration):
    dependencies=[('participation','0003_accesspass_accesspool_accesssession'),('surveys','0004_f04_target_guards')]
    operations=[migrations.RunSQL(SQL,REVERSE)]
