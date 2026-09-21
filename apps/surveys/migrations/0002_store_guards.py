from django.db import migrations

SQL = r"""
CREATE FUNCTION nexora_survey_guard() RETURNS trigger AS $$
DECLARE ri rounds_roundinstrument; r rounds_collectionround; p surveys_surveyprofile;
        inv surveys_invitation; member rounds_populationmember; groupcode text;
BEGIN
    IF TG_TABLE_NAME='surveys_surveyprofile' THEN
        SELECT * INTO ri FROM rounds_roundinstrument WHERE id=COALESCE(NEW.binding_id,OLD.binding_id);
    ELSIF TG_TABLE_NAME='surveys_anonymoussession' THEN
        IF TG_OP='DELETE' THEN RETURN OLD; END IF;
        SELECT * INTO inv FROM surveys_invitation WHERE id=NEW.invitation_id;
        SELECT * INTO ri FROM rounds_roundinstrument WHERE id=inv.binding_id;
    ELSE
        SELECT * INTO ri FROM rounds_roundinstrument WHERE id=COALESCE(NEW.binding_id,OLD.binding_id);
    END IF;
    SELECT * INTO r FROM rounds_collectionround WHERE id=ri.collection_round_id FOR UPDATE;
    IF r.id IS NULL THEN RAISE EXCEPTION 'Survey round missing' USING ERRCODE='23514'; END IF;
    IF TG_TABLE_NAME='surveys_surveyprofile' THEN
        IF r.status<>'draft' OR EXISTS(SELECT 1 FROM surveys_invitation WHERE binding_id=ri.id) THEN RAISE EXCEPTION 'Survey context frozen' USING ERRCODE='23514'; END IF;
        IF TG_OP='UPDATE' AND NEW.binding_id<>OLD.binding_id THEN RAISE EXCEPTION 'Stable survey binding' USING ERRCODE='23514'; END IF;
        IF TG_OP='DELETE' THEN RETURN OLD; END IF;
        IF NOT EXISTS(SELECT 1 FROM catalog_instrumentversion v JOIN catalog_instrument i ON i.id=v.instrument_id
                      WHERE v.id=ri.instrument_version_id AND i.code IN ('F01','F02','F03','F04')) THEN
            RAISE EXCEPTION 'Anonymous survey instrument required' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END IF;
    SELECT * INTO p FROM surveys_surveyprofile WHERE binding_id=ri.id;
    IF p.binding_id IS NULL THEN RAISE EXCEPTION 'Survey profile missing' USING ERRCODE='23514'; END IF;
    IF TG_TABLE_NAME='surveys_invitation' THEN
        IF TG_OP='DELETE' OR (TG_OP='UPDATE' AND (OLD.spent OR NEW.binding_id<>OLD.binding_id OR NEW.member_id<>OLD.member_id)) THEN
            RAISE EXCEPTION 'Used invitation retained; stable eligibility identity' USING ERRCODE='23514';
        END IF;
        SELECT * INTO member FROM rounds_populationmember WHERE id=NEW.member_id;
        SELECT code INTO groupcode FROM rounds_respondentgroup WHERE id=member.group_id;
        IF r.status NOT IN ('ready','open') OR member.snapshot_id IS DISTINCT FROM r.population_snapshot_id OR groupcode<>p.group_code
           OR NEW.expires_at IS DISTINCT FROM r.close_at OR NEW.token_hash !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION 'Invitation must match the pinned population and window' USING ERRCODE='23514';
        END IF;
        IF NEW.spent AND (r.status<>'open' OR NEW.revoked) THEN RAISE EXCEPTION 'Cannot spend unavailable invitation' USING ERRCODE='23514'; END IF;
    ELSIF TG_TABLE_NAME='surveys_anonymoussession' THEN
        IF inv.spent OR inv.revoked OR r.status<>'open' OR NEW.expires_at>inv.expires_at OR NEW.secret_hash !~ '^[0-9a-f]{64}$'
           OR (TG_OP='UPDATE' AND (NEW.invitation_id<>OLD.invitation_id OR NEW.secret_hash<>OLD.secret_hash)) THEN
            RAISE EXCEPTION 'Invalid anonymous session' USING ERRCODE='23514';
        END IF;
    ELSE
        IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Submitted survey response is immutable' USING ERRCODE='23514'; END IF;
        IF r.status<>'open' OR NEW.group_code<>p.group_code OR NEW.submitted_at<r.open_at OR NEW.submitted_at>=r.close_at
           OR jsonb_typeof(NEW.answers)<>'object' THEN
            RAISE EXCEPTION 'Response must match an open pinned survey' USING ERRCODE='23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER survey_profile_guard BEFORE INSERT OR UPDATE OR DELETE ON surveys_surveyprofile FOR EACH ROW EXECUTE FUNCTION nexora_survey_guard();
CREATE TRIGGER survey_invitation_guard BEFORE INSERT OR UPDATE OR DELETE ON surveys_invitation FOR EACH ROW EXECUTE FUNCTION nexora_survey_guard();
CREATE TRIGGER survey_session_guard BEFORE INSERT OR UPDATE OR DELETE ON surveys_anonymoussession FOR EACH ROW EXECUTE FUNCTION nexora_survey_guard();
CREATE TRIGGER survey_response_guard BEFORE INSERT OR UPDATE OR DELETE ON surveys_anonymousresponse FOR EACH ROW EXECUTE FUNCTION nexora_survey_guard();

CREATE FUNCTION nexora_survey_balance() RETURNS trigger AS $$
DECLARE spent_count bigint; response_count bigint;
BEGIN
    SELECT count(*) INTO spent_count FROM surveys_invitation WHERE binding_id=NEW.binding_id AND spent;
    SELECT count(*) INTO response_count FROM surveys_anonymousresponse WHERE binding_id=NEW.binding_id;
    IF spent_count<>response_count THEN RAISE EXCEPTION 'Invitation spend and anonymous response must commit together' USING ERRCODE='23514'; END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
CREATE CONSTRAINT TRIGGER survey_spend_balance AFTER INSERT OR UPDATE ON surveys_invitation DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION nexora_survey_balance();
CREATE CONSTRAINT TRIGGER survey_response_balance AFTER INSERT ON surveys_anonymousresponse DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION nexora_survey_balance();
"""
REVERSE = """
DROP TRIGGER survey_spend_balance ON surveys_invitation;
DROP TRIGGER survey_response_balance ON surveys_anonymousresponse;
DROP FUNCTION nexora_survey_balance();
DROP TRIGGER survey_profile_guard ON surveys_surveyprofile;
DROP TRIGGER survey_invitation_guard ON surveys_invitation;
DROP TRIGGER survey_session_guard ON surveys_anonymoussession;
DROP TRIGGER survey_response_guard ON surveys_anonymousresponse;
DROP FUNCTION nexora_survey_guard();
"""
class Migration(migrations.Migration):
    dependencies=[('surveys','0001_initial')]
    operations=[migrations.RunSQL(SQL,REVERSE)]
