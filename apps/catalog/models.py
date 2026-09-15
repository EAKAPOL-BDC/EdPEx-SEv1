"""Versioned M1 definitions. No responses, formula execution, or F06 assessors."""
import hashlib
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q


FORMULA_KEYS = (
    "SAT_TOP2", "DIS_YES", "MEAN_5", "ENG_3", "PAIR_MEAN_TOP", "HAPPINESS_10",
    "DIMENSION_SAT", "ADMIN_MEAN", "ETHICS_TOP", "K_EXTERNAL", "SELF_VISION",
    "SELF_VALUES", "SELF_BEHAVIOUR", "SELF_COMPETENCY", "SELF_DIMENSION",
    "SELF_DIGITAL_POP", "TRAINING_HOURS", "TRAINING_PEOPLE", "SAFETY_ANY", "STUDY_VISIT",
)
VERSION_STATUSES = [(s, s) for s in ("draft", "published", "retired")]
TRANSLATION_STATUSES = [(s, s) for s in ("draft", "needs_review", "approved", "stale")]
ANSWER_TYPES = ("context_reference", "date", "date_time_range", "decimal", "evidence_reference", "integer_scale", "multi_choice", "review_metadata", "single_choice", "text")


def source_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ValidatedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Instrument(ValidatedModel):
    scope = models.ForeignKey("accounts.AccessScope", on_delete=models.PROTECT)
    code = models.CharField(max_length=3, choices=[(f"F0{i}", f"F0{i}") for i in range(1, 7)])

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["scope", "code"], name="catalog_instrument_scope_code"),
            models.CheckConstraint(condition=Q(code__in=[f"F0{i}" for i in range(1, 7)]), name="catalog_instrument_code"),
        ]

    def __str__(self):
        return self.code


class InstrumentVersion(ValidatedModel):
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT, related_name="versions")
    version = models.CharField(max_length=40)
    revision = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=12, choices=VERSION_STATUSES, default="draft")
    title_th = models.TextField()
    checksum = models.CharField(max_length=64, blank=True)
    assessment_method = models.CharField(max_length=24, choices=[(v, v) for v in ("survey", "verified_activity", "self_report")])
    evidence_required = models.BooleanField(default=False)
    assessor_scoring = models.BooleanField(default=False)
    response_unit = models.CharField(max_length=200, blank=True)
    identity_domain = models.CharField(max_length=100, blank=True)
    group_codes = models.JSONField(default=list, blank=True)
    workflow = models.JSONField(default=list, blank=True)
    requirements = models.JSONField(default=list, blank=True)
    source_metadata = models.JSONField(default=dict, blank=True)
    instructions_curated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    based_on = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["instrument", "version"], name="catalog_instrument_version"),
            models.CheckConstraint(condition=Q(status__in=["draft", "published", "retired"]), name="catalog_version_status"),
        ]

    def clean(self):
        if self.instrument_id and self.instrument.code == "F06":
            if self.assessment_method != "self_report" or self.evidence_required or self.assessor_scoring:
                raise ValidationError("F06 is self-report; assessor scoring and required evidence are forbidden.")
            if any(step in self.workflow for step in ("verified", "rejected", "assessor_scored")):
                raise ValidationError("F06 cannot use an assessor verification workflow.")
        parent_id, visited = self.based_on_id, {self.pk}
        while parent_id:
            if parent_id in visited:
                raise ValidationError("Version lineage cannot contain cycles.")
            visited.add(parent_id)
            parent = type(self).objects.filter(pk=parent_id).first()
            if parent is None or parent.instrument_id != self.instrument_id:
                raise ValidationError("Version lineage must remain within one instrument.")
            parent_id = parent.based_on_id
        if not self._state.adding:
            old = type(self).objects.get(pk=self.pk)
            if old.based_on_id != self.based_on_id:
                raise ValidationError("Version lineage is fixed when a version is created.")
            if old.status != "draft":
                changed = [f.attname for f in self._meta.concrete_fields if getattr(old, f.attname) != getattr(self, f.attname)]
                if changed and not (changed == ["status"] and old.status == "published" and self.status == "retired"):
                    raise ValidationError("Published versions are immutable; clone a new version.")


