"""Add explicit calculation actions without granting them to existing roles."""
from django.db import migrations


OLD_ACTIONS = """
    'catalog.read', 'catalog.edit', 'catalog.publish', 'catalog.archive', 'translation.review',
    'calendar.manage', 'round.manage', 'population.manage', 'responsibility.manage', 'source.manage',
    'audit.read', 'self.read', 'self.write', 'role.manage'
"""
FUNCTION = """
CREATE OR REPLACE FUNCTION edpex_accounts_role_guard() RETURNS trigger AS $$
DECLARE allowed_actions text[] := ARRAY[%s];
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
"""


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_postgresql_guards")]
    operations = [migrations.RunSQL(
        FUNCTION % (OLD_ACTIONS + ", 'calculation.run', 'calculation.source', 'calculation.validate'"),
        FUNCTION % OLD_ACTIONS,
    )]
