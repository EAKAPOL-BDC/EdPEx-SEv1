"""Reuse locked source text only while preparing a private simulation copy.

Real forms still require the ordinary interactive review snapshots. No model
validation or database guard is disabled and each pair retains its audit event.
"""
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from apps.accounts.permissions import require_permission
from apps.catalog.models import InstrumentVersion, TranslationBundle
from apps.catalog.services import source_texts, _review_snapshot, _approve_locked_translation
from .models import WorkspaceRefresh


@transaction.atomic
def review_simulation_bundle(actor, bundle, progress=lambda message: None):
    version = InstrumentVersion.objects.select_for_update().select_related('instrument__scope').get(pk=bundle.instrument_version_id)
    scope = version.instrument.scope
    for action in ('role.manage', 'catalog.edit', 'translation.review'):
        require_permission(actor, action, scope)
    permits = WorkspaceRefresh.objects.filter(scope=scope,actor=actor,status='running')
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute('SELECT txid_current()')
            permits = permits.filter(database_transaction=cursor.fetchone()[0])
    if (version.status != 'draft' or version.source_metadata.get('synthetic_only') is not True
        or str(version.based_on_id) != version.source_metadata.get('simulation_source')
        or not permits.exists()):
        raise ValidationError('Automatic review is limited to isolated copies inside an authorized workspace refresh.')
    bundle = TranslationBundle.objects.select_for_update().get(pk=bundle.pk,instrument_version=version)
    bundle.instrument_version = version
    if bundle.status != 'draft':
        raise ValidationError('Published translation bundles are immutable.')
    # All writers take the version lock before modifying source content. This
    # private loop never edits source text, so one map stays current throughout.
    originals = source_texts(version)
    entries = {(e.content_key,e.locale):e for e in bundle.translations.select_for_update().order_by('pk')}
    selected = []
    for key in originals:
        for locale in ('th','en'):
            entry = entries.get((key,locale))
            if entry is None or not entry.text.strip():
                raise ValidationError(f'{version.instrument.code}: Missing translation: {key} ({locale}); no fallback.')
            selected.append(entry)
    for index,entry in enumerate(selected,1):
        entry.bundle = bundle
        entry.source_metadata = {**entry.source_metadata,'review_mode':'simulation_only'}
        original = originals[entry.content_key]
        snapshot = _review_snapshot(actor,entry,original,entry.text,'translation')
        _approve_locked_translation(actor,entry,original,reviewed_token=snapshot['reviewed_token'])
        if index == 1 or index % 25 == 0 or index == len(selected):
            progress(f'{version.instrument.code}: ตรวจคำแปล {index}/{len(selected)} รายการ')
    # A grant revoked during a long batch causes the entire batch to roll back.
    for action in ('role.manage', 'catalog.edit', 'translation.review'):
        require_permission(actor, action, scope)
    return bundle
