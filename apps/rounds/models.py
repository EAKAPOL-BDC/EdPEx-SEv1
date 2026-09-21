"""M1 temporal and population identity domain (Blueprint 7–9, 24–26, 33).

Dates are real Gregorian dates; period ends are exclusive. These tables do not
store survey answers and intentionally have no FK to any survey response.
"""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models import F, Q
from django.utils import timezone


class ValidatedQuerySet(models.QuerySet):
    """Prevent bulk ORM operations from bypassing relation/history validation."""

    def update(self, **kwargs):
        raise ValidationError("Use the validated domain services to update records.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Create records through their validated save method.")

    def bulk_update(self, objs, fields, **kwargs):
        raise ValidationError("Use the validated domain services to update records.")

    def delete(self):
        count = 0
        by_model = {}
        with transaction.atomic():
            for instance in self.select_for_update():
                deleted, details = instance.delete()
                count += deleted
                for label, value in details.items():
                    by_model[label] = by_model.get(label, 0) + value
        return count, by_model


class DomainRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("accounts.Organization", on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = ValidatedQuerySet.as_manager()

    class Meta:
        abstract = True

    def domain_scope(self):
        return self.scope

    def clean(self):
        super().clean()
        scope = self.domain_scope()
        if self.organization_id and self.organization_id != scope.organization_id:
            raise ValidationError({"organization": "Organization must match the access scope."})
        self.organization_id = scope.organization_id

    def check_history(self, previous):
        pass

    def lock_dependencies(self):
        """Lock parent rows before checking publication/freeze state."""

    def save(self, *args, **kwargs):
        with transaction.atomic():
            self.lock_dependencies()
            self.organization_id = self.organization_id or self.domain_scope().organization_id
            previous = type(self).objects.select_for_update().filter(pk=self.pk).first()
            if previous:
                self.check_history(previous)
            self.full_clean()
            return super().save(*args, **kwargs)

    def unchanged(self, previous, exceptions=()):
        ignored = {"updated_at", *exceptions}
        for field in self._meta.concrete_fields:
            if field.name not in ignored and getattr(self, field.attname) != getattr(previous, field.attname):
                raise ValidationError("This historical record is immutable; create a new version.")


class Calendar(DomainRecord):
    class Type(models.TextChoices):
        FISCAL = "fiscal", "ปีงบประมาณ"
        ACADEMIC = "academic", "ปีการศึกษา"
        CALENDAR = "calendar", "ปีปฏิทิน"
        CUSTOM = "custom", "กำหนดเอง"

    scope = models.ForeignKey("accounts.AccessScope", on_delete=models.PROTECT)
    code = models.CharField(max_length=80)
    label = models.CharField(max_length=255)
    calendar_type = models.CharField(max_length=12, choices=Type.choices)
    timezone = models.CharField(max_length=64, default="Asia/Bangkok")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["scope", "code"], name="round_calendar_scope_code")]

    def clean(self):
        super().clean()
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValidationError({"timezone": "Use a valid IANA time zone."}) from error

    def check_history(self, previous):
        if previous.periods.exists():
            self.unchanged(previous)


