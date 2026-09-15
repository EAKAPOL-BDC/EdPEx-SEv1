"""Read the exact published wording pinned by an already activated round.

This is a staff history service: both round.manage and catalog.read are required.
It returns instrument wording, never participant identities or survey answers.
General catalog selection continues to exclude retired versions.
"""

from django.core.exceptions import ValidationError

from apps.accounts.permissions import require_permission
from apps.rounds.models import CollectionRound, PopulationSnapshot, RoundInstrument

from .models import source_hash
from .services import source_texts


def round_respondent_text(actor, collection_round, binding, content_key, locale):
    """Resolve all relationships from storage; submitted cached objects are untrusted."""
    collection_round = CollectionRound.objects.select_related("scope", "population_snapshot").get(
        pk=getattr(collection_round, "pk", collection_round),
    )
    require_permission(actor, "round.manage", collection_round.scope)
    require_permission(actor, "catalog.read", collection_round.scope)
    historical_statuses = {
        CollectionRound.Status.OPEN, CollectionRound.Status.CLOSED,
        CollectionRound.Status.CALCULATING, CollectionRound.Status.REVIEW,
        CollectionRound.Status.APPROVED, CollectionRound.Status.ARCHIVED,
    }
    snapshot = collection_round.population_snapshot
    if collection_round.status not in historical_statuses or snapshot is None or (
        snapshot.status != PopulationSnapshot.Status.FROZEN
        or snapshot.collection_round_id != collection_round.pk
    ):
        raise ValidationError("Historical wording requires an activated round with its frozen population.")
    binding = RoundInstrument.objects.select_related(
        "instrument_version__instrument", "translation_bundle",
    ).filter(pk=getattr(binding, "pk", binding), collection_round_id=collection_round.pk).first()
    if binding is None:
        raise ValidationError("This instrument binding does not belong to the requested round.")
    version, bundle = binding.instrument_version, binding.translation_bundle
    if (
        binding.organization_id != collection_round.scope.organization_id
        or version.instrument.scope_id != collection_round.scope_id
        or bundle.instrument_version_id != version.pk
        or version.status not in {"published", "retired"}
        or bundle.status != "published"
        or version.published_at is None or bundle.published_at is None
        or locale not in {"th", "en"}
    ):
        raise ValidationError("Only the exact published version and bundle pinned by this round can be read.")
    original = source_texts(version).get(content_key)
    if original is None:
        raise ValidationError("Content is not intended for respondents.")
    entry = bundle.translations.filter(content_key=content_key, locale=locale, status="approved").first()
    if not entry or (
        not entry.reviewed_by_id or not entry.reviewed_at or not entry.text.strip()
        or entry.source_hash != source_hash(original)
        or (locale == "th" and entry.text != original)
    ):
        raise ValidationError("Approved pinned wording is unavailable; draft text and fallback are forbidden.")
    return entry.text
