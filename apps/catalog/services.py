"""Authorized catalog operations. Callers cannot publish unreviewed English."""
import copy
import hashlib
import json

from django.core.exceptions import ValidationError
from django.core import signing
from django.db import transaction
from django.utils import timezone

from apps.accounts.permissions import require_permission
from .models import (
    BindingQuestion, ContentTranslation, InstrumentContent, InstrumentVersion,
    Question, QuestionOption, TranslationBundle, IndicatorBinding, LocalizedLabel, source_hash,
)


def _audit(actor, version, action, reason="", **metadata):
    from apps.auditlog.services import record_event
    record_event(
        organization=version.instrument.scope.organization, actor=actor, action=action,
        object_type="catalog.InstrumentVersion", object_id=str(version.pk),
        reason=reason, metadata={"scope_id": str(version.instrument.scope_id), **metadata},
    )


def source_texts(version):
    """Return respondent content only; never expose raw sections or answer keys."""
    texts = {}
    for question in version.questions.filter(active=True, audience="respondent").prefetch_related("options"):
        texts[f"{question.question_id}.text"] = question.text_th
        for option in question.options.all():
            texts[f"{question.question_id}.option.{option.code}"] = option.label_th
    for content in version.contents.filter(active=True, audience="respondent").exclude(kind="source_section"):
        texts[content.content_key] = content.text_th
    return texts


def assert_complete_bundle(bundle):
    version = bundle.instrument_version
    if not version.instructions_curated or not version.contents.filter(
        active=True, audience="respondent", kind="instruction",
    ).exists():
        raise ValidationError("Curate the respondent instructions from the source before publication.")
    expected = source_texts(version)
    if not expected:
        raise ValidationError("A translation bundle cannot be empty.")
    entries = {(entry.content_key, entry.locale): entry for entry in bundle.translations.all()}
    for key, original in expected.items():
        for locale in ("th", "en"):
            entry = entries.get((key, locale))
            if not entry or entry.status != "approved" or not entry.text.strip() or not entry.reviewed_by_id or not entry.reviewed_at:
                raise ValidationError(f"Unapproved or missing translation: {key} [{locale}].")
            if entry.source_hash != source_hash(original):
                raise ValidationError(f"Translation source changed: {key} [{locale}].")
            if locale == "th" and entry.text != original:
                raise ValidationError(f"Thai text differs from its source: {key}.")


@transaction.atomic
def update_question(actor, question, **changes):
    question = Question.objects.select_related("version__instrument__scope").get(pk=question.pk)
    require_permission(actor, "catalog.edit", question.version.instrument.scope)
    InstrumentVersion.objects.select_for_update().get(pk=question.version_id)
    question = Question.objects.select_for_update().select_related("version__instrument__scope").get(pk=question.pk)
    editable = {"text_th", "answer_type", "required_rule", "visibility_rule", "scale", "group_codes", "answer_statuses", "active", "source_metadata", "requirements"}
    if not changes or set(changes) - editable:
        raise ValidationError("Only editable question content may change; stable IDs cannot change.")
    for key, value in changes.items():
        setattr(question, key, value)
    question.save()
    _audit(actor, question.version, "catalog.question_updated", question_id=question.question_id, changed_fields=sorted(changes))
    return question


def _locked_translation(actor, entry, action):
    entry = ContentTranslation.objects.select_related("bundle__instrument_version__instrument__scope").get(pk=entry.pk)
    require_permission(actor, action, entry.bundle.instrument_version.instrument.scope)
    # Every write follows parent version -> bundle -> entry ordering.
    InstrumentVersion.objects.select_for_update().get(pk=entry.bundle.instrument_version_id)
    TranslationBundle.objects.select_for_update().get(pk=entry.bundle_id)
    return ContentTranslation.objects.select_for_update().select_related("bundle__instrument_version__instrument__scope").get(pk=entry.pk)


def _review_payload(actor, entry, original, translated, kind):
    """Bind the submitted review to the exact pair shown, its row and its reviewer."""
    return {
        "kind": kind, "actor": str(actor.pk), "id": str(entry.pk),
        "revision": entry.review_revision,
        "source_hash": source_hash(original), "translation_hash": source_hash(translated),
    }