class ReportingPeriod(DomainRecord):
    calendar = models.ForeignKey(Calendar, on_delete=models.PROTECT, related_name="periods")
    code = models.CharField(max_length=80)
    reporting_year_be = models.PositiveIntegerField(validators=[MinValueValidator(2565)])
    start_date = models.DateField()
    end_date = models.DateField(help_text="Exclusive Gregorian end date")
    parent = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="children")
    version = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["calendar", "code", "version"], name="round_period_code_version"),
            models.CheckConstraint(condition=Q(reporting_year_be__gte=2565), name="round_period_year_2565"),
            models.CheckConstraint(condition=Q(end_date__gt=F("start_date")), name="round_period_positive_window"),
            models.CheckConstraint(condition=Q(version__gte=1), name="round_period_positive_version"),
            models.CheckConstraint(condition=(Q(approved=False, approved_by__isnull=True, approved_at__isnull=True) | Q(approved=True, approved_by__isnull=False, approved_at__isnull=False)), name="round_period_approval_actor"),
        ]

    def domain_scope(self):
        return self.calendar.scope

    def lock_dependencies(self):
        self.calendar = Calendar.objects.select_for_update().get(pk=self.calendar_id)
        if self.parent_id:
            self.parent = type(self).objects.select_for_update().get(pk=self.parent_id)

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.start_date >= self.end_date:
            raise ValidationError("Period must have start < exclusive end.")
        if self.parent_id:
            if self.parent_id == self.pk or self.parent.calendar_id != self.calendar_id:
                raise ValidationError({"parent": "Parent must be another period in the same calendar."})
            if self.parent.parent_id:
                raise ValidationError({"parent": "M1 supports year periods with one child level."})
            if self.reporting_year_be != self.parent.reporting_year_be:
                raise ValidationError({"reporting_year_be": "Child reporting year must match its parent."})
            if self.start_date < self.parent.start_date or self.end_date > self.parent.end_date:
                raise ValidationError("Child period must be contained in the parent.")
        if self.start_date and self.end_date:
            # A revision of the same logical period may overlap its predecessor.
            siblings = type(self).objects.filter(calendar_id=self.calendar_id, parent_id=self.parent_id).exclude(pk=self.pk).exclude(code=self.code)
            if siblings.filter(start_date__lt=self.end_date, end_date__gt=self.start_date).exists():
                raise ValidationError("Sibling periods must not overlap; period end is exclusive.")
        if self.approved and not (self.approved_by_id and self.approved_at):
            raise ValidationError("Approval records the actor and actual approval time.")
        if not self.approved and (self.approved_by_id or self.approved_at):
            raise ValidationError("Draft periods cannot claim an approval actor or time.")

    def check_history(self, previous):
        if previous.approved:
            self.unchanged(previous)
        elif previous.collection_rounds.exists() or previous.children.exists():
            self.unchanged(previous, exceptions=("approved", "approved_by", "approved_at"))

    def delete(self, *args, **kwargs):
        if type(self).objects.filter(pk=self.pk, approved=True).exists():
            raise ValidationError("Approved periods are retained; create a revision.")
        return super().delete(*args, **kwargs)


