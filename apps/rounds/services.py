"""Permission checked M1 entry points; status/freeze changes are transactional."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.accounts.permissions import require_permission
from apps.auditlog.services import record_event

from .models import (
    Calendar, CollectionRound, DataSource, PopulationMember, PopulationSnapshot,
    ReportingPeriod, RespondentGroup, ResponsibilityAssignment, RoundInstrument,
)


MODEL_ACTIONS = {
    Calendar: "calendar.manage", ReportingPeriod: "calendar.manage",
    CollectionRound: "round.manage", RoundInstrument: "round.manage",
    PopulationSnapshot: "population.manage", PopulationMember: "population.manage",
    RespondentGroup: "population.manage", ResponsibilityAssignment: "responsibility.manage",
    DataSource: "source.manage",
}
CONTROLLED_FIELDS = {
    ReportingPeriod: {"approved", "approved_by", "approved_by_id", "approved_at"},
    CollectionRound: {"status", "population_snapshot", "population_snapshot_id"},
    PopulationSnapshot: {"status", "frozen_at"},
    DataSource: {"recorded_at"},
}


def _authorize(actor, record):
    action = MODEL_ACTIONS[type(record)]
    require_permission(actor, action, record.domain_scope())
    return action


def _event(actor, record, action, reason="", **metadata):
    record_event(
        organization=record.organization, actor=actor, action=action,
        object_type=record._meta.label_lower, object_id=str(record.pk), reason=reason,
        metadata={"scope_id": str(record.domain_scope().pk), **metadata},
    )


def _validate_write_fields(model, values):
    if model not in MODEL_ACTIONS:
        raise ValidationError("Unsupported model for this domain service.")
    forbidden = {"id", "pk", "created_at", "updated_at", "_allow_transition", "_allow_freeze"}
    forbidden |= CONTROLLED_FIELDS.get(model, set())
    allowed = {name for field in model._meta.concrete_fields for name in (field.name, field.attname)}
    if forbidden.intersection(values) or set(values) - allowed:
        raise ValidationError("Lifecycle fields must be changed through their dedicated service.")


def _fresh_foreign_keys(model, values):
    """Only retain submitted FK identities, never trust cached relation graphs."""
    normalized = dict(values)
    for field in model._meta.concrete_fields:
        if field.is_relation and field.name in normalized:
            value = normalized.pop(field.name)
            normalized[field.attname] = getattr(value, "pk", value)
    return normalized


@transaction.atomic
def create_record(actor, model, **values):
    """Create a draft/domain row after checking the target access scope."""
    _validate_write_fields(model, values)
    record = model(**_fresh_foreign_keys(model, values))
    action = _authorize(actor, record)
    record.save()
    _authorize(actor, record)
    _event(actor, record, action + ".create")
    return record


@transaction.atomic
def update_record(actor, record, *, reason, **values):
    if not reason.strip():
        raise ValidationError("Record the reason for a change.")
    _validate_write_fields(type(record), values)
    record = type(record).objects.select_for_update().get(pk=record.pk)
    action = _authorize(actor, record)
    for field, value in _fresh_foreign_keys(type(record), values).items():
        setattr(record, field, value)
    _authorize(actor, record)
    record.save()
    _authorize(actor, record)
    # Audit field names, never identity values, employment facts, or locations.
    _event(actor, record, action + ".update", reason, changed_fields=sorted(values))
    return record


@transaction.atomic
def delete_draft(actor, record, *, reason):
    if not reason.strip():
        raise ValidationError("Record the reason for deletion.")
    record = type(record).objects.select_for_update().get(pk=record.pk)
    action = _authorize(actor, record)
    _event(actor, record, action + ".delete", reason)
    record.delete()


def records_for_scope(actor, model, scope):
    """Explicit scope-bound read; population identity requires population.manage."""
    if model not in MODEL_ACTIONS:
        raise ValidationError("Unsupported model.")
    require_permission(actor, MODEL_ACTIONS[model], scope)
    paths = {
        ReportingPeriod: "calendar__scope",
        RoundInstrument: "collection_round__scope",
        PopulationSnapshot: "collection_round__scope",
        PopulationMember: "snapshot__collection_round__scope",
    }
    return model.objects.filter(**{paths.get(model, "scope"): scope}, organization=scope.organization)


@transaction.atomic
def approve_period(actor, period, *, reason):
    period = ReportingPeriod.objects.select_for_update().get(pk=period.pk)
    _authorize(actor, period)
    if period.approved:
        raise ValidationError("The period is already approved.")
    if not reason.strip():
        raise ValidationError("Explain the approval of actual reporting dates.")
    period.approved = True
    period.approved_by = actor
    period.approved_at = timezone.now()
    period.save()
    _event(actor, period, "calendar.manage.approve", reason)
    return period


@transaction.atomic
def freeze_population(actor, snapshot):
    # Match member save's lock ordering: snapshot then member rows.
    snapshot = PopulationSnapshot.objects.select_for_update().get(pk=snapshot.pk)
    _authorize(actor, snapshot)
    if snapshot.status != PopulationSnapshot.Status.DRAFT:
        raise ValidationError("Snapshot is already frozen.")
    if not snapshot.counts_by_group:
        raise ValidationError("Define actual eligible counts and respondent groups before freezing.")
    if not snapshot.source_id:
        raise ValidationError("Identify the actual source of this population before freezing.")
    actual = dict(snapshot.members.values("group__code").annotate(total=Count("id")).values_list("group__code", "total"))
    if actual and any(actual.get(code, 0) != count for code, count in snapshot.counts_by_group.items()):
        raise ValidationError("Member rows do not match the declared complete population counts.")
    if set(actual) - set(snapshot.counts_by_group):
        raise ValidationError("A population member's group is missing from the declared counts.")
    snapshot.status = PopulationSnapshot.Status.FROZEN
    snapshot.frozen_at = timezone.now()
    snapshot._allow_freeze = True
    snapshot.save()
    _event(actor, snapshot, "population.manage.freeze", version=snapshot.version)
    return snapshot


def _check_ready(collection_round):
    if not collection_round.period.approved:
        raise ValidationError("Approve the real reporting period before activating a round.")
    if not collection_round.privacy_notice.strip():
        raise ValidationError("The round requires its privacy and data-use notice.")
    bindings = list(collection_round.round_instruments.select_related("instrument_version", "translation_bundle"))
    if not bindings:
        raise ValidationError("Bind at least one reviewed instrument and translation version.")
    for binding in bindings:
        binding.full_clean()
        if binding.instrument_version.status != "published" or binding.translation_bundle.status != "published":
            raise ValidationError("Only published instruments and approved, published translation bundles can open.")
    if collection_round.status != CollectionRound.Status.DRAFT and collection_round.population_snapshot_id:
        snapshot = collection_round.population_snapshot
    else:
        snapshot = collection_round.population_snapshots.filter(status=PopulationSnapshot.Status.FROZEN).order_by("-version").first()
    if snapshot is None:
        raise ValidationError("Freeze the actual population before activating the round.")
    collection_round.population_snapshot = snapshot


@transaction.atomic
def transition_round(actor, collection_round, target_status, *, reason=""):
    """M1 activation/closing only; calculation and result approval belong to M4.

    The persisted status vocabulary anticipates later work, but this service does
    not pretend that an unimplemented calculation or result review succeeded.
    """
    collection_round = CollectionRound.objects.select_for_update().get(pk=collection_round.pk)
    _authorize(actor, collection_round)
    source_status = collection_round.status
    allowed = {
        CollectionRound.Status.DRAFT: {CollectionRound.Status.READY},
        CollectionRound.Status.READY: {CollectionRound.Status.DRAFT, CollectionRound.Status.OPEN},
        CollectionRound.Status.OPEN: {CollectionRound.Status.CLOSED},
    }
    if target_status not in allowed.get(source_status, set()):
        raise ValidationError("This lifecycle transition is not supported in M1.")
    if target_status in (CollectionRound.Status.READY, CollectionRound.Status.OPEN):
        _check_ready(collection_round)
    if target_status == CollectionRound.Status.OPEN and not collection_round.open_at <= timezone.now() < collection_round.close_at:
        raise ValidationError("The current server time is outside the collection window.")
    if target_status in (CollectionRound.Status.DRAFT, CollectionRound.Status.CLOSED) and not reason.strip():
        raise ValidationError("Record a reason for reverting readiness or closing collection.")
    collection_round.status = target_status
    collection_round._allow_transition = True
    collection_round.save()
    _event(actor, collection_round, "round.manage.transition", reason, before_status=source_status, after_status=target_status)
    return collection_round
