"""PostgreSQL invariants frozen in Django migration history."""
from django.db import migrations

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION edpex_accounts_scope_guard() RETURNS trigger AS $$
DECLARE
    ancestor uuid;
    ancestor_parent uuid;
    ancestor_organization uuid;
    visited uuid[];
BEGIN
    PERFORM pg_advisory_xact_lock(58701236194701);
    IF TG_OP = 'UPDATE' AND OLD.organization_id IS DISTINCT FROM NEW.organization_id THEN
        RAISE EXCEPTION 'An existing scope cannot move between organizations' USING ERRCODE = '23514';
    END IF;
    ancestor := NEW.parent_id;
    visited := ARRAY[NEW.id];
    WHILE ancestor IS NOT NULL LOOP
        IF ancestor = ANY(visited) THEN
            RAISE EXCEPTION 'Scope parents must not form a cycle' USING ERRCODE = '23514';
        END IF;
        visited := array_append(visited, ancestor);
        SELECT parent_id, organization_id INTO ancestor_parent, ancestor_organization
          FROM accounts_accessscope WHERE id = ancestor;
        IF NOT FOUND THEN
            EXIT; -- the foreign key handles a nonexistent parent
        END IF;
        IF ancestor_organization IS DISTINCT FROM NEW.organization_id THEN
            RAISE EXCEPTION 'Parent scope must belong to the same organization' USING ERRCODE = '23514';
        END IF;
        ancestor := ancestor_parent;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accounts_scope_guard BEFORE INSERT OR UPDATE ON accounts_accessscope
FOR EACH ROW EXECUTE FUNCTION edpex_accounts_scope_guard();

CREATE OR REPLACE FUNCTION edpex_accounts_membership_guard() RETURNS trigger AS $$
BEGIN
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id OR OLD.user_id IS DISTINCT FROM NEW.user_id THEN
        RAISE EXCEPTION 'Membership identity is immutable; revoke and create a new membership' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accounts_membership_guard BEFORE UPDATE ON accounts_membership
FOR EACH ROW EXECUTE FUNCTION edpex_accounts_membership_guard();

CREATE OR REPLACE FUNCTION edpex_accounts_assignment_guard() RETURNS trigger AS $$
DECLARE
    membership_organization uuid;
    scope_organization uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Grant history is retained; revoke instead' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND
        (to_jsonb(OLD) - ARRAY['updated_at', 'revoked_at']) IS DISTINCT FROM
        (to_jsonb(NEW) - ARRAY['updated_at', 'revoked_at']) THEN
        RAISE EXCEPTION 'Grant history is immutable; revoke and create a new grant' USING ERRCODE = '23514';
    END IF;
    PERFORM 1 FROM accounts_role WHERE id = NEW.role_id FOR UPDATE;
    SELECT organization_id INTO membership_organization FROM accounts_membership WHERE id = NEW.membership_id;
    SELECT organization_id INTO scope_organization FROM accounts_accessscope WHERE id = NEW.scope_id;
    IF membership_organization IS NOT NULL AND scope_organization IS NOT NULL
       AND membership_organization IS DISTINCT FROM scope_organization THEN
        RAISE EXCEPTION 'Grant and membership must belong to the same organization' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.revoked_at IS NOT NULL AND OLD.revoked_at IS DISTINCT FROM NEW.revoked_at THEN
        RAISE EXCEPTION 'Revocation is retained; create a new grant to restore access' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accounts_assignment_guard BEFORE INSERT OR UPDATE OR DELETE ON accounts_roleassignment
FOR EACH ROW EXECUTE FUNCTION edpex_accounts_assignment_guard();

CREATE OR REPLACE FUNCTION edpex_accounts_role_guard() RETURNS trigger AS $$
DECLARE
    allowed_actions text[] := ARRAY[
        'catalog.read', 'catalog.edit', 'catalog.publish', 'catalog.archive', 'translation.review',
        'calendar.manage', 'round.manage', 'population.manage', 'responsibility.manage', 'source.manage',
        'audit.read', 'self.read', 'self.write', 'role.manage'
    ];
BEGIN
    IF TG_OP = 'UPDATE' AND EXISTS (SELECT 1 FROM accounts_roleassignment WHERE role_id = OLD.id)
        AND (OLD.code IS DISTINCT FROM NEW.code OR OLD.permissions IS DISTINCT FROM NEW.permissions) THEN
        RAISE EXCEPTION 'Assigned roles are immutable; create a new role and dated grant' USING ERRCODE = '23514';
    END IF;
    IF jsonb_typeof(NEW.permissions) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'Permissions must be an action list' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.permissions) AS item
               WHERE jsonb_typeof(item) <> 'string' OR NOT (item #>> '{}') = ANY(allowed_actions)) THEN
        RAISE EXCEPTION 'Unsupported permission action' USING ERRCODE = '23514';
    END IF;
    IF (SELECT count(*) FROM jsonb_array_elements(NEW.permissions)) <>
       (SELECT count(DISTINCT item) FROM jsonb_array_elements(NEW.permissions) AS item) THEN
        RAISE EXCEPTION 'Duplicate permission actions are not allowed' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accounts_role_guard BEFORE INSERT OR UPDATE ON accounts_role
FOR EACH ROW EXECUTE FUNCTION edpex_accounts_role_guard();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS accounts_role_guard ON accounts_role;
DROP FUNCTION IF EXISTS edpex_accounts_role_guard();
DROP TRIGGER IF EXISTS accounts_assignment_guard ON accounts_roleassignment;
DROP FUNCTION IF EXISTS edpex_accounts_assignment_guard();
DROP TRIGGER IF EXISTS accounts_membership_guard ON accounts_membership;
DROP FUNCTION IF EXISTS edpex_accounts_membership_guard();
DROP TRIGGER IF EXISTS accounts_scope_guard ON accounts_accessscope;
DROP FUNCTION IF EXISTS edpex_accounts_scope_guard();
"""

class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
