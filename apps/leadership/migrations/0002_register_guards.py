"""Protect fiscal segments and frozen rosters at the PostgreSQL boundary."""
from django.db import migrations

SQL = r"""
CREATE FUNCTION nexora_f04_register_guard() RETURNS trigger AS $$
DECLARE scope_org uuid; t leadership_annualtarget; pos leadership_position;
        p leadership_annualplan; per rounds_reportingperiod; cal rounds_calendar;
BEGIN
    IF TG_OP='DELETE' THEN
        IF TG_TABLE_NAME='leadership_eligibility' THEN
            SELECT * INTO t FROM leadership_annualtarget WHERE id=OLD.target_id FOR UPDATE;
            IF t.status='draft' THEN RETURN OLD; END IF;
        END IF;
        RAISE EXCEPTION 'F04 register history is retained' USING ERRCODE='23514';
    END IF;
    SELECT organization_id INTO scope_org FROM accounts_accessscope WHERE id=NEW.scope_id FOR UPDATE;
    IF scope_org IS DISTINCT FROM NEW.organization_id THEN RAISE EXCEPTION 'F04 organization mismatch' USING ERRCODE='23514'; END IF;
    IF TG_OP='UPDATE' AND (NEW.scope_id<>OLD.scope_id OR NEW.organization_id<>OLD.organization_id) THEN
        RAISE EXCEPTION 'Stable F04 scope' USING ERRCODE='23514';
    END IF;
    IF TG_TABLE_NAME IN ('leadership_person','leadership_programme','leadership_position') AND TG_OP='UPDATE' THEN
        IF NEW.code<>OLD.code THEN RAISE EXCEPTION 'Stable F04 code' USING ERRCODE='23514'; END IF;
    END IF;
    IF TG_TABLE_NAME='leadership_person' THEN
        IF NEW.user_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM accounts_membership WHERE user_id=NEW.user_id AND organization_id=scope_org) THEN
            RAISE EXCEPTION 'F04 person account mismatch' USING ERRCODE='23514'; END IF;
    ELSIF TG_TABLE_NAME='leadership_position' THEN
        IF NEW.programme_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM leadership_programme WHERE id=NEW.programme_id AND scope_id=NEW.scope_id) THEN
            RAISE EXCEPTION 'F04 programme scope mismatch' USING ERRCODE='23514'; END IF;
        IF TG_OP='UPDATE' AND (NEW.role<>OLD.role OR NEW.programme_id IS DISTINCT FROM OLD.programme_id) AND EXISTS(SELECT 1 FROM leadership_annualtarget WHERE position_id=OLD.id) THEN
            RAISE EXCEPTION 'Used F04 position identity is stable' USING ERRCODE='23514'; END IF;
    ELSIF TG_TABLE_NAME='leadership_annualplan' THEN
        IF TG_OP='UPDATE' AND (to_jsonb(NEW)-'updated_at')<>(to_jsonb(OLD)-'updated_at') THEN
            RAISE EXCEPTION 'F04 year is immutable' USING ERRCODE='23514'; END IF;
        SELECT * INTO per FROM rounds_reportingperiod WHERE id=NEW.period_id;
        SELECT * INTO cal FROM rounds_calendar WHERE id=per.calendar_id;
        IF cal.scope_id IS DISTINCT FROM NEW.scope_id OR cal.calendar_type<>'fiscal' OR NOT per.approved OR per.parent_id IS NOT NULL
           OR NEW.fiscal_year<2565 OR NEW.fiscal_year>3000 OR per.reporting_year_be<>NEW.fiscal_year
           OR per.start_date<>make_date(NEW.fiscal_year-544,10,1) OR per.end_date<>make_date(NEW.fiscal_year-543,10,1) THEN
            RAISE EXCEPTION 'Approved full fiscal year required' USING ERRCODE='23514'; END IF;
    ELSIF TG_TABLE_NAME='leadership_annualtarget' THEN
        SELECT * INTO p FROM leadership_annualplan WHERE id=NEW.plan_id;
        SELECT * INTO pos FROM leadership_position WHERE id=NEW.position_id;
        IF p.scope_id IS DISTINCT FROM NEW.scope_id OR pos.scope_id IS DISTINCT FROM NEW.scope_id
           OR NOT EXISTS(SELECT 1 FROM leadership_person WHERE id=NEW.person_id AND scope_id=NEW.scope_id)
           OR NEW.start_date<make_date(p.fiscal_year-544,10,1) OR NEW.end_date>make_date(p.fiscal_year-543,10,1) THEN
            RAISE EXCEPTION 'F04 target scope or fiscal dates mismatch' USING ERRCODE='23514'; END IF;
        IF TG_OP='INSERT' AND NEW.status<>'draft' THEN RAISE EXCEPTION 'Start with a draft F04 target' USING ERRCODE='23514'; END IF;
        IF TG_OP='UPDATE' THEN
            IF NEW.plan_id<>OLD.plan_id THEN RAISE EXCEPTION 'Stable F04 target year' USING ERRCODE='23514'; END IF;
            IF OLD.status IN ('superseded','exempt') AND (to_jsonb(NEW)-'updated_at')<>(to_jsonb(OLD)-'updated_at') THEN
                RAISE EXCEPTION 'Terminal F04 target retained' USING ERRCODE='23514'; END IF;
            IF OLD.status='ready' AND ((to_jsonb(NEW)-ARRAY['status','status_reason','updated_at'])<>(to_jsonb(OLD)-ARRAY['status','status_reason','updated_at']) OR NEW.status NOT IN ('ready','superseded')) THEN
                RAISE EXCEPTION 'Frozen F04 target is immutable' USING ERRCODE='23514'; END IF;
        END IF;
        IF NEW.status='draft' AND (NEW.snapshot<>'{}'::jsonb OR NEW.frozen_by_id IS NOT NULL OR NEW.frozen_at IS NOT NULL) THEN
            RAISE EXCEPTION 'Draft target cannot claim a frozen snapshot' USING ERRCODE='23514'; END IF;
        IF NEW.status='ready' AND (NEW.frozen_by_id IS NULL OR NEW.frozen_at IS NULL OR NEW.snapshot->>'target_id' IS DISTINCT FROM NEW.id::text
            OR NEW.snapshot->>'person_id' IS DISTINCT FROM NEW.person_id::text OR NEW.snapshot->>'position_id' IS DISTINCT FROM NEW.position_id::text
            OR NEW.snapshot->>'role' IS DISTINCT FROM pos.role OR NOT EXISTS(SELECT 1 FROM leadership_eligibility WHERE target_id=NEW.id)) THEN
            RAISE EXCEPTION 'Ready target needs a frozen snapshot and explicit roster' USING ERRCODE='23514'; END IF;
        IF NEW.status IN ('superseded','exempt') AND btrim(NEW.status_reason)='' THEN
            RAISE EXCEPTION 'F04 status reason required' USING ERRCODE='23514'; END IF;
        IF NEW.status IN ('draft','ready') AND EXISTS(SELECT 1 FROM leadership_annualtarget x WHERE x.plan_id=NEW.plan_id AND x.position_id=NEW.position_id
                AND x.id<>NEW.id AND x.status IN ('draft','ready') AND x.start_date<NEW.end_date AND x.end_date>NEW.start_date) THEN
            RAISE EXCEPTION 'Overlapping F04 position segment' USING ERRCODE='23514'; END IF;
        IF NEW.supersedes_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM leadership_annualtarget WHERE id=NEW.supersedes_id AND id<>NEW.id AND plan_id=NEW.plan_id AND status='superseded') THEN
            RAISE EXCEPTION 'Invalid F04 replacement reference' USING ERRCODE='23514'; END IF;
    ELSIF TG_TABLE_NAME='leadership_eligibility' THEN
        SELECT * INTO t FROM leadership_annualtarget WHERE id=NEW.target_id FOR UPDATE;
        IF t.status IS DISTINCT FROM 'draft' OR t.scope_id IS DISTINCT FROM NEW.scope_id
           OR NOT EXISTS(SELECT 1 FROM leadership_person WHERE id=NEW.person_id AND scope_id=NEW.scope_id) THEN
            RAISE EXCEPTION 'F04 roster frozen or scope mismatch' USING ERRCODE='23514'; END IF;
        IF TG_OP='UPDATE' AND (NEW.target_id<>OLD.target_id OR NEW.person_id<>OLD.person_id) THEN
            RAISE EXCEPTION 'Stable F04 eligibility identity' USING ERRCODE='23514'; END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""
TABLES=['person','programme','position','annualplan','annualtarget','eligibility']
SQL+='\n'.join(f'CREATE TRIGGER f04_{name}_guard BEFORE INSERT OR UPDATE OR DELETE ON leadership_{name} FOR EACH ROW EXECUTE FUNCTION nexora_f04_register_guard();' for name in TABLES)
REVERSE='\n'.join(f'DROP TRIGGER f04_{name}_guard ON leadership_{name};' for name in TABLES)+'\nDROP FUNCTION nexora_f04_register_guard();'

class Migration(migrations.Migration):
    dependencies=[('leadership','0001_initial')]
    operations=[migrations.RunSQL(SQL,REVERSE)]