def _check_review_token(token, expected):
    try:
        submitted = signing.loads(token, salt="catalog.review.v1")
    except (signing.BadSignature, TypeError, ValueError):
        raise ValidationError("The reviewed snapshot is invalid; reopen the current source and translation.")
    if submitted != expected:
        raise ValidationError("The source or translation changed; reopen and review the new snapshot.")


def _review_snapshot(actor, entry, original, translated, kind):
    payload = _review_payload(actor, entry, original, translated, kind)
    return {
        "source_text": original, "translation_text": translated,
        "review_revision": entry.review_revision,
        "reviewed_token": signing.dumps(payload, salt="catalog.review.v1"),
    }


@transaction.atomic
def translation_review_snapshot(actor, entry):
    """Show this pair together; the client must return its token without refreshing it."""
    entry = _locked_translation(actor, entry, "translation.review")
    original = source_texts(entry.bundle.instrument_version).get(entry.content_key)
    if original is None:
        raise ValidationError("Only current respondent content may be reviewed.")
    return _review_snapshot(actor, entry, original, entry.text, "translation")


@transaction.atomic
def edit_translation(actor, entry, text):
    entry = _locked_translation(actor, entry, "catalog.edit")
    version = entry.bundle.instrument_version
    original = source_texts(version).get(entry.content_key)
    if original is None:
        raise ValidationError("Only current respondent content may be translated.")
    entry.text, entry.status, entry.source_hash = text, "needs_review", source_hash(original)
    entry.reviewed_by, entry.reviewed_at = None, None
    entry.save()
    entry.refresh_from_db(fields=["review_revision"])
    _audit(actor, version, "catalog.translation_updated", content_key=entry.content_key, locale=entry.locale)
    return entry


@transaction.atomic
def approve_translation(actor, entry, *, reviewed_token):
    entry = _locked_translation(actor, entry, "translation.review")
    version = entry.bundle.instrument_version
    original = source_texts(version).get(entry.content_key)
    return _approve_locked_translation(actor, entry, original, reviewed_token=reviewed_token)


def _approve_locked_translation(actor, entry, original, *, reviewed_token):
    """Internal operation after authorization and version/bundle/entry locks.

    Keep pair validation, model validation, audit and revision refresh identical
    for the interactive reviewer and isolated synthetic-copy preparation.
    """
    version = entry.bundle.instrument_version
    if original is None or entry.source_hash != source_hash(original) or not entry.text.strip():
        raise ValidationError("Translation must be nonempty and refer to the current source.")
    _check_review_token(reviewed_token, _review_payload(actor, entry, original, entry.text, "translation"))
    if entry.status == "stale":
        raise ValidationError("Revise stale translations before requesting another review.")
    if entry.locale == "th" and entry.text != original:
        raise ValidationError("Thai text must match the reviewed Thai source.")
    entry.status, entry.reviewed_by, entry.reviewed_at = "approved", actor, timezone.now()
    entry.save()
    _audit(actor, version, "catalog.translation_approved", content_key=entry.content_key, locale=entry.locale,
           revision=entry.review_revision, source_hash=entry.source_hash, checksum=source_hash(entry.text))
    entry.refresh_from_db(fields=["review_revision"])
    return entry


@transaction.atomic
def publish_bundle(actor, bundle):
    bundle = TranslationBundle.objects.select_related("instrument_version__instrument__scope").get(pk=bundle.pk)
    require_permission(actor, "catalog.publish", bundle.instrument_version.instrument.scope)
    InstrumentVersion.objects.select_for_update().get(pk=bundle.instrument_version_id)
    bundle = TranslationBundle.objects.select_for_update().select_related("instrument_version__instrument__scope").get(pk=bundle.pk)
    if bundle.status != "draft":
        raise ValidationError("Only draft bundles can be published.")
    assert_complete_bundle(bundle)
    bundle.status, bundle.published_at = "published", timezone.now()
    bundle.save()
    _audit(actor, bundle.instrument_version, "catalog.bundle_published", bundle_id=str(bundle.pk))
    return bundle


