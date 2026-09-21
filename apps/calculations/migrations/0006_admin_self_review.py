from importlib import import_module
from django.db import migrations

ORIGINAL=import_module('apps.calculations.migrations.0005_anonymous_source_review').UPDATED
HELPER=r"""
CREATE FUNCTION edpex_admin_self_review(actor integer, target uuid) RETURNS boolean AS $$
 SELECT target='fc064809-6564-4f74-b303-c32026f82511'::uuid AND EXISTS (
 SELECT 1 FROM auth_user u JOIN accounts_membership m ON m.user_id=u.id
 JOIN accounts_roleassignment g ON g.membership_id=m.id
 JOIN accounts_role r ON r.id=g.role_id JOIN accounts_accessscope s ON s.id=g.scope_id
 WHERE u.id=actor AND u.username='edpexadmin' AND u.is_active AND u.is_superuser
 AND m.is_active AND s.active AND m.organization_id=s.organization_id
 AND g.scope_id=target AND r.code='system-administrator-v1'
 AND r.permissions @> '["role.manage","result.review","result.approve","calculation.validate"]'::jsonb
 AND g.revoked_at IS NULL AND g.active_from<=statement_timestamp()
 AND (g.active_until IS NULL OR g.active_until>statement_timestamp()))
$$ LANGUAGE sql STABLE;
"""
OLD='IF NEW.actor_id IN (review.requested_by_id, run.created_by_id)'
NEW="""IF (NEW.actor_id IN (review.requested_by_id, run.created_by_id) AND
            (NOT edpex_admin_self_review(NEW.actor_id, (SELECT scope_id FROM rounds_collectionround WHERE id=run.collection_round_id))
             OR NEW.reason NOT LIKE '[ADMIN SELF-REVIEW] %'))"""
assert OLD in ORIGINAL
UPDATED=ORIGINAL.replace(OLD,NEW)
class Migration(migrations.Migration):
    dependencies=[('calculations','0005_anonymous_source_review')]
    operations=[migrations.RunSQL(HELPER+UPDATED,ORIGINAL+'DROP FUNCTION edpex_admin_self_review(integer, uuid);')]