class CollectionRound(DomainRecord):
    class Status(models.TextChoices):
        DRAFT = "draft", "ร่าง"
        READY = "ready", "พร้อมเปิด"
        OPEN = "open", "เปิดรับ"
        CLOSED = "closed", "ปิดรับ"
        CALCULATING = "calculating", "คำนวณ"
        REVIEW = "review", "ตรวจผล"
        APPROVED = "approved", "รับรองผล"
        ARCHIVED = "archived", "เก็บประวัติ"

    scope = models.ForeignKey("accounts.AccessScope", on_delete=models.PROTECT)
    period = models.ForeignKey(ReportingPeriod, on_delete=models.PROTECT, related_name="collection_rounds")
    code = models.CharField(max_length=80)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_collection_rounds")
    open_at = models.DateTimeField()
    due_at = models.DateTimeField()
    close_at = models.DateTimeField(help_text="Exclusive collection cutoff")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    privacy_notice = models.TextField(blank=True)
    data_kind = models.CharField(max_length=12, default='real', choices=[('real','ข้อมูลจริง'),('synthetic','ข้อมูลสมมุติ')])
    schedule_confirmed = models.BooleanField(default=True)
    population_snapshot = models.ForeignKey("PopulationSnapshot", on_delete=models.PROTECT, null=True, blank=True, related_name="pinned_by_rounds")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["scope", "code"], name="round_scope_code"),
            models.CheckConstraint(condition=Q(due_at__gte=F("open_at")) & Q(close_at__gte=F("due_at")) & Q(close_at__gt=F("open_at")), name="round_collection_time_order"),
        ]

    def clean(self):
        super().clean()
        if self.scope_id != self.period.calendar.scope_id:
            raise ValidationError({"period": "Round and reporting calendar must have the same scope."})
        if not (self.open_at <= self.due_at <= self.close_at and self.open_at < self.close_at):
            raise ValidationError("Require open <= due <= close and open < close.")
        if any(timezone.is_naive(value) for value in (self.open_at, self.due_at, self.close_at)):
            raise ValidationError("Collection timestamps must be timezone-aware.")
        from apps.accounts.permissions import has_active_membership

        previous = type(self).objects.filter(pk=self.pk).values("owner_id", "scope_id").first()
        assigning_owner = previous is None or (previous["owner_id"], previous["scope_id"]) != (self.owner_id, self.scope_id)
        # Validate membership when assigning a person, not when closing their
        # historical work after departure. Services still authorize the actor.
        if assigning_owner and not has_active_membership(self.owner, self.scope):
            raise ValidationError({"owner": "Round owner must be an active member of this organization."})
        if self.population_snapshot_id:
            if self.population_snapshot.collection_round_id != self.pk or self.population_snapshot.status != PopulationSnapshot.Status.FROZEN:
                raise ValidationError("Pinned population must be a frozen snapshot of this round.")

    def lock_dependencies(self):
        self.period = ReportingPeriod.objects.select_for_update().get(pk=self.period_id)

    def check_history(self, previous):
        if self.data_kind != previous.data_kind:
            raise ValidationError('เปลี่ยนข้อมูลสมมุติเป็นข้อมูลจริงไม่ได้ / Collection data kind is immutable.')
        if self.scope_id != previous.scope_id:
            raise ValidationError("Round scope is a stable identity; create a new round.")
        if self.period_id != previous.period_id and (previous.round_instruments.exists() or previous.population_snapshots.exists() or previous.responsibilities.exists()):
            raise ValidationError("A round with dependent records cannot change its reporting period.")
        if self.status != previous.status and not getattr(self, "_allow_transition", False):
            raise ValidationError("Change round status through transition_round.")
        if previous.status != self.Status.DRAFT:
            self.unchanged(previous, exceptions=("status",))

    def save(self, *args, **kwargs):
        if self._state.adding and self.status != self.Status.DRAFT:
            raise ValidationError("Create a draft round first.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if type(self).objects.filter(pk=self.pk).exclude(status=self.Status.DRAFT).exists():
            raise ValidationError("Used rounds are retained.")
        return super().delete(*args, **kwargs)

    def accepting_at(self, at=None):
        at = at or timezone.now()
        return self.status == self.Status.OPEN and self.open_at <= at < self.close_at


class RoundInstrument(DomainRecord):
    collection_round = models.ForeignKey(CollectionRound, on_delete=models.PROTECT, related_name="round_instruments")
    instrument_version = models.ForeignKey("catalog.InstrumentVersion", on_delete=models.PROTECT)
    translation_bundle = models.ForeignKey("catalog.TranslationBundle", on_delete=models.PROTECT)
    context = models.CharField(max_length=160, default="default")
    configuration = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["collection_round", "instrument_version", "context"], name="round_instrument_context")]

    def domain_scope(self):
        return self.collection_round.scope

    def lock_dependencies(self):
        self.collection_round = CollectionRound.objects.select_for_update().get(pk=self.collection_round_id)

    def clean(self):
        super().clean()
        if self.instrument_version.source_metadata.get('synthetic_only') and self.collection_round.data_kind!='synthetic':
            raise ValidationError('แบบฟอร์มจำลองใช้เก็บข้อมูลจริงไม่ได้ / Simulation-only form.')
        if self.instrument_version.instrument.scope_id != self.collection_round.scope_id:
            raise ValidationError("Instrument and round must share the same scope.")
        if self.translation_bundle.instrument_version_id != self.instrument_version_id:
            raise ValidationError("Translation bundle must belong to the selected instrument version.")
        previous = type(self).objects.filter(pk=self.pk).values(
            "collection_round_id", "instrument_version_id", "translation_bundle_id",
        ).first()
        selected = (self.collection_round_id, self.instrument_version_id, self.translation_bundle_id)
        if previous is None or selected != tuple(previous[k] for k in ('collection_round_id','instrument_version_id','translation_bundle_id')):
            from apps.governance.policies import validate_period
            validate_period(self.instrument_version.instrument.code,self.collection_round.period)
        changing_selection = previous is None or selected != tuple(previous[field] for field in (
            "collection_round_id", "instrument_version_id", "translation_bundle_id",
        ))
        from apps.catalog.models import InstrumentVersion

        if changing_selection and InstrumentVersion.objects.filter(pk=self.instrument_version_id, status="retired").exists():
            raise ValidationError("Retired versions cannot be selected for a new round binding.")
        if self.collection_round.status != CollectionRound.Status.DRAFT:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous:
                self.unchanged(previous)
            else:
                raise ValidationError("Round bindings are frozen after the draft stage.")
        # Configuration is intentionally closed in M1; later collection bundles
        # need a typed, validated schema before they may alter instrument rules.
        if self.configuration:
            raise ValidationError({"configuration": "M1 does not permit unvalidated instrument overrides."})

    def check_history(self, previous):
        if previous.collection_round.status != CollectionRound.Status.DRAFT:
            self.unchanged(previous)

    def delete(self, *args, **kwargs):
        if CollectionRound.objects.filter(pk=self.collection_round_id).exclude(status=CollectionRound.Status.DRAFT).exists():
            raise ValidationError("Used instrument and translation bindings are retained.")
        return super().delete(*args, **kwargs)