@transaction.atomic
def publish_instrument_version(actor, version):
    version = InstrumentVersion.objects.select_for_update().select_related("instrument__scope").get(pk=version.pk)
    require_permission(actor, "catalog.publish", version.instrument.scope)
    if version.status != "draft":
        raise ValidationError("Only draft instrument versions can be published.")
    bundles = list(version.translation_bundles.filter(status="published"))
    if not bundles:
        raise ValidationError("Publish a complete approved translation bundle first.")
    for bundle in bundles:
        assert_complete_bundle(bundle)
    if not version.questions.filter(active=True).exists():
        raise ValidationError("An instrument version must contain questions.")
    # Multiple indicator bindings may share a formula. Read and lock each actual
    # formula once; cached per-binding copies otherwise republish a locked version.
    from .models import FormulaVersion
    for formula in FormulaVersion.objects.select_for_update().filter(
        pk__in=version.bindings.values("formula_id")
    ).order_by("pk"):
        if formula.status == "draft":
            formula.status = "published"
            formula.save()
    snapshot = {
        "texts": source_texts(version),
        "questions": list(version.questions.order_by("question_id").values("question_id", "answer_type", "required_rule", "visibility_rule", "scale", "group_codes", "answer_statuses", "active")),
        "options": list(QuestionOption.objects.filter(question__version=version).order_by("question__question_id", "code").values("question__question_id", "code", "label_th", "score", "answer_status")),
        "bindings": list(version.bindings.order_by("indicator__code").values("indicator__code", "formula__key", "formula__version", "formula__source_hash", "group_rules", "dimensions", "indicator_snapshot")),
    }
    version.checksum = hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
    version.status, version.published_at = "published", timezone.now()
    version.save()
    _audit(actor, version, "catalog.version_published", checksum=version.checksum)
    return version


def respondent_text(actor, bundle, content_key, locale):
    """No fallback, no draft strings, no configuration-only source content."""
    bundle = TranslationBundle.objects.select_related("instrument_version__instrument__scope").get(pk=bundle.pk)
    version = bundle.instrument_version
    require_permission(actor, "catalog.read", version.instrument.scope)
    if locale not in ("th", "en") or bundle.status != "published" or version.status != "published":
        raise ValidationError("This locale/version/bundle is not published.")
    original = source_texts(version).get(content_key)
    if original is None:
        raise ValidationError("Content is not intended for respondents.")
    entry = bundle.translations.filter(content_key=content_key, locale=locale, status="approved").first()
    if not entry or entry.source_hash != source_hash(original) or not entry.text.strip():
        raise ValidationError("Approved translation is unavailable; fallback is forbidden.")
    return entry.text


@transaction.atomic
def clone_instrument_version(actor, source, new_version):
    source = InstrumentVersion.objects.select_for_update().select_related("instrument__scope").get(pk=source.pk)
    require_permission(actor, "catalog.edit", source.instrument.scope)
    fields = {field.name: copy.deepcopy(getattr(source, field.name)) for field in source._meta.fields
              if field.name not in {"id", "version", "revision", "status", "checksum", "created_at", "published_at", "based_on", "instrument"}}
    target = InstrumentVersion.objects.create(instrument=source.instrument, version=new_version, revision=source.revision + 1, based_on=source, **fields)
    question_map = {}
    for old in source.questions.prefetch_related('options'):
        values = {f.name: copy.deepcopy(getattr(old, f.name)) for f in old._meta.fields if f.name not in {"id", "created_at", "version"}}
        question = Question.objects.create(version=target, **values)
        question_map[old.pk] = question
        for option in old.options.all():
            values = {f.name: copy.deepcopy(getattr(option, f.name)) for f in option._meta.fields if f.name not in {"id", "created_at", "question"}}
            QuestionOption.objects.create(question=question, **values)
    for content in source.contents.all():
        values = {f.name: copy.deepcopy(getattr(content, f.name)) for f in content._meta.fields if f.name not in {"id", "created_at", "version"}}
        InstrumentContent.objects.create(version=target, **values)
    for binding in source.bindings.select_related('indicator','formula').prefetch_related('questions'):
        new_binding = IndicatorBinding.objects.create(version=target, indicator=binding.indicator, formula=binding.formula,
            group_rules=copy.deepcopy(binding.group_rules), dimensions=copy.deepcopy(binding.dimensions),
            source_metadata=copy.deepcopy(binding.source_metadata), indicator_snapshot=copy.deepcopy(binding.indicator_snapshot))
        for question in binding.questions.all():
            BindingQuestion.objects.create(binding=new_binding, question=question_map[question.pk])
    # Explicit re-review preserves history and avoids carrying approval into a changed version.
    reserved_codes = set(source.translation_bundles.values_list("bundle_version", flat=True))
    for old_bundle in source.translation_bundles.order_by("bundle_version").prefetch_related('translations'):
        code = _clone_bundle_code(old_bundle.bundle_version, reserved_codes)
        reserved_codes.add(code)
        new_bundle = TranslationBundle.objects.create(instrument_version=target, bundle_version=code)
        for entry in old_bundle.translations.all():
            ContentTranslation.objects.create(bundle=new_bundle, content_key=entry.content_key, locale=entry.locale,
                text=entry.text, status="needs_review", source_hash=entry.source_hash, source_metadata=copy.deepcopy(entry.source_metadata))
    _audit(actor, target, "catalog.version_cloned", old_version=source.version, new_version=target.version)
    return target


