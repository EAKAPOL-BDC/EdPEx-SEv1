"""Internal calculation snapshots. No model is registered in Django admin.

Snapshots contain restricted source material; services never return ORM records
to analyst-facing or public callers. PostgreSQL guards also protect bulk/SQL writes.
"""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q

from .codec import digest


HASH = RegexValidator(r"\A[0-9a-f]{64}\Z", "Use a SHA-256 digest.")
COMMIT = RegexValidator(r"\A[0-9a-f]{40}\Z", "Use a full commit SHA.")


class SnapshotQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Calculation snapshots cannot be updated through a queryset.")

    def delete(self):
        raise ValidationError("Calculation history is retained.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Use the calculation service to create a snapshot.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Calculation snapshots are immutable.")


class SnapshotRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = SnapshotQuerySet.as_manager()

    class Meta:
        abstract = True
        default_permissions = ()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Calculation snapshots are append-only.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Calculation history is retained.")


class CalculationRun(SnapshotRecord):
    collection_round = models.ForeignKey("rounds.CollectionRound", on_delete=models.PROTECT, related_name="calculation_runs")
    population_snapshot = models.ForeignKey("rounds.PopulationSnapshot", on_delete=models.PROTECT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    cutoff = models.DateTimeField()
    engine_commit = models.CharField(max_length=40, validators=[COMMIT])
    engine_hash = models.CharField(max_length=64, validators=[HASH])
    input_hash = models.CharField(max_length=64, validators=[HASH])
    manifest = models.JSONField()
    status = models.CharField(max_length=12, choices=[("building", "building"), ("complete", "complete")], default="building")
    result_hash = models.CharField(max_length=64, blank=True)
    input_count = models.PositiveIntegerField(default=0)
    result_count = models.PositiveIntegerField(default=0)
    sealed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["collection_round", "input_hash"], name="calc_run_source_unique"),
            models.CheckConstraint(condition=(Q(status="building", sealed_at__isnull=True, result_hash="", input_count=0, result_count=0)
                | (Q(status="complete", sealed_at__isnull=False, input_count__gt=0, result_count__gt=0) & ~Q(result_hash=""))),
                name="calc_run_seal_state"),
        ]
        indexes = [models.Index(fields=["collection_round", "created_at"], name="calc_run_round_created_idx")]

    def clean(self):
        super().clean()
        from django.utils import timezone
        if timezone.is_naive(self.cutoff):
            raise ValidationError("Cutoff must be timezone aware.")
        if self.population_snapshot.collection_round_id != self.collection_round_id:
            raise ValidationError("Population belongs to another round.")
        if self.population_snapshot.status != "frozen" or self.collection_round.population_snapshot_id != self.population_snapshot_id:
            raise ValidationError("Use the population pinned by the collection round.")
        if self._state.adding and self.status != "building":
            raise ValidationError("Runs are sealed only by the calculation service.")
        if self.input_hash != digest(self.manifest):
            raise ValidationError("Run manifest checksum mismatch.")


class CalculationInputSnapshot(SnapshotRecord):
    run = models.ForeignKey(CalculationRun, on_delete=models.PROTECT, related_name="inputs")
    round_instrument = models.ForeignKey("rounds.RoundInstrument", on_delete=models.PROTECT)
    binding = models.ForeignKey("catalog.IndicatorBinding", on_delete=models.PROTECT)
    group = models.ForeignKey("rounds.RespondentGroup", on_delete=models.PROTECT)
    series_key = models.CharField(max_length=64, validators=[HASH])
    definition = models.JSONField()
    payload = models.JSONField()
    source_hash = models.CharField(max_length=64, validators=[HASH])
    question_hash = models.CharField(max_length=64, validators=[HASH])
    formula_hash = models.CharField(max_length=64, validators=[HASH])

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["run", "series_key"], name="calc_input_run_series_unique")]

    def clean(self):
        super().clean()
        if self.run.status != "building":
            raise ValidationError("Cannot add sources to a sealed run.")
        if self.round_instrument.collection_round_id != self.run.collection_round_id:
            raise ValidationError("Instrument belongs to another collection round.")
        if self.binding.version_id != self.round_instrument.instrument_version_id:
            raise ValidationError("Binding belongs to another instrument version.")
        if self.group.scope_id != self.run.collection_round.scope_id:
            raise ValidationError("Group belongs to another scope.")
        if self.source_hash != digest(self.payload) or self.question_hash != digest(self.definition["questions"]) or self.formula_hash != digest(self.definition["formula"]):
            raise ValidationError("Input snapshot checksum mismatch.")


