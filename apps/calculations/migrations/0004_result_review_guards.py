from django.db import migrations

SQL = r"""
CREATE FUNCTION edpex_result_review_guard() RETURNS trigger AS $$
DECLARE run calculations_calculationrun; review calculations_resultreviewrequest;
        selected uuid; previous calculations_resultdecision;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Aggregate review history is append-only' USING ERRCODE='23514';
    END IF;
    IF TG_TABLE_NAME = 'calculations_resultdecision' THEN
        SELECT * INTO review FROM calculations_resultreviewrequest WHERE id=NEW.review_id;
        SELECT * INTO run FROM calculations_calculationrun WHERE id=review.run_id;
    ELSE
        SELECT * INTO run FROM calculations_calculationrun WHERE id=NEW.run_id;
    END IF;
    PERFORM 1 FROM rounds_collectionround WHERE id=run.collection_round_id FOR UPDATE;
    IF run.id IS NULL OR run.status<>'complete' THEN
        RAISE EXCEPTION 'Aggregate review requires a sealed run' USING ERRCODE='23514';
    END IF;
    IF TG_TABLE_NAME = 'calculations_storedsourceselection' THEN
        IF NEW.source_kind<>'f06_revisions' OR NOT EXISTS (
            SELECT 1 FROM rounds_roundinstrument ri JOIN catalog_instrumentversion v ON v.id=ri.instrument_version_id
            JOIN catalog_instrument i ON i.id=v.instrument_id WHERE ri.id=NEW.round_instrument_id
            AND ri.collection_round_id=run.collection_round_id AND i.code='F06')
            OR EXISTS (SELECT 1 FROM calculations_calculationinputsnapshot WHERE run_id=run.id AND round_instrument_id<>NEW.round_instrument_id) THEN
            RAISE EXCEPTION 'Stored source selection crosses instrument or round' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END IF;
    SELECT round_instrument_id INTO selected FROM calculations_storedsourceselection WHERE run_id=run.id;
    IF selected IS NULL OR btrim(NEW.reason)='' OR length(NEW.reason)>2000 THEN
        RAISE EXCEPTION 'Review needs a stored source and a reason' USING ERRCODE='23514';
    END IF;
    IF TG_TABLE_NAME = 'calculations_resultreviewrequest' THEN
        IF NEW.review_token !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION 'Invalid review token' USING ERRCODE='23514';
        END IF;
    ELSE
        IF NEW.actor_id IN (review.requested_by_id, run.created_by_id)
            OR NEW.reviewed_token IS DISTINCT FROM review.review_token OR NEW.outcome NOT IN ('approved','returned') THEN
            RAISE EXCEPTION 'Independent aggregate reviewer and matching token required' USING ERRCODE='23514';
        END IF;
        SELECT d.* INTO previous FROM calculations_resultdecision d
            JOIN calculations_resultreviewrequest rr ON rr.id=d.review_id
            JOIN calculations_storedsourceselection ss ON ss.run_id=rr.run_id
            WHERE d.outcome='approved' AND ss.round_instrument_id=selected ORDER BY d.created_at DESC, d.id DESC LIMIT 1;
        IF (NEW.outcome='approved' AND NEW.previous_approval_id IS DISTINCT FROM previous.id)
            OR (NEW.outcome='returned' AND NEW.previous_approval_id IS NOT NULL)
            OR EXISTS (SELECT 1 FROM calculations_resultreviewrequest rr JOIN calculations_calculationrun cr ON cr.id=rr.run_id
                       WHERE rr.id=previous.review_id AND (cr.cutoff>run.cutoff OR cr.created_at>run.created_at)) THEN
            RAISE EXCEPTION 'Retain the latest approval when creating a correction decision' USING ERRCODE='23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER stored_source_guard BEFORE INSERT OR UPDATE OR DELETE ON calculations_storedsourceselection
    FOR EACH ROW EXECUTE FUNCTION edpex_result_review_guard();
CREATE TRIGGER result_review_guard BEFORE INSERT OR UPDATE OR DELETE ON calculations_resultreviewrequest
    FOR EACH ROW EXECUTE FUNCTION edpex_result_review_guard();
CREATE TRIGGER result_decision_guard BEFORE INSERT OR UPDATE OR DELETE ON calculations_resultdecision
    FOR EACH ROW EXECUTE FUNCTION edpex_result_review_guard();
"""
REVERSE = """
DROP TRIGGER stored_source_guard ON calculations_storedsourceselection;
DROP TRIGGER result_review_guard ON calculations_resultreviewrequest;
DROP TRIGGER result_decision_guard ON calculations_resultdecision;
DROP FUNCTION edpex_result_review_guard();
"""


class Migration(migrations.Migration):
    dependencies = [('calculations', '0003_resultreviewrequest_storedsourceselection_and_more'),
                    ('accounts', '0004_self_assessment_result_permissions')]
    operations = [migrations.RunSQL(SQL, REVERSE)]
