"""Bounded audit metadata; source request bodies must never be copied here."""
from django.core.exceptions import ValidationError
from apps.accounts.permissions import require_permission
from .models import AuditEvent

ALLOWED_METADATA = {
    'before_status', 'after_status', 'version', 'revision', 'source_id',
    'source_hash', 'checksum', 'field_names', 'count', 'locale',
    'instrument_id', 'question_id', 'bundle_id', 'round_id', 'scope_id',
    'membership_id', 'role_id', 'assignment_id', 'period_id', 'snapshot_id',
    'old_version', 'new_version', 'status', 'changed_fields', 'content_key',
}


def record_event(organization, actor, action, object_type, object_id, reason='', metadata=None):
    metadata = metadata or {}
    if not isinstance(metadata, dict):
        raise ValidationError('Audit metadata must be an object.')
    safe = {key: value for key, value in metadata.items() if key in ALLOWED_METADATA}
    for value in safe.values():
        if isinstance(value, dict) or (isinstance(value, list) and any(not isinstance(v, str) for v in value)):
            raise ValidationError('Nested audit payloads are not allowed.')
    return AuditEvent.objects.create(
        organization=organization, actor=actor if getattr(actor, 'is_authenticated', False) else None,
        action=action, object_type=object_type, object_id=str(object_id),
        reason=reason, metadata=safe,
    )


def events_for_scope(user, scope):
    require_permission(user, 'audit.read', scope)
    return AuditEvent.objects.filter(organization=scope.organization, metadata__scope_id=str(scope.pk))
