"""Add a scoped DELETE operation; never disable existing history guards.

Capture known guard definitions at migration time and inject a DELETE-only
permit. Reverse removes that exact branch. INSERT/UPDATE protection is intact.
"""
from django.db import migrations

GUARDS=('edpex_rounds_guard','edpex_population_member_lock','edpex_calculation_guard',
        'edpex_result_review_guard','f05_immutable_guard','edpex_self_report_guard',
        'nexora_survey_guard','nexora_f04_profile_guard')
BRANCH="\n    IF TG_OP='DELETE' AND nexora_refresh_allows(TG_TABLE_NAME,to_jsonb(OLD)) THEN RETURN OLD; END IF; -- scoped-refresh-v1\n"
SQL=r"""
CREATE FUNCTION nexora_scope_permissions(actor integer, target uuid, required jsonb) RETURNS boolean AS $$
WITH RECURSIVE chain AS (
 SELECT s.id,s.parent_id,s.organization_id FROM accounts_accessscope s WHERE s.id=target AND s.active
 UNION
 SELECT s.id,s.parent_id,s.organization_id FROM accounts_accessscope s JOIN chain c ON s.id=c.parent_id
 WHERE s.active AND s.organization_id=c.organization_id
), available AS (
 SELECT DISTINCT p.value AS permission
 FROM chain c JOIN accounts_roleassignment g ON g.scope_id=c.id
 JOIN accounts_membership m ON m.id=g.membership_id
 JOIN auth_user u ON u.id=m.user_id JOIN accounts_role r ON r.id=g.role_id
 CROSS JOIN LATERAL jsonb_array_elements_text(r.permissions) p
 WHERE u.id=actor AND u.is_active AND m.is_active AND m.organization_id=c.organization_id
 AND (c.id=target OR g.include_descendants) AND g.revoked_at IS NULL
 AND g.active_from<=statement_timestamp() AND (g.active_until IS NULL OR g.active_until>statement_timestamp())
)
SELECT EXISTS(SELECT 1 FROM chain WHERE id=target) AND NOT EXISTS (
 SELECT 1 FROM jsonb_array_elements_text(required) q WHERE q.value NOT IN (SELECT permission FROM available));
$$ LANGUAGE sql STABLE;

CREATE FUNCTION nexora_refresh_allows(table_name text, old_row jsonb) RETURNS boolean AS $$
DECLARE permit governance_workspacerefresh; key text; actual_scope uuid;
BEGIN
 IF COALESCE(current_setting('nexora.workspace_refresh',true),'')='' THEN RETURN false; END IF;
 SELECT * INTO permit FROM governance_workspacerefresh WHERE id::text=current_setting('nexora.workspace_refresh',true)
 AND status='running' AND database_transaction=txid_current();
 IF permit.id IS NULL OR NOT nexora_scope_permissions(permit.actor_id,permit.scope_id,
 '["role.manage","round.manage","population.manage","source.manage","calendar.manage","catalog.edit","catalog.publish","translation.review","calculation.run","calculation.validate","result.submit","result.review","result.approve"]') THEN RETURN false; END IF;
 key=CASE WHEN table_name='surveys_surveyprofile' THEN old_row->>'binding_id' ELSE old_row->>'id' END;
 IF NOT COALESCE((permit.manifest->table_name) ? key,false) THEN RETURN false; END IF;
 -- Verify the row scope independently of the manifest, while parents still exist.
 CASE table_name
 WHEN 'rounds_collectionround','rounds_datasource','rounds_responsibilityassignment' THEN actual_scope=(old_row->>'scope_id')::uuid;
 WHEN 'rounds_roundinstrument','rounds_populationsnapshot','calculations_calculationrun','calculations_calculationrequest' THEN
   SELECT scope_id INTO actual_scope FROM rounds_collectionround WHERE id=(old_row->>'collection_round_id')::uuid;
 WHEN 'rounds_populationmember' THEN
   SELECT r.scope_id INTO actual_scope FROM rounds_populationsnapshot p JOIN rounds_collectionround r ON r.id=p.collection_round_id WHERE p.id=(old_row->>'snapshot_id')::uuid;
 WHEN 'surveys_surveyprofile','surveys_invitation','surveys_anonymousresponse' THEN
   SELECT r.scope_id INTO actual_scope FROM rounds_roundinstrument b JOIN rounds_collectionround r ON r.id=b.collection_round_id WHERE b.id=(old_row->>'binding_id')::uuid;
 WHEN 'surveys_anonymoussession' THEN
   SELECT r.scope_id INTO actual_scope FROM surveys_invitation i JOIN rounds_roundinstrument b ON b.id=i.binding_id JOIN rounds_collectionround r ON r.id=b.collection_round_id WHERE i.id=(old_row->>'invitation_id')::uuid;
 WHEN 'calculations_calculationinputsnapshot','calculations_indicatorresult','calculations_storedsourceselection','calculations_resultreviewrequest' THEN
   SELECT r.scope_id INTO actual_scope FROM calculations_calculationrun c JOIN rounds_collectionround r ON r.id=c.collection_round_id WHERE c.id=(old_row->>'run_id')::uuid;
 WHEN 'calculations_resultdecision' THEN
   SELECT r.scope_id INTO actual_scope FROM calculations_resultreviewrequest rr JOIN calculations_calculationrun c ON c.id=rr.run_id JOIN rounds_collectionround r ON r.id=c.collection_round_id WHERE rr.id=(old_row->>'review_id')::uuid;
 WHEN 'calculations_activityrecord','selfassessments_selfassessmentassignment' THEN
   SELECT r.scope_id INTO actual_scope FROM rounds_roundinstrument b JOIN rounds_collectionround r ON r.id=b.collection_round_id WHERE b.id=(old_row->>'round_instrument_id')::uuid;
 WHEN 'calculations_activityrevision' THEN
   SELECT r.scope_id INTO actual_scope FROM calculations_activityrecord a JOIN rounds_roundinstrument b ON b.id=a.round_instrument_id JOIN rounds_collectionround r ON r.id=b.collection_round_id WHERE a.id=(old_row->>'record_id')::uuid;
 WHEN 'selfassessments_selfassessmentrevision' THEN
   SELECT r.scope_id INTO actual_scope FROM selfassessments_selfassessmentassignment a JOIN rounds_roundinstrument b ON b.id=a.round_instrument_id JOIN rounds_collectionround r ON r.id=b.collection_round_id WHERE a.id=(old_row->>'assignment_id')::uuid;
 ELSE RETURN false;
 END CASE;
 RETURN actual_scope=permit.scope_id;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION nexora_collection_kind_guard() RETURNS trigger AS $$
DECLARE r rounds_collectionround; metadata jsonb;
BEGIN
 IF TG_TABLE_NAME='rounds_collectionround' THEN
   IF NEW.data_kind NOT IN ('real','synthetic') THEN RAISE EXCEPTION 'Invalid data kind'; END IF;
   IF TG_OP='UPDATE' AND NEW.data_kind<>OLD.data_kind THEN RAISE EXCEPTION 'Collection data kind is immutable'; END IF;
   IF NEW.status<>'draft' AND NOT NEW.schedule_confirmed THEN RAISE EXCEPTION 'Confirm the collection window first'; END IF;
 ELSE
   SELECT * INTO r FROM rounds_collectionround WHERE id=NEW.collection_round_id;
   SELECT source_metadata INTO metadata FROM catalog_instrumentversion WHERE id=NEW.instrument_version_id;
   IF COALESCE((metadata->>'synthetic_only')::boolean,false) AND r.data_kind<>'synthetic' THEN RAISE EXCEPTION 'Simulation forms cannot collect real answers'; END IF;
 END IF;
 RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER collection_kind_guard BEFORE INSERT OR UPDATE ON rounds_collectionround FOR EACH ROW EXECUTE FUNCTION nexora_collection_kind_guard();
CREATE TRIGGER collection_kind_guard BEFORE INSERT OR UPDATE ON rounds_roundinstrument FOR EACH ROW EXECUTE FUNCTION nexora_collection_kind_guard();

CREATE FUNCTION nexora_simulation_review(actor integer, round_id uuid, reason text) RETURNS boolean AS $$
 SELECT EXISTS (SELECT 1 FROM rounds_collectionround r WHERE r.id=round_id AND r.data_kind='synthetic'
 AND reason LIKE '[SIMULATION ONLY] %' AND nexora_scope_permissions(actor,r.scope_id,'["result.review","result.approve","calculation.validate"]'));
$$ LANGUAGE sql STABLE;

CREATE FUNCTION nexora_refresh_history_guard() RETURNS trigger AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Workspace refresh history is retained'; END IF;
 IF NOT nexora_scope_permissions(NEW.actor_id,NEW.scope_id,'["role.manage","round.manage","population.manage","source.manage","calendar.manage","catalog.edit","catalog.publish","translation.review","calculation.run","calculation.validate","result.submit","result.review","result.approve"]') THEN RAISE EXCEPTION 'Unauthorized workspace refresh'; END IF;
 IF TG_OP='INSERT' THEN
   IF NEW.status<>'running' OR NEW.database_transaction IS NOT NULL OR NEW.completed_at IS NOT NULL THEN RAISE EXCEPTION 'Invalid initial refresh state'; END IF;
 ELSE
   IF OLD.status<>'running' OR (to_jsonb(NEW)-ARRAY['status','summary','database_transaction','completed_at']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','summary','database_transaction','completed_at']) THEN RAISE EXCEPTION 'Immutable refresh identity and plan'; END IF;
   IF NEW.database_transaction<>txid_current() OR (OLD.database_transaction IS NOT NULL AND NEW.database_transaction<>OLD.database_transaction) THEN RAISE EXCEPTION 'Refresh is transaction scoped'; END IF;
   IF NEW.status NOT IN ('running','completed') OR (NEW.status='completed')<>(NEW.completed_at IS NOT NULL) THEN RAISE EXCEPTION 'Invalid refresh completion'; END IF;
 END IF;
 RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER refresh_history_guard BEFORE INSERT OR UPDATE OR DELETE ON governance_workspacerefresh FOR EACH ROW EXECUTE FUNCTION nexora_refresh_history_guard();
"""
OLD_REVIEW="NOT edpex_admin_self_review(NEW.actor_id, (SELECT scope_id FROM rounds_collectionround WHERE id=run.collection_round_id))\n             OR NEW.reason NOT LIKE '[ADMIN SELF-REVIEW] %'"
NEW_REVIEW="("+OLD_REVIEW+") AND NOT nexora_simulation_review(NEW.actor_id,run.collection_round_id,NEW.reason)"