class VersionContent(ValidatedModel):
    """Shared guard; PostgreSQL triggers also protect direct SQL and bulk writes."""
    class Meta:
        abstract = True

    def clean(self):
        version = self.content_version()
        if version and (InstrumentVersion.objects.get(pk=version.pk).status != "draft" or version.translation_bundles.filter(status="published").exists()):
            raise ValidationError("Published content is immutable; clone a new version.")

    def delete(self, *args, **kwargs):
        self.clean()
        return super().delete(*args, **kwargs)


class Question(VersionContent):
    version = models.ForeignKey(InstrumentVersion, on_delete=models.PROTECT, related_name="questions")
    question_id = models.CharField(max_length=40, validators=[RegexValidator(r"^F0[1-6]-[A-Z0-9-]+$")])
    text_th = models.TextField()
    answer_type = models.CharField(max_length=30, choices=[(item, item) for item in ANSWER_TYPES])
    required_rule = models.JSONField(default=dict, blank=True)
    visibility_rule = models.JSONField(default=dict, blank=True)
    scale = models.JSONField(default=dict, blank=True)
    group_codes = models.JSONField(default=list, blank=True)
    answer_statuses = models.JSONField(default=list, blank=True)
    audience = models.CharField(max_length=30, default="respondent")
    active = models.BooleanField(default=True)
    source_metadata = models.JSONField(default=dict, blank=True)
    requirements = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["version", "question_id"], name="catalog_question_stable_id"),
            models.CheckConstraint(condition=Q(answer_type__in=ANSWER_TYPES), name="catalog_question_type_allowlist"),
        ]

    def content_version(self):
        return self.version

    def clean(self):
        super().clean()
        if self.version_id and not self.question_id.startswith(self.version.instrument.code + "-"):
            raise ValidationError("Question ID must belong to its instrument.")
        if self.version_id and self.version.instrument.code == "F06":
            if self.answer_type in ("evidence_reference", "review_metadata", "assessor_score"):
                raise ValidationError("F06 cannot collect assessor scores or evidence requirements.")

    def save(self, *args, **kwargs):
        old = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        result = super().save(*args, **kwargs)
        if old and any(getattr(old, f) != getattr(self, f) for f in ("text_th", "required_rule", "visibility_rule", "scale", "answer_type", "group_codes")):
            invalidate_translations(self.version_id)
        return result


class QuestionOption(VersionContent):
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="options")
    code = models.CharField(max_length=80)
    label_th = models.TextField()
    score = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    answer_status = models.CharField(max_length=30, default="answered")
    position = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["question", "code"], name="catalog_option_stable_code"),
            models.CheckConstraint(condition=Q(answer_status="answered") | Q(score__isnull=True), name="catalog_nonanswer_no_score"),
        ]

    def content_version(self):
        return self.question.version

    def save(self, *args, **kwargs):
        old = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        result = super().save(*args, **kwargs)
        if old and any(getattr(old, f) != getattr(self, f) for f in ("label_th", "score", "answer_status")):
            invalidate_translations(self.question.version_id)
        return result


class InstrumentContent(VersionContent):
    """Explicit instruction/rubric inventory; raw source sections stay configuration-only."""
    version = models.ForeignKey(InstrumentVersion, on_delete=models.PROTECT, related_name="contents")
    content_key = models.CharField(max_length=160)
    kind = models.CharField(max_length=24, choices=[(s, s) for s in ("instruction", "rubric", "title", "source_section", "ancillary")])
    text_th = models.TextField()
    audience = models.CharField(max_length=30, default="configuration_only")
    active = models.BooleanField(default=True)
    source_metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["version", "content_key"], name="catalog_content_stable_key"),
            models.CheckConstraint(condition=~Q(kind="source_section") | Q(audience="configuration_only"), name="catalog_raw_sections_private"),
        ]

    def content_version(self):
        return self.version

    def save(self, *args, **kwargs):
        old = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        result = super().save(*args, **kwargs)
        if old and old.text_th != self.text_th:
            invalidate_translations(self.version_id)
        return result


