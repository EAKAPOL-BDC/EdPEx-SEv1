"""Seal entire runs atomically and retain immutable history even through SQL."""
from django.db import migrations


FORWARD_SQL = r"""
CREATE FUNCTION edpex_calculation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    parent_run calculations_calculationrun;
    parent_source calculations_calculationinputsnapshot;
    round_scope uuid;
    pinned_population uuid;
    round_state text;
    actual_inputs bigint;
    actual_results bigint;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Calculation history is retained' USING ERRCODE='23514';
    END IF;
    IF TG_TABLE_NAME = 'calculations_calculationrun' THEN
        IF TG_OP = 'UPDATE' THEN
            IF OLD.status <> 'building' OR NEW.status <> 'complete'
                OR (to_jsonb(NEW) - ARRAY['status','sealed_at','result_hash','input_count','result_count'])
                   IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status','sealed_at','result_hash','input_count','result_count']) THEN
                RAISE EXCEPTION 'Sealed calculation runs are immutable' USING ERRCODE='23514';
            END IF;
            SELECT count(*) INTO actual_inputs FROM calculations_calculationinputsnapshot WHERE run_id=NEW.id;
            SELECT count(*) INTO actual_results FROM calculations_indicatorresult WHERE run_id=NEW.id;
            IF NEW.sealed_at IS NULL OR NEW.result_hash !~ '^[0-9a-f]{64}$'
                OR actual_inputs=0 OR actual_inputs<>actual_results
                OR NEW.input_count<>actual_inputs OR NEW.result_count<>actual_results
                OR jsonb_array_length(NEW.manifest->'sources') IS DISTINCT FROM actual_inputs THEN
                RAISE EXCEPTION 'Cannot seal an incomplete calculation run' USING ERRCODE='23514';
            END IF;
        ELSE
            SELECT scope_id, population_snapshot_id, status INTO round_scope, pinned_population, round_state
              FROM rounds_collectionround WHERE id=NEW.collection_round_id FOR UPDATE;
            IF NEW.status <> 'building' OR round_state NOT IN ('closed','review','approved')
                OR NEW.population_snapshot_id IS DISTINCT FROM pinned_population
                OR NOT EXISTS (SELECT 1 FROM rounds_populationsnapshot WHERE id=NEW.population_snapshot_id
                               AND collection_round_id=NEW.collection_round_id AND status='frozen') THEN
                RAISE EXCEPTION 'Calculation requires a closed round and its frozen population' USING ERRCODE='23514';
            END IF;
            IF NEW.manifest->>'round_id' IS DISTINCT FROM NEW.collection_round_id::text
                OR NEW.manifest->>'scope_id' IS DISTINCT FROM round_scope::text
                OR NEW.manifest->'population'->>'id' IS DISTINCT FROM NEW.population_snapshot_id::text
                OR NEW.manifest->'engine'->>'commit' IS DISTINCT FROM NEW.engine_commit
                OR NEW.manifest->'engine'->>'hash' IS DISTINCT FROM NEW.engine_hash
                OR jsonb_typeof(NEW.manifest->'sources') IS DISTINCT FROM 'array'
                OR NEW.engine_commit !~ '^[0-9a-f]{40}$' OR NEW.engine_hash !~ '^[0-9a-f]{64}$'
                OR NEW.input_hash !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'Invalid calculation manifest references' USING ERRCODE='23514';
            END IF;
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'Calculation snapshots are append-only' USING ERRCODE='23514';
    END IF;
    SELECT * INTO parent_run FROM calculations_calculationrun WHERE id=NEW.run_id FOR UPDATE;
    IF parent_run.id IS NULL THEN
        RAISE EXCEPTION 'Missing calculation parent' USING ERRCODE='23514';
    END IF;
    IF TG_TABLE_NAME = 'calculations_calculationrequest' THEN
        IF parent_run.status <> 'complete' OR parent_run.collection_round_id <> NEW.collection_round_id
            OR parent_run.input_hash <> NEW.request_hash OR btrim(NEW.idempotency_key)='' THEN
            RAISE EXCEPTION 'Idempotency receipt must match a complete run' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END IF;
    IF parent_run.status <> 'building' THEN
        RAISE EXCEPTION 'Cannot append to a sealed calculation run' USING ERRCODE='23514';
    END IF;
    IF TG_TABLE_NAME = 'calculations_calculationinputsnapshot' THEN
        IF NOT EXISTS (
            SELECT 1 FROM rounds_roundinstrument ri
              JOIN catalog_indicatorbinding b ON b.version_id=ri.instrument_version_id
              JOIN rounds_collectionround r ON r.id=ri.collection_round_id
              JOIN rounds_respondentgroup g ON g.scope_id=r.scope_id
             WHERE ri.id=NEW.round_instrument_id AND ri.collection_round_id=parent_run.collection_round_id
               AND b.id=NEW.binding_id AND g.id=NEW.group_id) THEN
            RAISE EXCEPTION 'Calculation input relations cross round or scope' USING ERRCODE='23514';
        END IF;
        IF NEW.series_key !~ '^[0-9a-f]{64}$' OR NEW.source_hash !~ '^[0-9a-f]{64}$'
            OR NEW.question_hash !~ '^[0-9a-f]{64}$' OR NEW.formula_hash !~ '^[0-9a-f]{64}$'
            OR jsonb_typeof(NEW.payload) IS DISTINCT FROM 'object'
            OR jsonb_typeof(NEW.definition) IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'Invalid calculation input schema' USING ERRCODE='23514';
        END IF;
    ELSE
        SELECT * INTO parent_source FROM calculations_calculationinputsnapshot WHERE id=NEW.source_id;
        IF parent_source.run_id IS DISTINCT FROM NEW.run_id OR parent_source.series_key IS DISTINCT FROM NEW.series_key
            OR parent_source.definition->'series'->>'indicator_code' IS DISTINCT FROM NEW.indicator_code
            OR NEW.result_hash !~ '^[0-9a-f]{64}$' OR jsonb_typeof(NEW.payload) IS DISTINCT FROM 'object'
            OR (NEW.payload->>'status') IS NULL
            OR (NEW.payload->>'status') NOT IN ('computed','no_valid_data','not_applicable',
                'insufficient_population_definition','suppressed','calculation_error') THEN
            RAISE EXCEPTION 'Result must match its source series' USING ERRCODE='23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER calc_run_guard BEFORE INSERT OR UPDATE OR DELETE ON calculations_calculationrun
FOR EACH ROW EXECUTE FUNCTION edpex_calculation_guard();
CREATE TRIGGER calc_input_guard BEFORE INSERT OR UPDATE OR DELETE ON calculations_calculationinputsnapshot
FOR EACH ROW EXECUTE FUNCTION edpex_calculation_guard();
CREATE TRIGGER calc_result_guard BEFORE INSERT OR UPDATE OR DELETE ON calculations_indicatorresult
FOR EACH ROW EXECUTE FUNCTION edpex_calculation_guard();
CREATE TRIGGER calc_request_guard BEFORE INSERT OR UPDATE OR DELETE ON calculations_calculationrequest
FOR EACH ROW EXECUTE FUNCTION edpex_calculation_guard();

CREATE FUNCTION edpex_calculation_must_seal() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM calculations_calculationrun WHERE id=NEW.id AND status<>'complete') THEN
        RAISE EXCEPTION 'Calculation transaction must seal its run before commit' USING ERRCODE='23514';
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER calc_run_must_seal AFTER INSERT OR UPDATE ON calculations_calculationrun
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION edpex_calculation_must_seal();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS calc_run_must_seal ON calculations_calculationrun;
DROP FUNCTION IF EXISTS edpex_calculation_must_seal();
DROP TRIGGER IF EXISTS calc_request_guard ON calculations_calculationrequest;
DROP TRIGGER IF EXISTS calc_result_guard ON calculations_indicatorresult;
DROP TRIGGER IF EXISTS calc_input_guard ON calculations_calculationinputsnapshot;
DROP TRIGGER IF EXISTS calc_run_guard ON calculations_calculationrun;
DROP FUNCTION IF EXISTS edpex_calculation_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("calculations", "0001_initial"), ("accounts", "0003_calculation_permissions")]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