def guards(apps,editor,reverse=False):
    if editor.connection.vendor!='postgresql':return
    with editor.connection.cursor() as cursor:
        for name in GUARDS:
            cursor.execute('SELECT pg_get_functiondef(%s::regprocedure)',[name+'()'])
            definition=cursor.fetchone()[0]
            if reverse:
                if BRANCH not in definition:raise RuntimeError('Missing refresh guard: '+name)
                definition=definition.replace(BRANCH,'',1)
                if name=='edpex_result_review_guard':definition=definition.replace(NEW_REVIEW,OLD_REVIEW)
            else:
                if BRANCH in definition:raise RuntimeError('Refresh guard already installed: '+name)
                # Known functions have one outer BEGIN; nested blocks stay intact.
                pos=definition.index('BEGIN')+len('BEGIN')
                definition=definition[:pos]+BRANCH+definition[pos:]
                if name=='edpex_result_review_guard':
                    if OLD_REVIEW not in definition:raise RuntimeError('Unrecognized review guard; refusing migration')
                    definition=definition.replace(OLD_REVIEW,NEW_REVIEW)
            cursor.execute(definition)

def undo(apps,editor):guards(apps,editor,True)

class Migration(migrations.Migration):
    dependencies=[('governance','0004_workspace_refresh')]
    operations=[migrations.RunSQL(SQL,"""
DROP TRIGGER collection_kind_guard ON rounds_collectionround;
DROP TRIGGER collection_kind_guard ON rounds_roundinstrument;
DROP FUNCTION nexora_collection_kind_guard();
DROP TRIGGER refresh_history_guard ON governance_workspacerefresh;
DROP FUNCTION nexora_refresh_history_guard();
DROP FUNCTION nexora_simulation_review(integer,uuid,text);
DROP FUNCTION nexora_refresh_allows(text,jsonb);
DROP FUNCTION nexora_scope_permissions(integer,uuid,jsonb);
"""),migrations.RunPython(guards,undo)]