class RespondentGroup(DomainRecord):
    scope = models.ForeignKey("accounts.AccessScope", on_delete=models.PROTECT)
    code = models.CharField(max_length=80)
    label = models.CharField(max_length=255)
    parent = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="children")
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["scope", "code"], name="round_group_scope_code")]

    def clean(self):
        super().clean()
        visited = {self.pk}
        parent = self.parent
        while parent:
            if parent.pk in visited or parent.scope_id != self.scope_id:
                raise ValidationError("Group ancestry must be acyclic and within one scope.")
            visited.add(parent.pk)
            parent = parent.parent

    def check_history(self, previous):
        if self.scope_id != previous.scope_id or self.code != previous.code:
            raise ValidationError("Respondent group scope and stable code cannot change.")
        if previous.members.exists() or PopulationSnapshot.objects.filter(collection_round__scope_id=previous.scope_id, counts_by_group__has_key=previous.code).exists():
            self.unchanged(previous, exceptions=("active",))

    def delete(self, *args, **kwargs):
        previous = type(self).objects.get(pk=self.pk)
        if PopulationSnapshot.objects.filter(collection_round__scope_id=previous.scope_id, counts_by_group__has_key=previous.code).exists():
            raise ValidationError("Population group definitions referenced by counts are retained.")
        return super().delete(*args, **kwargs)


class PopulationSnapshot(DomainRecord):
    class Status(models.TextChoices):
        DRAFT = "draft", "ร่าง"
        FROZEN = "frozen", "ตรึงแล้ว"

    collection_round = models.ForeignKey(CollectionRound, on_delete=models.PROTECT, related_name="population_snapshots")
    definition = models.TextField()
    counting_unit = models.CharField(max_length=80)
    version = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.DRAFT)
    counts_by_group = models.JSONField(default=dict, blank=True)
    captured_at = models.DateTimeField(default=timezone.now)
    frozen_at = models.DateTimeField(null=True, blank=True)
    source = models.ForeignKey("DataSource", on_delete=models.PROTECT, null=True, blank=True, related_name="population_snapshots")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["collection_round", "version"], name="round_population_version"),
            models.CheckConstraint(condition=Q(version__gte=1), name="round_population_positive_version"),
            models.CheckConstraint(condition=Q(status="draft", frozen_at__isnull=True) | Q(status="frozen", frozen_at__isnull=False), name="round_population_frozen_time"),
        ]

    def domain_scope(self):
        return self.collection_round.scope

    def lock_dependencies(self):
        self.collection_round = CollectionRound.objects.select_for_update().get(pk=self.collection_round_id)
        if self.source_id:
            self.source = DataSource.objects.select_for_update().get(pk=self.source_id)

    def clean(self):
        super().clean()
        if self.source_id and self.source.scope_id != self.collection_round.scope_id:
            raise ValidationError("Population source and round must share one access scope.")
        if not isinstance(self.counts_by_group, dict) or any(not isinstance(key, str) or type(value) is not int or value < 0 for key, value in self.counts_by_group.items()):
            raise ValidationError("Population counts are nonnegative integers keyed by stable group code.")
        if self.counts_by_group:
            codes = set(RespondentGroup.objects.filter(scope=self.collection_round.scope, code__in=self.counts_by_group).values_list("code", flat=True))
            if codes != set(self.counts_by_group):
                raise ValidationError("Population counts contain a group outside this scope.")
        if self.collection_round.status not in (CollectionRound.Status.DRAFT, CollectionRound.Status.READY):
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous:
                self.unchanged(previous)
            else:
                raise ValidationError("Do not replace the population of an opened round.")
        if self.status == self.Status.FROZEN and not self.frozen_at:
            raise ValidationError("A frozen snapshot requires its actual freeze time.")
        if self.status == self.Status.FROZEN and not self.source_id:
            raise ValidationError("A frozen population requires its actual source provenance.")
        if self.status == self.Status.DRAFT and self.frozen_at:
            raise ValidationError("Draft snapshots do not have a freeze time.")

    def check_history(self, previous):
        if self.collection_round_id != previous.collection_round_id:
            raise ValidationError("Population snapshot round is a stable identity.")
        if previous.status == self.Status.FROZEN:
            self.unchanged(previous)
        elif self.status != previous.status and not getattr(self, "_allow_freeze", False):
            raise ValidationError("Freeze population snapshots through freeze_population.")

    def save(self, *args, **kwargs):
        if self._state.adding and self.status != self.Status.DRAFT:
            raise ValidationError("Create the draft snapshot first.")
        with transaction.atomic():
            # PostgreSQL UPDATE locks this row before its round guard runs.
            # Keep ORM edits in the same order as freeze and direct SQL edits.
            type(self).objects.select_for_update().filter(pk=self.pk).first()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if type(self).objects.filter(pk=self.pk, status=self.Status.FROZEN).exists():
            raise ValidationError("Frozen population snapshots are retained.")
        return super().delete(*args, **kwargs)