def _clone_bundle_code(original, reserved):
    """Fresh target versions are private to this transaction; reserve all sibling IDs."""
    max_length = TranslationBundle._meta.get_field("bundle_version").max_length
    sequence = 1
    while True:
        suffix = "-copy" if sequence == 1 else f"-copy-{sequence}"
        candidate = original[:max_length - len(suffix)] + suffix
        if candidate not in reserved:
            return candidate
        sequence += 1


def _label_audit(actor, label, action, **metadata):
    from apps.auditlog.services import record_event
    record_event(organization=label.scope.organization, actor=actor, action=action,
        object_type="catalog.LocalizedLabel", object_id=str(label.pk),
        metadata={"scope_id": str(label.scope_id), "version": label.version, "content_key": label.key, "status": label.status, **metadata})


@transaction.atomic
def localized_label_review_snapshot(actor, label):
    label = LocalizedLabel.objects.select_for_update().select_related("scope").get(pk=label.pk)
    require_permission(actor, "translation.review", label.scope)
    return _review_snapshot(actor, label, label.source_th, label.text_en, "label")


@transaction.atomic
def review_localized_label(actor, label, *, reviewed_token):
    label = LocalizedLabel.objects.select_for_update().select_related("scope").get(pk=label.pk)
    require_permission(actor, "translation.review", label.scope)
    if label.published or not label.source_th.strip() or not label.text_en.strip():
        raise ValidationError("Only an unpublished, complete TH/EN label pair can be reviewed.")
    _check_review_token(reviewed_token, _review_payload(actor, label, label.source_th, label.text_en, "label"))
    label.source_hash, label.status = source_hash(label.source_th), "approved"
    label.reviewed_by, label.reviewed_at = actor, timezone.now()
    label.save()
    _label_audit(actor, label, "catalog.label_approved", revision=label.review_revision,
                 source_hash=label.source_hash, checksum=source_hash(label.text_en))
    label.refresh_from_db(fields=["review_revision"])
    return label


@transaction.atomic
def publish_localized_label(actor, label):
    label = LocalizedLabel.objects.select_for_update().select_related("scope").get(pk=label.pk)
    require_permission(actor, "catalog.publish", label.scope)
    if label.status != "approved" or label.source_hash != source_hash(label.source_th):
        raise ValidationError("A current approved label pair is required.")
    label.published, label.published_at = True, timezone.now()
    label.save()
    _label_audit(actor, label, "catalog.label_published")
    return label


def localized_label_text(actor, label, locale):
    label = LocalizedLabel.objects.select_related("scope").get(pk=label.pk)
    require_permission(actor, "catalog.read", label.scope)
    if locale not in ("th", "en") or not label.published or label.status != "approved" or label.source_hash != source_hash(label.source_th):
        raise ValidationError("This localized label is unavailable; draft/fallback content is forbidden.")
    return label.source_th if locale == "th" else label.text_en