class IndicatorResult(SnapshotRecord):
    run = models.ForeignKey(CalculationRun, on_delete=models.PROTECT, related_name="results")
    source = models.OneToOneField(CalculationInputSnapshot, on_delete=models.PROTECT, related_name="result")
    indicator_code = models.CharField(max_length=20)
    series_key = models.CharField(max_length=64, validators=[HASH])
    payload = models.JSONField()
    result_hash = models.CharField(max_length=64, validators=[HASH])

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["run", "series_key"], name="calc_result_run_series_unique")]

    def clean(self):
        super().clean()
        if self.run.status != "building" or self.source.run_id != self.run_id:
            raise ValidationError("Result must be created in its unsealed source run.")
        if self.series_key != self.source.series_key or self.indicator_code != self.source.definition["series"]["indicator_code"]:
            raise ValidationError("Result and source series differ.")
        if self.result_hash != digest(self.payload):
            raise ValidationError("Result checksum mismatch.")


class CalculationRequest(SnapshotRecord):
    collection_round = models.ForeignKey("rounds.CollectionRound", on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=160)
    request_hash = models.CharField(max_length=64, validators=[HASH])
    run = models.ForeignKey(CalculationRun, on_delete=models.PROTECT, related_name="requests")

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["collection_round", "actor", "idempotency_key"], name="calc_request_actor_key_unique")]

    def clean(self):
        super().clean()
        if not self.idempotency_key.strip():
            raise ValidationError("An idempotency key is required.")
        if self.run.collection_round_id != self.collection_round_id or self.run.status != "complete":
            raise ValidationError("Request must point to a complete run of its round.")
        if self.request_hash != self.run.input_hash:
            raise ValidationError("Request hash does not match its run.")


class StoredSourceSelection(SnapshotRecord):
    """Attestation that all series of one F06 binding came from the stored source adapter."""
    run = models.OneToOneField(CalculationRun, on_delete=models.PROTECT, related_name='stored_source')
    round_instrument = models.ForeignKey('rounds.RoundInstrument', on_delete=models.PROTECT, related_name='stored_calculations')
    source_kind = models.CharField(max_length=32, default='f06_revisions')

    class Meta:
        default_permissions = ()

    def clean(self):
        if self.run.status != 'complete' or self.run.collection_round_id != self.round_instrument.collection_round_id:
            raise ValidationError('Stored source selection must match a complete run of its round.')
        code = self.round_instrument.instrument_version.instrument.code
        if not ((self.source_kind == 'f05_activity_revisions' and code == 'F05') or (self.source_kind == 'f06_revisions' and code == 'F06') or (self.source_kind == 'anonymous_surveys' and code in {'F01','F02','F03','F04','F05','F06'} and hasattr(self.round_instrument,'survey_profile'))):
            raise ValidationError('Unsupported stored source adapter.')


class ResultReviewRequest(SnapshotRecord):
    run = models.OneToOneField(CalculationRun, on_delete=models.PROTECT, related_name='review_request')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    reason = models.TextField()
    review_token = models.CharField(max_length=64, validators=[HASH])

    class Meta:
        default_permissions = ()

    def clean(self):
        if self.run.status != 'complete' or not StoredSourceSelection.objects.filter(run=self.run).exists():
            raise ValidationError('Review requires a sealed calculation from the database source adapter.')
        if not self.reason.strip() or len(self.reason) > 2000:
            raise ValidationError('Record a review reason, up to 2000 characters.')
        if self.review_token != digest({'run_id': str(self.run_id), 'input_hash': self.run.input_hash, 'result_hash': self.run.result_hash}):
            raise ValidationError('Review token does not match the sealed result set.')