class PopulationMember(DomainRecord):
    """Restricted eligibility identity only: no answer, response or invitation FK."""

    snapshot = models.ForeignKey(PopulationSnapshot, on_delete=models.PROTECT, related_name="members")
    group = models.ForeignKey(RespondentGroup, on_delete=models.PROTECT, related_name="members")
    eligible_unit_key = models.CharField(max_length=160)
    employment_facts = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["snapshot", "group", "eligible_unit_key"], name="round_population_member_unit")]

    def domain_scope(self):
        return self.snapshot.collection_round.scope

    def lock_dependencies(self):
        # save/delete hold the member row first, so its persisted source cannot
        # change while we acquire both parent locks in a deterministic order.
        source_id = type(self).objects.filter(pk=self.pk).values_list("snapshot_id", flat=True).first()
        snapshot_ids = {self.snapshot_id}
        if source_id:
            snapshot_ids.add(source_id)
        snapshots = {
            snapshot.pk: snapshot
            for snapshot in PopulationSnapshot.objects.select_for_update().filter(
                pk__in=snapshot_ids
            ).order_by("pk")
        }
        if len(snapshots) != len(snapshot_ids):
            raise ValidationError("Population snapshot no longer exists.")
        self.snapshot = snapshots[self.snapshot_id]
        if any(snapshot.status == PopulationSnapshot.Status.FROZEN for snapshot in snapshots.values()):
            raise ValidationError("Members of a frozen snapshot cannot be changed.")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            # Direct PostgreSQL UPDATE acquires the member tuple before firing
            # its parent-lock trigger. Match that order to avoid lock inversion.
            type(self).objects.select_for_update().filter(pk=self.pk).first()
            return super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.group.scope_id != self.snapshot.collection_round.scope_id:
            raise ValidationError("Population group and snapshot must share one scope.")
        if self.snapshot.status == PopulationSnapshot.Status.FROZEN:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous:
                self.unchanged(previous)
            else:
                raise ValidationError("Members cannot be added to a frozen snapshot.")
        if not isinstance(self.employment_facts, dict):
            raise ValidationError("Employment facts must be a JSON object.")

    def check_history(self, previous):
        if previous.snapshot.status == PopulationSnapshot.Status.FROZEN:
            self.unchanged(previous)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            current = type(self).objects.select_for_update().filter(pk=self.pk).first()
            if current is not None:
                # A caller may hold an instance predating an earlier move.
                self.snapshot_id = current.snapshot_id
                self.lock_dependencies()
            return super().delete(*args, **kwargs)


