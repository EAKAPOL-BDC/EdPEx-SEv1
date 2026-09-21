from django.db import migrations

SQL=r"""
CREATE FUNCTION nexora_f04_profile_guard() RETURNS trigger AS $$
DECLARE ri rounds_roundinstrument; r rounds_collectionround; t leadership_annualtarget; code text; period uuid;
BEGIN
    IF TG_OP='DELETE' THEN
        IF OLD.annual_target_id IS NOT NULL THEN RAISE EXCEPTION 'Registered F04 history retained' USING ERRCODE='23514'; END IF;
        RETURN OLD;
    END IF;
    SELECT * INTO ri FROM rounds_roundinstrument WHERE id=NEW.binding_id;
    SELECT * INTO r FROM rounds_collectionround WHERE id=ri.collection_round_id;
    SELECT i.code INTO code FROM catalog_instrumentversion v JOIN catalog_instrument i ON i.id=v.instrument_id WHERE v.id=ri.instrument_version_id;
    IF TG_OP='UPDATE' AND NEW.annual_target_id IS DISTINCT FROM OLD.annual_target_id THEN
        RAISE EXCEPTION 'F04 target binding is immutable' USING ERRCODE='23514'; END IF;
    IF NEW.annual_target_id IS NULL THEN
        IF TG_OP='INSERT' AND code='F04' AND NEW.assessor_role<>'BO' THEN
            RAISE EXCEPTION 'Create new individual F04 from fiscal register' USING ERRCODE='23514'; END IF;
        RETURN NEW;
    END IF;
    SELECT * INTO t FROM leadership_annualtarget WHERE id=NEW.annual_target_id;
    SELECT period_id INTO period FROM leadership_annualplan WHERE id=t.plan_id;
    IF t.id IS NULL OR t.scope_id<>r.scope_id OR period<>r.period_id OR code<>'F04' OR t.snapshot->>'role' IS DISTINCT FROM NEW.assessor_role
       OR ri.context<>'f04-target-'||t.id::text OR (TG_OP='INSERT' AND t.status<>'ready') THEN
        RAISE EXCEPTION 'Invalid registered F04 context' USING ERRCODE='23514'; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER f04_profile_guard BEFORE INSERT OR UPDATE OR DELETE ON surveys_surveyprofile FOR EACH ROW EXECUTE FUNCTION nexora_f04_profile_guard();
"""

class Migration(migrations.Migration):
    dependencies=[('surveys','0003_surveyprofile_annual_target_and_more'),('leadership','0002_register_guards')]
    operations=[migrations.RunSQL(SQL,'DROP TRIGGER f04_profile_guard ON surveys_surveyprofile; DROP FUNCTION nexora_f04_profile_guard();')]
