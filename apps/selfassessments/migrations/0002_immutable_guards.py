from django.db import migrations

SQL = r"""
CREATE FUNCTION edpex_self_report_guard() RETURNS trigger AS $$
DECLARE ri rounds_roundinstrument; r rounds_collectionround; member rounds_populationmember;
        a selfassessments_selfassessmentassignment; v catalog_instrumentversion;
        group_code text; prior integer; prior_time timestamptz; q catalog_question;
        answer record; state text;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Self-report history is append-only' USING ERRCODE='23514';
    END IF;
    IF TG_TABLE_NAME = 'selfassessments_selfassessmentassignment' THEN
        SELECT * INTO ri FROM rounds_roundinstrument WHERE id=NEW.round_instrument_id;
        SELECT * INTO r FROM rounds_collectionround WHERE id=ri.collection_round_id FOR UPDATE;
        SELECT * INTO member FROM rounds_populationmember WHERE id=NEW.member_id;
        SELECT code INTO group_code FROM rounds_respondentgroup WHERE id=member.group_id AND scope_id=r.scope_id;
        SELECT * INTO v FROM catalog_instrumentversion WHERE id=ri.instrument_version_id;
        IF r.id IS NULL OR r.status <> 'ready' OR member.snapshot_id IS DISTINCT FROM r.population_snapshot_id
            OR group_code IS NULL OR group_code NOT IN ('ST1','ST2') OR v.status <> 'published'
            OR v.assessment_method <> 'self_report' OR v.evidence_required OR v.assessor_scoring
            OR NOT EXISTS (SELECT 1 FROM catalog_instrument WHERE id=v.instrument_id AND code='F06')
            OR NOT EXISTS (SELECT 1 FROM accounts_membership m JOIN auth_user u ON u.id=m.user_id
                           WHERE m.user_id=NEW.user_id AND m.organization_id=r.organization_id AND m.is_active AND u.is_active)
            OR btrim(NEW.duties)='' OR length(NEW.duties)>4000 THEN
            RAISE EXCEPTION 'Invalid F06 owner or pre-opening assignment' USING ERRCODE='23514';
        END IF;
        IF jsonb_typeof(NEW.expected_levels) IS DISTINCT FROM 'object'
            OR jsonb_typeof(NEW.applicable_question_ids) IS DISTINCT FROM 'array' THEN
            RAISE EXCEPTION 'Freeze typed expected levels and applicability' USING ERRCODE='23514';
        END IF;
        IF EXISTS (SELECT 1 FROM jsonb_each(NEW.expected_levels) x WHERE jsonb_typeof(x.value)<>'number'
                    OR x.value::text !~ '^[1-5]$')
            OR (SELECT count(*) FROM jsonb_object_keys(NEW.expected_levels)) <>
               (SELECT count(*) FROM catalog_question WHERE version_id=v.id AND active AND group_codes ? group_code AND answer_type='integer_scale')
            OR EXISTS (SELECT 1 FROM catalog_question WHERE version_id=v.id AND active AND group_codes ? group_code
                       AND answer_type='integer_scale' AND NOT NEW.expected_levels ? question_id)
            OR EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.applicable_question_ids) x
                WHERE jsonb_typeof(x)<>'string' OR NOT EXISTS (SELECT 1 FROM catalog_question q
                    WHERE q.version_id=v.id AND q.active AND q.group_codes ? group_code AND q.question_id=x #>> '{}'
                      AND q.question_id !~ '^F06-P0[1-5]$'))
            OR (SELECT count(*) FROM jsonb_array_elements(NEW.applicable_question_ids)) <>
               (SELECT count(DISTINCT x) FROM jsonb_array_elements(NEW.applicable_question_ids) x)
            OR EXISTS (SELECT 1 FROM catalog_question q WHERE q.version_id=v.id AND q.active AND q.group_codes ? group_code
                AND q.question_id !~ '^F06-P0[1-5]$' AND q.question_id !~ '^F06-[MT]'
                AND NOT NEW.applicable_question_ids ? q.question_id) THEN
            RAISE EXCEPTION 'Assignment questions or expected levels differ from the published group schema' USING ERRCODE='23514';
        END IF;
    ELSE
        SELECT * INTO a FROM selfassessments_selfassessmentassignment WHERE id=NEW.assignment_id;
        SELECT * INTO ri FROM rounds_roundinstrument WHERE id=a.round_instrument_id;
        SELECT * INTO r FROM rounds_collectionround WHERE id=ri.collection_round_id FOR UPDATE;
        SELECT g.code INTO group_code FROM rounds_populationmember m JOIN rounds_respondentgroup g ON g.id=m.group_id WHERE m.id=a.member_id;
        SELECT revision, recorded_at INTO prior, prior_time FROM selfassessments_selfassessmentrevision
            WHERE assignment_id=a.id ORDER BY revision DESC LIMIT 1;
        IF a.id IS NULL OR r.status <> 'open' OR NEW.recorded_at<r.open_at OR NEW.recorded_at>=r.close_at
            OR clock_timestamp()<r.open_at OR clock_timestamp()>=r.close_at OR NEW.recorded_at>clock_timestamp()
            OR NEW.revision<>COALESCE(prior,0)+1 OR NEW.recorded_at<prior_time
            OR NEW.status NOT IN ('draft','submitted') OR NEW.completeness NOT IN ('partial','complete')
            OR btrim(NEW.idempotency_key)='' OR NEW.request_hash !~ '^[0-9a-f]{64}$'
            OR jsonb_typeof(NEW.answers) IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'Invalid self-report revision or closed collection window' USING ERRCODE='23514';
        END IF;
        FOR answer IN SELECT * FROM jsonb_each(NEW.answers) LOOP
            SELECT * INTO q FROM catalog_question WHERE version_id=ri.instrument_version_id AND active
                AND question_id=answer.key AND group_codes ? group_code AND question_id !~ '^F06-P0[1-5]$';
            state := answer.value->>'status';
            IF q.id IS NULL OR jsonb_typeof(answer.value) IS DISTINCT FROM 'object'
                OR state IS NULL OR state NOT IN ('answered','missing','skipped','not_applicable','unable_to_assess','not_shown')
                OR answer.value - ARRAY['status','value','reason','example','development_plan'] <> '{}'::jsonb
                OR (a.applicable_question_ids ? answer.key AND state='not_shown')
                OR (NOT a.applicable_question_ids ? answer.key AND answer.value <> '{"status":"not_shown"}'::jsonb) THEN
                RAISE EXCEPTION 'Invalid self-report question or payload field' USING ERRCODE='23514';
            END IF;
            IF state='answered' AND q.answer_type='integer_scale' AND (
                jsonb_typeof(answer.value->'value') IS DISTINCT FROM 'number' OR answer.value->>'value' !~ '^[1-5]$'
                OR NOT EXISTS (SELECT 1 FROM catalog_questionoption o WHERE o.question_id=q.id AND o.answer_status='answered'
                               AND o.score=(answer.value->>'value')::numeric)) THEN
                RAISE EXCEPTION 'Invalid self-report score' USING ERRCODE='23514';
            END IF;
            IF state='not_applicable' AND answer.key ~ '^F06-[MT]' AND btrim(COALESCE(answer.value->>'reason',''))='' THEN
                RAISE EXCEPTION 'Not-applicable dimensions require a reason' USING ERRCODE='23514';
            END IF;
            IF state<>'answered' AND answer.value ? 'value' AND answer.value->'value'<>'null'::jsonb THEN
                RAISE EXCEPTION 'Non-score states cannot contain a score' USING ERRCODE='23514';
            END IF;
        END LOOP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER self_assignment_guard BEFORE INSERT OR UPDATE OR DELETE ON selfassessments_selfassessmentassignment
    FOR EACH ROW EXECUTE FUNCTION edpex_self_report_guard();
CREATE TRIGGER self_revision_guard BEFORE INSERT OR UPDATE OR DELETE ON selfassessments_selfassessmentrevision
    FOR EACH ROW EXECUTE FUNCTION edpex_self_report_guard();
"""
REVERSE = """
DROP TRIGGER self_revision_guard ON selfassessments_selfassessmentrevision;
DROP TRIGGER self_assignment_guard ON selfassessments_selfassessmentassignment;
DROP FUNCTION edpex_self_report_guard();
"""


class Migration(migrations.Migration):
    dependencies = [('selfassessments', '0001_initial'), ('accounts', '0004_self_assessment_result_permissions')]
    operations = [migrations.RunSQL(SQL, REVERSE)]
