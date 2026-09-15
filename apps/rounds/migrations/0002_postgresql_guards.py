"""PostgreSQL invariants frozen in Django migration history."""
from django.db import migrations

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION edpex_rounds_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    linked_scope uuid;
    linked_organization uuid;
    state text;
    previous_state text;
    ref record;
    member_count bigint;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF TG_TABLE_NAME IN ('rounds_datasource', 'rounds_responsibilityassignment') THEN
            RAISE EXCEPTION 'Source and responsibility history cannot be deleted' USING ERRCODE = '23514';
        ELSIF TG_TABLE_NAME = 'rounds_reportingperiod' THEN
            IF OLD.approved THEN
                RAISE EXCEPTION 'Approved periods are immutable' USING ERRCODE = '23514';
            END IF;
        ELSIF TG_TABLE_NAME = 'rounds_collectionround' THEN
            IF OLD.status <> 'draft' THEN
                RAISE EXCEPTION 'Used rounds cannot be deleted' USING ERRCODE = '23514';
            END IF;
        ELSIF TG_TABLE_NAME = 'rounds_populationsnapshot' THEN
            IF OLD.status = 'frozen' THEN
                RAISE EXCEPTION 'Frozen populations cannot be deleted' USING ERRCODE = '23514';
            END IF;
        ELSIF TG_TABLE_NAME = 'rounds_respondentgroup' THEN
            IF EXISTS (SELECT 1 FROM rounds_populationsnapshot s JOIN rounds_collectionround r ON r.id = s.collection_round_id
                       WHERE r.scope_id = OLD.scope_id AND s.counts_by_group ? OLD.code) THEN
                RAISE EXCEPTION 'Population count group definitions cannot be deleted' USING ERRCODE = '23514';
            END IF;
        ELSIF TG_TABLE_NAME = 'rounds_populationmember' THEN
            SELECT status INTO state FROM rounds_populationsnapshot WHERE id = OLD.snapshot_id FOR UPDATE;
            IF state = 'frozen' THEN
                RAISE EXCEPTION 'Frozen population members cannot be deleted' USING ERRCODE = '23514';
            END IF;
        ELSIF TG_TABLE_NAME = 'rounds_roundinstrument' THEN
            SELECT status INTO state FROM rounds_collectionround WHERE id = OLD.collection_round_id FOR UPDATE;
            IF state <> 'draft' THEN
                RAISE EXCEPTION 'Used round bindings cannot be deleted' USING ERRCODE = '23514';
            END IF;
        END IF;
        RETURN OLD;
    END IF;

    IF TG_TABLE_NAME IN ('rounds_calendar', 'rounds_collectionround', 'rounds_respondentgroup',
                          'rounds_responsibilityassignment', 'rounds_datasource') THEN
        linked_scope := NEW.scope_id;
    ELSIF TG_TABLE_NAME = 'rounds_reportingperiod' THEN
        SELECT scope_id INTO linked_scope FROM rounds_calendar WHERE id = NEW.calendar_id FOR UPDATE;
    ELSIF TG_TABLE_NAME IN ('rounds_roundinstrument', 'rounds_populationsnapshot') THEN
        SELECT scope_id, status INTO linked_scope, state FROM rounds_collectionround WHERE id = NEW.collection_round_id FOR UPDATE;
    ELSIF TG_TABLE_NAME = 'rounds_populationmember' THEN
        SELECT s.status, r.scope_id INTO state, linked_scope
        FROM rounds_populationsnapshot s JOIN rounds_collectionround r ON r.id = s.collection_round_id
        WHERE s.id = NEW.snapshot_id FOR UPDATE OF s;
    END IF;
    SELECT organization_id INTO linked_organization FROM accounts_accessscope WHERE id = linked_scope;
    IF linked_organization IS NULL OR NEW.organization_id IS DISTINCT FROM linked_organization THEN
        RAISE EXCEPTION 'Business organization must match its access scope' USING ERRCODE = '23514';
    END IF;

    IF TG_TABLE_NAME = 'rounds_calendar' THEN
        IF NEW.calendar_type NOT IN ('fiscal', 'academic', 'calendar', 'custom') THEN
            RAISE EXCEPTION 'Unsupported calendar type' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'UPDATE' AND EXISTS (SELECT 1 FROM rounds_reportingperiod WHERE calendar_id = OLD.id)
            AND (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM (to_jsonb(OLD) - 'updated_at') THEN
            RAISE EXCEPTION 'A calendar used by periods is immutable' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'rounds_reportingperiod' THEN
        IF TG_OP = 'UPDATE' AND OLD.approved
            AND (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM (to_jsonb(OLD) - 'updated_at') THEN
            RAISE EXCEPTION 'Approved periods are immutable' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'UPDATE' AND (
            EXISTS (SELECT 1 FROM rounds_reportingperiod WHERE parent_id = OLD.id) OR
            EXISTS (SELECT 1 FROM rounds_collectionround WHERE period_id = OLD.id))
            AND (to_jsonb(NEW) - ARRAY['updated_at','approved','approved_by_id','approved_at'])
                IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['updated_at','approved','approved_by_id','approved_at']) THEN
            RAISE EXCEPTION 'Referenced period dates and identity are immutable' USING ERRCODE = '23514';
        END IF;
        IF NEW.parent_id IS NOT NULL THEN
            SELECT * INTO ref FROM rounds_reportingperiod WHERE id = NEW.parent_id;
            IF ref.id IS NULL OR ref.id = NEW.id OR ref.calendar_id <> NEW.calendar_id OR ref.parent_id IS NOT NULL
                OR ref.reporting_year_be <> NEW.reporting_year_be OR NEW.start_date < ref.start_date OR NEW.end_date > ref.end_date THEN
                RAISE EXCEPTION 'Child period must belong to and fit its parent year' USING ERRCODE = '23514';
            END IF;
        END IF;
        IF EXISTS (SELECT 1 FROM rounds_reportingperiod p
                   WHERE p.calendar_id = NEW.calendar_id AND p.parent_id IS NOT DISTINCT FROM NEW.parent_id
                     AND p.id <> NEW.id AND p.code <> NEW.code
                     AND p.start_date < NEW.end_date AND p.end_date > NEW.start_date) THEN
            RAISE EXCEPTION 'Sibling reporting periods overlap' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'rounds_collectionround' THEN
        SELECT c.scope_id, p.approved INTO ref FROM rounds_reportingperiod p
          JOIN rounds_calendar c ON c.id = p.calendar_id WHERE p.id = NEW.period_id FOR UPDATE OF p;
        IF ref.scope_id IS DISTINCT FROM NEW.scope_id THEN
            RAISE EXCEPTION 'Round and calendar scopes differ' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'INSERT' AND NEW.status <> 'draft' THEN
            RAISE EXCEPTION 'Rounds must start as drafts' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'UPDATE' THEN
            IF NEW.scope_id <> OLD.scope_id OR (NEW.period_id <> OLD.period_id AND (
                EXISTS (SELECT 1 FROM rounds_roundinstrument WHERE collection_round_id = OLD.id) OR
                EXISTS (SELECT 1 FROM rounds_populationsnapshot WHERE collection_round_id = OLD.id) OR
                EXISTS (SELECT 1 FROM rounds_responsibilityassignment WHERE collection_round_id = OLD.id))) THEN
                RAISE EXCEPTION 'Round scope is stable and referenced period cannot change' USING ERRCODE = '23514';
            END IF;
            IF OLD.status <> 'draft' AND (to_jsonb(NEW) - ARRAY['updated_at','status'])
                 IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['updated_at','status']) THEN
                RAISE EXCEPTION 'Activated round configuration is frozen' USING ERRCODE = '23514';
            END IF;
            IF NEW.status <> OLD.status AND NOT (
                 (OLD.status = 'draft' AND NEW.status = 'ready') OR
                 (OLD.status = 'ready' AND NEW.status IN ('draft', 'open')) OR
                 (OLD.status = 'open' AND NEW.status = 'closed')) THEN
                RAISE EXCEPTION 'Unsupported M1 round transition' USING ERRCODE = '23514';
            END IF;
        END IF;
        IF NEW.population_snapshot_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM rounds_populationsnapshot WHERE id = NEW.population_snapshot_id
              AND collection_round_id = NEW.id AND status = 'frozen') THEN
            RAISE EXCEPTION 'Pinned population must be frozen and belong to this round' USING ERRCODE = '23514';
        END IF;
        IF NEW.status IN ('ready', 'open') THEN
            IF NOT ref.approved OR NEW.privacy_notice = '' OR NEW.population_snapshot_id IS NULL
                OR NOT EXISTS (SELECT 1 FROM rounds_roundinstrument WHERE collection_round_id = NEW.id)
                OR EXISTS (SELECT 1 FROM rounds_roundinstrument b
                    JOIN catalog_instrumentversion v ON v.id = b.instrument_version_id
                    JOIN catalog_translationbundle t ON t.id = b.translation_bundle_id
                    WHERE b.collection_round_id = NEW.id AND (v.status <> 'published' OR t.status <> 'published')) THEN
                RAISE EXCEPTION 'Round lacks approved period, population, instrument or translations' USING ERRCODE = '23514';
            END IF;
        END IF;
    ELSIF TG_TABLE_NAME = 'rounds_roundinstrument' THEN
        IF state <> 'draft' AND (TG_OP = 'INSERT' OR (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM (to_jsonb(OLD) - 'updated_at')) THEN
            RAISE EXCEPTION 'Round bindings are frozen after draft' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'UPDATE' THEN
            SELECT status INTO previous_state FROM rounds_collectionround WHERE id = OLD.collection_round_id;
            IF previous_state <> 'draft' AND (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM (to_jsonb(OLD) - 'updated_at') THEN
                RAISE EXCEPTION 'Cannot move bindings out of a used round' USING ERRCODE = '23514';
            END IF;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM catalog_instrumentversion v
                       JOIN catalog_instrument i ON i.id = v.instrument_id
                       JOIN catalog_translationbundle t ON t.instrument_version_id = v.id
                       WHERE v.id = NEW.instrument_version_id AND i.scope_id = linked_scope AND t.id = NEW.translation_bundle_id)
            OR NEW.configuration <> '{}'::jsonb THEN
            RAISE EXCEPTION 'Invalid instrument scope, bundle or unvalidated override' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'rounds_populationsnapshot' THEN
        IF TG_OP = 'UPDATE' AND NEW.collection_round_id <> OLD.collection_round_id THEN
            RAISE EXCEPTION 'A population snapshot cannot move between rounds' USING ERRCODE = '23514';
        END IF;
        IF NEW.source_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM rounds_datasource WHERE id = NEW.source_id AND scope_id = linked_scope) THEN
            RAISE EXCEPTION 'Population provenance belongs to another access scope' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'UPDATE' AND OLD.status = 'frozen'
            AND (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM (to_jsonb(OLD) - 'updated_at') THEN
            RAISE EXCEPTION 'Frozen populations are immutable' USING ERRCODE = '23514';
        END IF;
        IF state NOT IN ('draft', 'ready') AND (TG_OP = 'INSERT'
            OR (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM (to_jsonb(OLD) - 'updated_at')) THEN
            RAISE EXCEPTION 'Opened rounds cannot acquire changed populations' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'INSERT' AND NEW.status <> 'draft' THEN
            RAISE EXCEPTION 'Population snapshots must start as drafts' USING ERRCODE = '23514';
        END IF;
        IF jsonb_typeof(NEW.counts_by_group) <> 'object' OR EXISTS (
            SELECT 1 FROM jsonb_each(NEW.counts_by_group) e
              WHERE jsonb_typeof(e.value) <> 'number' OR e.value::text !~ '^[0-9]+$'
                OR NOT EXISTS (SELECT 1 FROM rounds_respondentgroup g WHERE g.scope_id = linked_scope AND g.code = e.key)) THEN
            RAISE EXCEPTION 'Population counts must be real nonnegative integers for this scope groups' USING ERRCODE = '23514';
        END IF;
        IF NEW.status = 'frozen' THEN
            IF NEW.source_id IS NULL THEN
                RAISE EXCEPTION 'Frozen population requires actual source provenance' USING ERRCODE = '23514';
            END IF;
            SELECT count(*) INTO member_count FROM rounds_populationmember WHERE snapshot_id = NEW.id;
            IF NEW.counts_by_group = '{}'::jsonb OR (member_count > 0 AND (
                EXISTS (SELECT 1 FROM jsonb_each(NEW.counts_by_group) e WHERE (e.value::text)::bigint <>
                    (SELECT count(*) FROM rounds_populationmember m JOIN rounds_respondentgroup g ON g.id = m.group_id
                     WHERE m.snapshot_id = NEW.id AND g.code = e.key)) OR
                EXISTS (SELECT 1 FROM rounds_populationmember m JOIN rounds_respondentgroup g ON g.id = m.group_id
                        WHERE m.snapshot_id = NEW.id AND NOT NEW.counts_by_group ? g.code))) THEN
                RAISE EXCEPTION 'Frozen population members must match their defined counts' USING ERRCODE = '23514';
            END IF;
        END IF;
    ELSIF TG_TABLE_NAME = 'rounds_populationmember' THEN
        IF state = 'frozen' AND (TG_OP = 'INSERT' OR (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM (to_jsonb(OLD) - 'updated_at')) THEN
            RAISE EXCEPTION 'Frozen population members are immutable' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'UPDATE' THEN
            SELECT status INTO previous_state FROM rounds_populationsnapshot WHERE id = OLD.snapshot_id;
            IF previous_state = 'frozen' AND (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM (to_jsonb(OLD) - 'updated_at') THEN
                RAISE EXCEPTION 'Cannot move members out of a frozen population' USING ERRCODE = '23514';
            END IF;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM rounds_respondentgroup WHERE id = NEW.group_id AND scope_id = linked_scope)
            OR jsonb_typeof(NEW.employment_facts) <> 'object' THEN
            RAISE EXCEPTION 'Population member has invalid group scope or employment facts' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'rounds_respondentgroup' THEN
        IF TG_OP = 'UPDATE' AND (NEW.scope_id <> OLD.scope_id OR NEW.code <> OLD.code) THEN
            RAISE EXCEPTION 'Respondent group scope and stable code cannot change' USING ERRCODE = '23514';
        END IF;
        IF NEW.parent_id IS NOT NULL AND (NOT EXISTS (SELECT 1 FROM rounds_respondentgroup WHERE id = NEW.parent_id AND scope_id = NEW.scope_id)
            OR EXISTS (WITH RECURSIVE ancestors AS (
                SELECT id, parent_id FROM rounds_respondentgroup WHERE id = NEW.parent_id
                UNION SELECT g.id, g.parent_id FROM rounds_respondentgroup g JOIN ancestors a ON g.id = a.parent_id)
                SELECT 1 FROM ancestors WHERE id = NEW.id)) THEN
            RAISE EXCEPTION 'Group hierarchy must remain in scope and acyclic' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'UPDATE' AND (EXISTS (SELECT 1 FROM rounds_populationmember WHERE group_id = OLD.id) OR
            EXISTS (SELECT 1 FROM rounds_populationsnapshot s JOIN rounds_collectionround r ON r.id = s.collection_round_id
                    WHERE r.scope_id = OLD.scope_id AND s.counts_by_group ? OLD.code))
            AND (to_jsonb(NEW) - ARRAY['updated_at','active']) IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['updated_at','active']) THEN
            RAISE EXCEPTION 'Referenced respondent group identity is immutable' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'rounds_responsibilityassignment' THEN
        IF NEW.collection_round_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM rounds_collectionround WHERE id = NEW.collection_round_id AND scope_id = NEW.scope_id) THEN
            RAISE EXCEPTION 'Responsibility and round scopes differ' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'UPDATE' AND (
            (to_jsonb(NEW) - ARRAY['updated_at','active_until']) IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['updated_at','active_until'])
            OR (OLD.active_until IS NOT NULL AND NEW.active_until IS DISTINCT FROM OLD.active_until)) THEN
            RAISE EXCEPTION 'Responsibility history is immutable except first ending time' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'rounds_datasource' THEN
        IF NEW.source_type NOT IN ('raw', 'aggregate') THEN
            RAISE EXCEPTION 'Unsupported source type' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'UPDATE' AND (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM (to_jsonb(OLD) - 'updated_at') THEN
            RAISE EXCEPTION 'Source provenance is append-only' USING ERRCODE = '23514';
        END IF;
        IF NEW.supersedes_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM rounds_datasource WHERE id = NEW.supersedes_id AND scope_id = NEW.scope_id AND revision = NEW.revision - 1) THEN
            RAISE EXCEPTION 'Source revision must extend the same scope lineage' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DO $$ DECLARE table_name text; BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'rounds_calendar','rounds_reportingperiod','rounds_collectionround','rounds_roundinstrument',
        'rounds_respondentgroup','rounds_populationsnapshot','rounds_populationmember',
        'rounds_responsibilityassignment','rounds_datasource'] LOOP
        EXECUTE format('CREATE TRIGGER edpex_rounds_invariants BEFORE INSERT OR UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION edpex_rounds_guard()', table_name);
    END LOOP;
END $$;
"""

REVERSE_SQL = r"""
DO $$ DECLARE table_name text; BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'rounds_calendar','rounds_reportingperiod','rounds_collectionround','rounds_roundinstrument',
        'rounds_respondentgroup','rounds_populationsnapshot','rounds_populationmember',
        'rounds_responsibilityassignment','rounds_datasource'] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS edpex_rounds_invariants ON %I', table_name);
    END LOOP;
END $$;
DROP FUNCTION IF EXISTS edpex_rounds_guard();
"""

class Migration(migrations.Migration):
    dependencies = [("rounds", "0001_initial"), ("catalog", "0002_postgresql_guards")]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