class ResponsibilityAssignment(DomainRecord):
    scope = models.ForeignKey("accounts.AccessScope", on_delete=models.PROTECT)
    collection_round = models.ForeignKey(CollectionRound, on_delete=models.PROTECT, null=True, blank=True, related_name="responsibilities")
    primary = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="primary_responsibilities")
    backup = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="backup_responsibilities")
    active_from = models.DateTimeField()
    active_until = models.DateTimeField(null=True, blank=True, help_text="Exclusive end")
    reason = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(active_until__isnull=True) | Q(active_until__gt=F("active_from")), name="round_responsibility_date_order"),
            models.CheckConstraint(condition=Q(backup__isnull=True) | ~Q(primary=F("backup")), name="round_responsibility_distinct"),
        ]

    def clean(self):
        super().clean()
        from apps.accounts.permissions import has_active_membership

        if self.collection_round_id and self.collection_round.scope_id != self.scope_id:
            raise ValidationError("Responsibility and round must share a scope.")
        previous = type(self).objects.filter(pk=self.pk).values("scope_id", "primary_id", "backup_id").first()
        for field in ("primary", "backup"):
            user = getattr(self, field)
            assigning_person = previous is None or previous["scope_id"] != self.scope_id or previous[field + "_id"] != getattr(self, field + "_id")
            if assigning_person and user is not None and not has_active_membership(user, self.scope):
                raise ValidationError({field: "Responsible users must be active members of this organization."})
        if self.primary_id == self.backup_id:
            raise ValidationError("Primary and backup must be different users.")
        if self.active_until and self.active_until <= self.active_from:
            raise ValidationError("Assignment end must follow its start.")
        if timezone.is_naive(self.active_from) or (self.active_until and timezone.is_naive(self.active_until)):
            raise ValidationError("Responsibility timestamps must be timezone-aware.")

    def check_history(self, previous):
        # Personnel transfer is a new dated row; ending an assignment preserves
        # its original people and start, including in historic audit entries.
        self.unchanged(previous, exceptions=("active_until",))
        if previous.active_until and self.active_until != previous.active_until:
            raise ValidationError("An ended responsibility assignment is immutable.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Responsibility history is retained; end the assignment instead.")


class DataSource(DomainRecord):
    class Type(models.TextChoices):
        RAW = "raw", "ข้อมูลรายรายการ"
        AGGREGATE = "aggregate", "ผลรวมเดิม"

    scope = models.ForeignKey("accounts.AccessScope", on_delete=models.PROTECT)
    title = models.CharField(max_length=500)
    location = models.TextField(help_text="Actual report/page, restricted reference, or source URL")
    source_type = models.CharField(max_length=12, choices=Type.choices)
    original_method = models.CharField(max_length=160, null=True, blank=True)
    instrument_version_original = models.CharField(max_length=80, null=True, blank=True)
    formula_version_original = models.CharField(max_length=80, null=True, blank=True)
    checksum_sha256 = models.CharField(max_length=64, blank=True, validators=[RegexValidator(r"^[a-fA-F0-9]{64}$", "Enter an actual SHA-256 digest.")])
    occurred_at = models.DateField(null=True, blank=True)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)
    limitations = models.TextField(blank=True)
    supersedes = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True, related_name="successor")
    revision = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(revision__gte=1), name="round_source_positive_revision")]

    def clean(self):
        super().clean()
        if self.supersedes_id:
            if self.supersedes_id == self.pk or self.supersedes.scope_id != self.scope_id:
                raise ValidationError("Source revisions must reference another source in the same scope.")
            if self.revision != self.supersedes.revision + 1:
                raise ValidationError("Source revision must increment the previous revision.")
        elif self.revision != 1:
            raise ValidationError("The first source revision is 1.")
        if not self.original_method and not self.limitations.strip():
            raise ValidationError("When the original method is unknown, describe that limitation.")

    def check_history(self, previous):
        self.unchanged(previous)

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.recorded_at = timezone.now()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Source provenance is retained; create a revision instead.")
