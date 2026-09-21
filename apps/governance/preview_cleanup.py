"""Explicit collection IDs only; no scope reset, seed, cascade, or master deletion."""
from collections import OrderedDict
from uuid import UUID

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from apps.auditlog.services import record_event
from apps.rounds.models import CollectionRound
from .models import WorkspaceRefresh
from .refresh import authorize, stable_hash

REVISION = 'preview-collection-cleanup-v1'
PATHS = OrderedDict([
    ('participation.AccessSession', 'invitation__binding__collection_round_id'),
    ('surveys.AnonymousSession', 'invitation__binding__collection_round_id'),
    ('participation.ParticipationReceipt', 'policy__binding__collection_round_id'),
    ('participation.PublicSession', 'binding__collection_round_id'),
    ('surveys.AnonymousResponse', 'binding__collection_round_id'),
    ('surveys.Invitation', 'binding__collection_round_id'),
    ('participation.AccessPass', 'binding__collection_round_id'),
    ('participation.PublicCollection', 'binding__collection_round_id'),
    ('participation.AccessPool', 'binding__collection_round_id'),
    ('participation.ReceiptPolicy', 'binding__collection_round_id'),
    ('surveys.SurveyProfile', 'binding__collection_round_id'),
    ('rounds.RoundInstrument', 'collection_round_id'),
    ('rounds.PopulationMember', 'snapshot__collection_round_id'),
    ('rounds.PopulationSnapshot', 'collection_round_id'),
    ('rounds.CollectionRound', 'id'),
])
BLOCKERS = {
    'calculations.CalculationRun': 'collection_round_id',
    'calculations.ActivityRecord': 'round_instrument__collection_round_id',
    'selfassessments.SelfAssessmentAssignment': 'round_instrument__collection_round_id',
    'rounds.ResponsibilityAssignment': 'collection_round_id',
    'participation.ReceiptRedemption': 'receipt__policy__binding__collection_round_id',
    'participation.VerifierGrant': 'policy__binding__collection_round_id',
}


def check_environment():
    db = connection.settings_dict
    if (connection.vendor != 'postgresql' or db['HOST'] not in ('127.0.0.1', 'localhost')
            or str(db['PORT']) != '55469'
            or not (db['NAME'] == 'edpex_m1_public_ui' or db['NAME'].startswith('edpex_m1_cleanup_'))):
        raise ValidationError('Cleanup is restricted to the isolated local preview and its rehearsal databases.')


def plan(actor, scope, round_ids):
    check_environment()
    authorize(actor, scope)
    ids = sorted({str(UUID(str(pk))) for pk in round_ids})
    if not ids:
        raise ValidationError('An explicit non-empty collection list is required.')
    rounds = list(CollectionRound.objects.filter(pk__in=ids).order_by('pk'))
    if len(rounds) != len(ids) or any(r.scope_id != scope.pk or r.data_kind != 'synthetic' for r in rounds):
        raise ValidationError('Every approved collection must exist, be synthetic and belong to this scope.')
    for label, path in BLOCKERS.items():
        if apps.get_model(label).objects.filter(**{path + '__in': ids}).exists():
            raise ValidationError('Additional linked records require separate review: ' + label)
    # A registered F04 target is not included in this reviewed historical F01 cleanup.
    if apps.get_model('surveys.SurveyProfile').objects.filter(
            binding__collection_round_id__in=ids, annual_target__isnull=False).exists():
        raise ValidationError('Registered F04 collections require a separate review.')
    manifest, fingerprints = {}, {}
    for label, path in PATHS.items():
        model = apps.get_model(label)
        query = model.objects.filter(**{path + '__in': ids}).order_by('pk')
        manifest[model._meta.db_table] = [str(pk) for pk in query.values_list('pk', flat=True)]
        fingerprints[model._meta.db_table] = stable_hash(list(query.values()))
    payload = {'revision': REVISION, 'scope': str(scope.pk), 'round_ids': ids,
               'manifest': manifest, 'fingerprints': fingerprints}
    return {**payload, 'hash': stable_hash(payload),
            'rounds': [{'id': str(r.pk), 'code': r.code, 'status': r.status} for r in rounds],
            'counts': {key: len(value) for key, value in manifest.items()}}


def retained_fingerprints(manifest):
    """No plaintext account secrets or response contents appear in the report."""
    result = {}
    for model in apps.get_models(include_auto_created=True):
        if model._meta.label in ('auditlog.AuditEvent', 'governance.WorkspaceRefresh'):
            continue
        query = model._base_manager.exclude(pk__in=manifest.get(model._meta.db_table, [])).order_by('pk')
        result[model._meta.db_table] = stable_hash(list(query.values()))
    return result


@transaction.atomic
def execute(actor, scope, *, round_ids, expected_hash, confirmation, reason):
    check_environment()
    authorize(actor, scope)
    if confirmation != 'DELETE APPROVED PREVIEW COLLECTIONS' or not reason.strip():
        raise ValidationError('Exact collection cleanup confirmation and reason required.')
    # Freeze writes to affected tables for this short transaction. Foreign keys
    # and all triggers remain enabled; a lock timeout aborts the whole operation.
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '8s'")
        tables = [connection.ops.quote_name(apps.get_model(label)._meta.db_table) for label in PATHS]
        cursor.execute('LOCK TABLE ' + ','.join(sorted(tables)) + ' IN SHARE ROW EXCLUSIVE MODE')
    current = plan(actor, scope, round_ids)
    if current['hash'] != expected_hash:
        raise ValidationError('Approved data has changed. Stop and review a fresh inventory.')
    preserved = retained_fingerprints(current['manifest'])
    old_audit = list(apps.get_model('auditlog.AuditEvent').objects.order_by('pk').values())
    run = WorkspaceRefresh.objects.create(scope=scope, actor=actor, plan_hash=expected_hash,
        manifest=current['manifest'], revision=REVISION, reason=reason)
    with connection.cursor() as cursor:
        cursor.execute('SELECT txid_current()')
        run.database_transaction = cursor.fetchone()[0]
        run.save(update_fields=['database_transaction'])
        cursor.execute("SELECT set_config('nexora.preview_cleanup', %s, true)", [str(run.pk)])
        for label in PATHS:
            model = apps.get_model(label)
            ids = current['manifest'][model._meta.db_table]
            if not ids:
                continue
            pk = model._meta.pk
            values = [pk.get_db_prep_value(value, connection) for value in ids]
            cursor.execute('DELETE FROM ' + connection.ops.quote_name(model._meta.db_table)
                + ' WHERE ' + connection.ops.quote_name(pk.column) + ' IN ('
                + ','.join(['%s'] * len(values)) + ')', values)
            if cursor.rowcount != len(ids):
                raise ValidationError('Deleted row count differs from the approved manifest.')
        cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
    if retained_fingerprints(current['manifest']) != preserved:
        raise ValidationError('A retained record changed. Cleanup rolled back.')
    if list(apps.get_model('auditlog.AuditEvent').objects.order_by('pk').values()) != old_audit:
        raise ValidationError('Audit history changed. Cleanup rolled back.')
    authorize(actor, scope)
    run.status = 'completed'
    run.completed_at = timezone.now()
    run.summary = {'deleted': current['counts'], 'retained_fingerprints': preserved}
    run.save(update_fields=['status', 'completed_at', 'summary'])
    record_event(scope.organization, actor, 'preview.collections_deleted', 'governance.workspacerefresh',
        str(run.pk), reason=reason, metadata={'scope_id': str(scope.pk), 'checksum': expected_hash,
        'count': sum(current['counts'].values()), 'version': REVISION})
    return run