class ResultDecision(SnapshotRecord):
    review = models.OneToOneField(ResultReviewRequest, on_delete=models.PROTECT, related_name='decision')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    outcome = models.CharField(max_length=12, choices=[('approved', 'approved'), ('returned', 'returned')])
    reason = models.TextField()
    reviewed_token = models.CharField(max_length=64, validators=[HASH])
    previous_approval = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True, related_name='successors')

    class Meta:
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=models.Q(outcome__in=['approved', 'returned']), name='result_decision_outcome')]

    def clean(self):
        if self.actor_id in {self.review.requested_by_id, self.review.run.created_by_id}:
            from .admin_review import can_self_review, PREFIX
            from apps.governance.simulation import can_simulate_review
            if not can_simulate_review(self.actor,self.review.run,self.reason) and (not can_self_review(self.actor, self.review.run.collection_round.scope) or not self.reason.startswith(PREFIX)):
                raise ValidationError('A different person must review the aggregate results.')
        if not self.reason.strip() or len(self.reason) > 2000 or self.reviewed_token != self.review.review_token:
            raise ValidationError('Record a reason and the exact reviewed result token.')
        if self.previous_approval_id:
            previous = self.previous_approval
            if (self.outcome != 'approved' or previous.outcome != 'approved'
                    or previous.review.run.stored_source.round_instrument_id != self.review.run.stored_source.round_instrument_id
                    or previous.review.run.cutoff > self.review.run.cutoff):
                raise ValidationError('Correction must retain the previous approval of this source stream.')


class DemoDataset(models.Model):
    """Explicitly synthetic data; never a ResultDecision or a production run."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope = models.ForeignKey('accounts.AccessScope', on_delete=models.PROTECT)
    key = models.CharField(max_length=40)
    label = models.CharField(max_length=120, default='ข้อมูลสมมุติ ปี 2569')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    catalog_hash = models.CharField(max_length=64)
    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=['scope','key'], name='demo_dataset_scope_key')]


class DemoSeries(models.Model):
    dataset = models.ForeignKey(DemoDataset, on_delete=models.CASCADE, related_name='series')
    indicator_code = models.CharField(max_length=20)
    indicator_label = models.TextField()
    form_code = models.CharField(max_length=3)
    group_code = models.CharField(max_length=20)
    group_label = models.TextField()
    dimension = models.CharField(max_length=40, blank=True)
    dimension_label = models.TextField(blank=True)
    unit = models.CharField(max_length=30)
    direction = models.CharField(max_length=30)
    formula_key = models.CharField(max_length=40)
    formula_version = models.CharField(max_length=20)
    context_key = models.CharField(max_length=80)
    source = models.JSONField()
    source_hash = models.CharField(max_length=64)
    result = models.JSONField()
    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=['dataset','indicator_code','group_code','dimension'], name='demo_series_unique')]


class ActivityRecord(SnapshotRecord):
    round_instrument = models.ForeignKey('rounds.RoundInstrument', on_delete=models.PROTECT, related_name='activity_records')
    member = models.ForeignKey('rounds.PopulationMember', on_delete=models.PROTECT)
    activity_code = models.CharField(max_length=100)
    session_code = models.CharField(max_length=100)
    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=['round_instrument','member','activity_code','session_code'],name='f05_activity_session_person')]
    def clean(self):
        ri=self.round_instrument
        if ri.instrument_version.instrument.code != 'F05' or self.member.snapshot_id != ri.collection_round.population_snapshot_id or self.member.group.code not in {'ST1','ST2'}:
            raise ValidationError('F05 requires a person from the pinned staff population.')


class ActivityRevision(SnapshotRecord):
    record = models.ForeignKey(ActivityRecord,on_delete=models.PROTECT,related_name='revisions')
    number = models.PositiveIntegerField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    status = models.CharField(max_length=24, choices=[(s,s) for s in ['draft','submitted','revision_requested','accepted','rejected']])
    payload = models.JSONField()
    reason = models.TextField()
    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=['record','number'],name='f05_revision_number'),
            models.CheckConstraint(condition=Q(status__in=['draft','submitted','revision_requested','accepted','rejected']),name='f05_revision_status')]
    def clean(self):
        from .activities import validate_payload
        validate_payload(self.payload,self.record.round_instrument.collection_round)
        if not self.reason.strip(): raise ValidationError('A change/review reason is required.')
