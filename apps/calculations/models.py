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
