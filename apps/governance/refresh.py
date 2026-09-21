"""Explicit scoped cleanup + replacement, atomic and stale-plan protected.

Historical ORM delete methods intentionally remain closed. This administrative
operation has a separate database permit limited to the reviewed row IDs and
the current transaction; ordinary deletion and all audit history stay guarded.
"""
from collections import OrderedDict
import json
from django.core.serializers.json import DjangoJSONEncoder
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone
from apps.accounts.models import AccessScope
from apps.accounts.permissions import require_permission
from apps.auditlog.services import record_event
from apps.calculations.codec import digest
from .models import WorkspaceRefresh

REVISION='annual-simulation-2565-2568-v1'
def stable_hash(value):
    return digest(json.loads(json.dumps(value,cls=DjangoJSONEncoder)))
PERMISSIONS=('role.manage','round.manage','population.manage','source.manage','calendar.manage',
             'catalog.edit','catalog.publish','translation.review','calculation.run','calculation.validate',
             'result.submit','result.review','result.approve')
# Children before parents. Foreign keys remain active (the round/population
# cycle is deferred by Django). Never use TRUNCATE or disable triggers.
PATHS=OrderedDict([
    ('surveys.AnonymousSession','invitation__binding__collection_round__scope'),
    ('surveys.AnonymousResponse','binding__collection_round__scope'),
    ('surveys.Invitation','binding__collection_round__scope'),
    ('calculations.ResultDecision','review__run__collection_round__scope'),
    ('calculations.ResultReviewRequest','run__collection_round__scope'),
    ('calculations.StoredSourceSelection','run__collection_round__scope'),
    ('calculations.CalculationRequest','collection_round__scope'),
    ('calculations.IndicatorResult','run__collection_round__scope'),
    ('calculations.CalculationInputSnapshot','run__collection_round__scope'),
    ('calculations.CalculationRun','collection_round__scope'),
    ('calculations.ActivityRevision','record__round_instrument__collection_round__scope'),
    ('calculations.ActivityRecord','round_instrument__collection_round__scope'),
    ('selfassessments.SelfAssessmentRevision','assignment__round_instrument__collection_round__scope'),
    ('selfassessments.SelfAssessmentAssignment','round_instrument__collection_round__scope'),
    ('surveys.SurveyProfile','binding__collection_round__scope'),
    ('rounds.ResponsibilityAssignment','collection_round__scope'),
    ('rounds.RoundInstrument','collection_round__scope'),
    ('rounds.PopulationMember','snapshot__collection_round__scope'),
    ('rounds.PopulationSnapshot','collection_round__scope'),
    ('rounds.CollectionRound','scope'),
    ('rounds.DataSource','scope'),
    ('calculations.DemoSeries','dataset__scope'),
    ('calculations.DemoDataset','scope'),
])

def authorize(actor,scope):
    for permission in PERMISSIONS:require_permission(actor,permission,scope)

def plan(actor,scope):
    authorize(actor,scope)
    manifest={}
    for label,path in PATHS.items():
        model=apps.get_model(label)
        manifest[model._meta.db_table]=[str(pk) for pk in model.objects.filter(**{path:scope}).order_by('pk').values_list('pk',flat=True)]
    # Include mutable row fingerprints, without retaining response contents.
    # A newly submitted answer, invitation change, or changed draft invalidates
    # the plan even when the total count is unchanged.
    fingerprints={}
    for label,path in PATHS.items():
        model=apps.get_model(label)
        fingerprints[model._meta.db_table]=stable_hash(list(model.objects.filter(**{path:scope}).order_by('pk').values()))
    from apps.catalog.models import InstrumentVersion
    catalog=list(InstrumentVersion.objects.filter(instrument__scope=scope).order_by('pk').values('id','version','status','checksum','source_metadata'))
    from apps.catalog.services import source_texts
    texts={str(v.pk):source_texts(v) for v in InstrumentVersion.objects.filter(instrument__scope=scope).order_by('pk')}
    payload={'texts':texts,'scope':str(scope.pk),'revision':REVISION,'manifest':manifest,'fingerprints':fingerprints,'catalog':catalog}
    return {'hash':stable_hash(payload),'manifest':manifest,'counts':{k:len(v) for k,v in manifest.items()},
            'scope':str(scope.pk),'scope_code':scope.code,'revision':REVISION,
            'synthetic_years':[2565,2566,2567],'pending_year':2568}


@transaction.atomic
def execute(actor,scope,*,expected_hash,confirmation,reason,seed=None):
    authorize(actor,scope)
    if confirmation!='RESET '+scope.code or not reason.strip():
        raise ValidationError('พิมพ์ RESET ตามด้วยรหัสพื้นที่และระบุเหตุผล / Exact scope confirmation and reason required.')
    AccessScope.objects.select_for_update().get(pk=scope.pk)
    from apps.rounds.models import CollectionRound,PopulationSnapshot
    list(CollectionRound.objects.select_for_update().filter(scope=scope).order_by('pk'))
    list(PopulationSnapshot.objects.select_for_update().filter(collection_round__scope=scope).order_by('pk'))
    current=plan(actor,scope)
    if current['hash']!=expected_hash:
        raise ValidationError('ข้อมูลเปลี่ยนหลังแสดงแผน กรุณาตรวจรายการใหม่ / The cleanup plan is stale; preview again.')
    run=WorkspaceRefresh.objects.create(scope=scope,actor=actor,plan_hash=current['hash'],manifest=current['manifest'],revision=REVISION,reason=reason)
    with connection.cursor() as cursor:
        if connection.vendor=='postgresql':
            cursor.execute('SELECT txid_current()');run.database_transaction=cursor.fetchone()[0];run.save(update_fields=['database_transaction'])
            cursor.execute("SELECT set_config('nexora.workspace_refresh', %s, true)",[str(run.pk)])
        for label in PATHS:
            model=apps.get_model(label);ids=current['manifest'][model._meta.db_table]
            pk=model._meta.pk
            for offset in range(0,len(ids),250):
                chunk=[pk.get_db_prep_value(v,connection) for v in ids[offset:offset+250]]
                cursor.execute('DELETE FROM '+connection.ops.quote_name(model._meta.db_table)+' WHERE '+connection.ops.quote_name(pk.column)+' IN ('+','.join(['%s']*len(chunk))+')',chunk)
    if seed is None:
        from .simulation import seed_workspace
        seed=seed_workspace
    summary=seed(actor,scope)
    authorize(actor,scope)
    run.status='completed';run.completed_at=timezone.now();run.summary={'deleted':current['counts'],'created':summary}
    run.save(update_fields=['status','completed_at','summary'])
    record_event(scope.organization,actor,'workspace.refreshed','governance.workspacerefresh',str(run.pk),reason=reason,
                 metadata={'scope_id':str(scope.pk),'checksum':run.plan_hash,'count':sum(current['counts'].values()),'version':REVISION})
    return run