class FormulaVersion(ValidatedModel):
    scope = models.ForeignKey("accounts.AccessScope", on_delete=models.PROTECT)
    key = models.CharField(max_length=32, choices=[(key, key) for key in FORMULA_KEYS])
    version = models.CharField(max_length=40)
    status = models.CharField(max_length=12, choices=VERSION_STATUSES, default="draft")
    definition_th = models.TextField()
    parameters = models.JSONField(default=dict, blank=True)
    source_hash = models.CharField(max_length=64)
    requirements = models.JSONField(default=list, blank=True)
    source_metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["scope", "key", "version"], name="catalog_formula_version"),
            models.CheckConstraint(condition=Q(key__in=FORMULA_KEYS), name="catalog_formula_allowlist"),
            models.CheckConstraint(condition=Q(status__in=["draft", "published", "retired"]), name="catalog_formula_status"),
        ]

    def clean(self):
        if not self._state.adding and type(self).objects.get(pk=self.pk).status != "draft":
            raise ValidationError("Published formula versions are immutable.")


class Indicator(ValidatedModel):
    scope = models.ForeignKey("accounts.AccessScope", on_delete=models.PROTECT)
    code = models.CharField(max_length=20)
    original_name = models.TextField(null=True, blank=True)
    original_name_status = models.CharField(max_length=100)
    display_name_th = models.TextField()
    display_name_status = models.CharField(max_length=100)
    unit = models.CharField(max_length=30)
    direction = models.CharField(max_length=30)
    requirements = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["scope", "code"], name="catalog_indicator_stable_code")]


class IndicatorBinding(VersionContent):
    version = models.ForeignKey(InstrumentVersion, on_delete=models.PROTECT, related_name="bindings")
    indicator = models.ForeignKey(Indicator, on_delete=models.PROTECT, related_name="bindings")
    formula = models.ForeignKey(FormulaVersion, on_delete=models.PROTECT, related_name="bindings")
    questions = models.ManyToManyField(Question, through="BindingQuestion", related_name="bindings")
    group_rules = models.JSONField(default=dict, blank=True)
    dimensions = models.JSONField(default=list, blank=True)
    source_metadata = models.JSONField(default=dict, blank=True)
    indicator_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["version", "indicator"], name="catalog_indicator_binding_version")]

    def content_version(self):
        return self.version

    def clean(self):
        super().clean()
        if self.version_id and self.indicator_id and self.formula_id:
            if self.version.instrument.scope_id != self.indicator.scope_id or self.indicator.scope_id != self.formula.scope_id:
                raise ValidationError("Bindings cannot cross access scopes.")


class BindingQuestion(VersionContent):
    binding = models.ForeignKey(IndicatorBinding, on_delete=models.PROTECT)
    question = models.ForeignKey(Question, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["binding", "question"], name="catalog_binding_question_unique")]

    def content_version(self):
        return self.binding.version

    def clean(self):
        super().clean()
        if self.binding_id and self.question_id and self.binding.version_id != self.question.version_id:
            raise ValidationError("Binding questions must come from the same instrument version.")


class TranslationBundle(ValidatedModel):
    instrument_version = models.ForeignKey(InstrumentVersion, on_delete=models.PROTECT, related_name="translation_bundles")
    bundle_version = models.CharField(max_length=40)
    status = models.CharField(max_length=12, choices=VERSION_STATUSES, default="draft")
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["instrument_version", "bundle_version"], name="catalog_translation_bundle_version"),
            models.CheckConstraint(condition=Q(status__in=["draft", "published", "retired"]), name="catalog_bundle_status"),
        ]

    def clean(self):
        if not self._state.adding and type(self).objects.get(pk=self.pk).status != "draft":
            raise ValidationError("Published translation bundles are immutable.")


