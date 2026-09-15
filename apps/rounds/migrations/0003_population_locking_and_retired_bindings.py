"""Coordinate population mutations with freeze and retain historic bindings.

Adds guards to databases that already applied M1 0002. PostgreSQL runs BEFORE
triggers in name order: population locks precede the original guards; the
retirement guard follows the original round lock.
"""

from django.db import migrations


FORWARD_SQL = r"""
CREATE FUNCTION edpex_population_member_lock() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    parent_ids uuid[];
    parent_row record;
    locked_count integer := 0;
BEGIN
    IF TG_OP = 'INSERT' THEN
        parent_ids := ARRAY[NEW.snapshot_id];
    ELSIF TG_OP = 'DELETE' THEN
        parent_ids := ARRAY[OLD.snapshot_id];
    ELSE
        SELECT array_agg(DISTINCT parent_id) INTO parent_ids
          FROM unnest(ARRAY[OLD.snapshot_id, NEW.snapshot_id]) AS parent_id;
    END IF;
    -- UPDATE/DELETE already hold the member tuple lock. Lock BOTH parents in
    -- UUID order; FOR UPDATE waits and returns the current committed status.
    FOR parent_row IN
        SELECT id, status FROM rounds_populationsnapshot
        WHERE id = ANY(parent_ids) ORDER BY id FOR UPDATE
    LOOP
        locked_count := locked_count + 1;
        IF parent_row.status = 'frozen' THEN
            RAISE EXCEPTION 'Frozen population membership cannot change' USING ERRCODE = '23514';
        END IF;
    END LOOP;
    IF locked_count <> cardinality(parent_ids) THEN
        RAISE EXCEPTION 'Population snapshot does not exist' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER edpex_population_member_lock
BEFORE INSERT OR UPDATE OR DELETE ON rounds_populationmember
FOR EACH ROW EXECUTE FUNCTION edpex_population_member_lock();

CREATE FUNCTION edpex_population_roster_count() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    require_roster boolean;
BEGIN
    IF NEW.status = 'frozen' THEN
        -- This UPDATE owns the snapshot row lock before entering the trigger.
        -- A raw source promises a complete roster even when its last member
        -- moved away. Aggregate-only sources may legitimately have no roster.
        SELECT source_type = 'raw' INTO require_roster
          FROM rounds_datasource WHERE id = NEW.source_id;
        IF require_roster OR EXISTS (
            SELECT 1 FROM rounds_populationmember WHERE snapshot_id = NEW.id
        ) THEN
            IF EXISTS (
                SELECT 1 FROM jsonb_each(NEW.counts_by_group) e
                WHERE e.value IS DISTINCT FROM to_jsonb((
                    SELECT count(*) FROM rounds_populationmember m
                    JOIN rounds_respondentgroup g ON g.id = m.group_id
                    WHERE m.snapshot_id = NEW.id AND g.code = e.key
                ))
            ) OR EXISTS (
                SELECT 1 FROM rounds_populationmember m
                JOIN rounds_respondentgroup g ON g.id = m.group_id
                WHERE m.snapshot_id = NEW.id AND NOT NEW.counts_by_group ? g.code
            ) THEN
                RAISE EXCEPTION 'Frozen roster must match declared population counts' USING ERRCODE = '23514';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER edpex_population_roster_count
BEFORE UPDATE ON rounds_populationsnapshot
FOR EACH ROW EXECUTE FUNCTION edpex_population_roster_count();

CREATE FUNCTION edpex_round_binding_retirement_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    version_status text;
BEGIN
    IF TG_OP = 'INSERT' OR
       ROW(NEW.collection_round_id, NEW.instrument_version_id, NEW.translation_bundle_id)
       IS DISTINCT FROM ROW(OLD.collection_round_id, OLD.instrument_version_id, OLD.translation_bundle_id) THEN
        SELECT status INTO version_status FROM catalog_instrumentversion
          WHERE id = NEW.instrument_version_id FOR UPDATE;
        IF version_status = 'retired' THEN
            RAISE EXCEPTION 'Retired versions cannot be selected for new round bindings' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

-- Run after edpex_rounds_invariants: both raw SQL and the ORM acquire round
-- before version locks, avoiding a version/round lock-order inversion.
CREATE TRIGGER edpex_rounds_retirement_guard
BEFORE INSERT OR UPDATE ON rounds_roundinstrument
FOR EACH ROW EXECUTE FUNCTION edpex_round_binding_retirement_guard();
"""

REVERSE_SQL = r"""
DROP TRIGGER edpex_rounds_retirement_guard ON rounds_roundinstrument;
DROP FUNCTION edpex_round_binding_retirement_guard();
DROP TRIGGER edpex_population_roster_count ON rounds_populationsnapshot;
DROP FUNCTION edpex_population_roster_count();
DROP TRIGGER edpex_population_member_lock ON rounds_populationmember;
DROP FUNCTION edpex_population_member_lock();
"""


class Migration(migrations.Migration):
    dependencies = [("rounds", "0002_postgresql_guards")]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
