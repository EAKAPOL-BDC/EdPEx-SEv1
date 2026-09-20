"""Audited, exact-row cleanup for synthetic preview collections only.

Ordinary deletes remain forbidden. The permit is bound to database, actor,
scope, transaction, manifest, and the synthetic parent collection.
"""
from django.db import migrations

GUARDS = (
    'edpex_rounds_guard', 'edpex_population_member_lock',
    'nexora_survey_guard', 'nexora_f04_profile_guard',
    'nexora_participation_guard', 'nexora_unlinked_access_guard',
    'nexora_unlinked_context_guard', 'nexora_public_guard',
    'nexora_public_context_guard',
)
BRANCH = "\n    IF TG_OP='DELETE' AND nexora_preview_cleanup_allows(TG_TABLE_NAME,to_jsonb(OLD)) THEN RETURN OLD; END IF; -- preview-cleanup-v1\n"
SQL = r"""
CREATE FUNCTION nexora_preview_cleanup_allows(table_name text, old_row jsonb) RETURNS boolean AS $$
DECLARE permit governance_workspacerefresh; key text; round_id uuid; binding_id uuid;
        actual_scope uuid; kind text;
BEGIN
 IF current_database()<>'edpex_m1_public_ui' AND current_database() NOT LIKE 'edpex_m1_cleanup_%' THEN RETURN false; END IF;
 IF COALESCE(current_setting('nexora.preview_cleanup',true),'')='' THEN RETURN false; END IF;
 SELECT * INTO permit FROM governance_workspacerefresh
 WHERE id::text=current_setting('nexora.preview_cleanup',true)
 AND revision='preview-collection-cleanup-v1' AND status='running'
 AND database_transaction=txid_current();
 IF permit.id IS NULL OR NOT nexora_scope_permissions(permit.actor_id,permit.scope_id,
 '["role.manage","round.manage","population.manage","source.manage","calendar.manage","catalog.edit","catalog.publish","translation.review","calculation.run","calculation.validate","result.submit","result.review","result.approve"]') THEN RETURN false; END IF;
 key=CASE WHEN table_name IN ('surveys_surveyprofile','participation_publiccollection','participation_accesspool')
          THEN old_row->>'binding_id' ELSE old_row->>'id' END;
 IF NOT COALESCE((permit.manifest->table_name) ? key,false) THEN RETURN false; END IF;
 CASE table_name
 WHEN 'rounds_collectionround' THEN round_id=(old_row->>'id')::uuid;
 WHEN 'rounds_roundinstrument','rounds_populationsnapshot' THEN round_id=(old_row->>'collection_round_id')::uuid;
 WHEN 'rounds_populationmember' THEN
   SELECT collection_round_id INTO round_id FROM rounds_populationsnapshot WHERE id=(old_row->>'snapshot_id')::uuid;
 WHEN 'surveys_surveyprofile','surveys_invitation','surveys_anonymousresponse',
      'participation_publiccollection','participation_publicsession','participation_accesspool',
      'participation_accesspass','participation_receiptpolicy' THEN binding_id=(old_row->>'binding_id')::uuid;
 WHEN 'surveys_anonymoussession' THEN
   SELECT i.binding_id INTO binding_id FROM surveys_invitation i WHERE i.id=(old_row->>'invitation_id')::uuid;
 WHEN 'participation_accesssession' THEN
   SELECT p.binding_id INTO binding_id FROM participation_accesspass p WHERE p.id=(old_row->>'invitation_id')::uuid;
 WHEN 'participation_participationreceipt' THEN
   SELECT p.binding_id INTO binding_id FROM participation_receiptpolicy p WHERE p.id=(old_row->>'policy_id')::uuid;
 ELSE RETURN false;
 END CASE;
 IF binding_id IS NOT NULL THEN
   SELECT b.collection_round_id INTO round_id FROM rounds_roundinstrument b WHERE b.id=binding_id;
 END IF;
 SELECT r.scope_id,r.data_kind INTO actual_scope,kind FROM rounds_collectionround r WHERE r.id=round_id;
 RETURN COALESCE(actual_scope=permit.scope_id AND kind='synthetic'
    AND (permit.manifest->'rounds_collectionround') ? round_id::text,false);
END;
$$ LANGUAGE plpgsql;
"""


def install(apps, editor, reverse=False):
    if editor.connection.vendor != 'postgresql':
        return
    with editor.connection.cursor() as cursor:
        for name in GUARDS:
            cursor.execute('SELECT pg_get_functiondef(%s::regprocedure)', [name + '()'])
            definition = cursor.fetchone()[0]
            if reverse:
                if BRANCH not in definition:
                    raise RuntimeError('Missing preview cleanup guard: ' + name)
                definition = definition.replace(BRANCH, '', 1)
            else:
                if BRANCH in definition:
                    raise RuntimeError('Duplicate preview cleanup guard: ' + name)
                pos = definition.index('BEGIN') + len('BEGIN')
                definition = definition[:pos] + BRANCH + definition[pos:]
            cursor.execute(definition)


def uninstall(apps, editor):
    install(apps, editor, True)


class Migration(migrations.Migration):
    dependencies = [
        ('governance', '0005_refresh_guards'),
        ('participation', '0008_public_session_clock'),
    ]
    operations = [
        migrations.RunSQL(SQL, 'DROP FUNCTION nexora_preview_cleanup_allows(text,jsonb);'),
        migrations.RunPython(install, uninstall),
    ]