class ContentTranslation(ValidatedModel):
    bundle = models.ForeignKey(TranslationBundle, on_delete=models.PROTECT, related_name="translations")
    content_key = models.CharField(max_length=160)
    locale = models.CharField(max_length=2, choices=[("th", "ไทย"), ("en", "English")])
    text = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=TRANSLATION_STATUSES, default="draft")
    source_hash = models.CharField(max_length=64)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    source_metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["bundle", "content_key", "locale"], name="catalog_translation_key_locale"),
            models.CheckConstraint(condition=Q(locale__in=["th", "en"]), name="catalog_translation_locale"),
            models.CheckConstraint(condition=Q(status__in=["draft", "needs_review", "approved", "stale"]), name="catalog_translation_status"),
            models.CheckConstraint(condition=~Q(status="approved") | (Q(reviewed_by__isnull=False, reviewed_at__isnull=False) & ~Q(text="")), name="catalog_translation_approved_review"),
        ]

    def clean(self):
        if self.bundle_id and TranslationBundle.objects.get(pk=self.bundle_id).status != "draft":
            raise ValidationError("Published translations are immutable.")
        if not self._state.adding:
            old = type(self).objects.get(pk=self.pk)
            if self.text != old.text and self.status == "approved":
                raise ValidationError("Edited text must be submitted for a new review.")


def invalidate_translations(version_id):
    ContentTranslation.objects.filter(bundle__instrument_version_id=version_id, bundle__status="draft").update(
        status="stale", reviewed_by=None, reviewed_at=None,
    )


LABEL_NAMESPACES = ("ui", "group", "calendar", "indicator", "notification", "export", "validation", "glossary")


class LocalizedLabel(ValidatedModel):
    """Versioned system/group/calendar labels; respondent instrument bundles remain separate."""
    scope = models.ForeignKey("accounts.AccessScope", on_delete=models.PROTECT)
    namespace = models.CharField(max_length=20, choices=[(item, item) for item in LABEL_NAMESPACES])
    key = models.CharField(max_length=160)
    version = models.CharField(max_length=40)
    source_th = models.TextField()
    text_en = models.TextField(blank=True)
    source_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=TRANSLATION_STATUSES, default="draft")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    source_metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["scope", "namespace", "key", "version"], name="catalog_label_key_version"),
            models.CheckConstraint(condition=Q(namespace__in=LABEL_NAMESPACES), name="catalog_label_namespace"),
            models.CheckConstraint(condition=Q(status__in=["draft", "needs_review", "approved", "stale"]), name="catalog_label_status"),
            models.CheckConstraint(condition=~Q(status="approved") | (Q(reviewed_by__isnull=False, reviewed_at__isnull=False) & ~Q(text_en="")), name="catalog_label_reviewed"),
            models.CheckConstraint(condition=Q(published=False) | Q(status="approved", published_at__isnull=False), name="catalog_label_publication"),
        ]

    def clean(self):
        old = type(self).objects.filter(pk=self.pk).first()
        if old and old.published:
            raise ValidationError("Published labels are immutable; create a new label version.")
        if old and (old.source_th != self.source_th or old.text_en != self.text_en) and self.status == "approved":
            raise ValidationError("Changed labels must be reviewed again.")
        if self.status == "approved" and (not self.text_en.strip() or self.source_hash != source_hash(self.source_th)):
            raise ValidationError("Approved labels must match the nonempty reviewed source pair.")

    def save(self, *args, **kwargs):
        old = type(self).objects.filter(pk=self.pk).first()
        if old and not old.published and (old.source_th != self.source_th or old.text_en != self.text_en):
            self.status = "stale" if old.source_th != self.source_th else "needs_review"
            self.reviewed_by, self.reviewed_at = None, None
            self.source_hash = source_hash(self.source_th)
        return super().save(*args, **kwargs)
