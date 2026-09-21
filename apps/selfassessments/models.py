"""Immutable assignments and revisions. F06 has no reviewer or evidence field."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.calculations.codec import digest
from apps.calculations.models import HASH, SnapshotRecord


class SelfAssessmentAssignment(SnapshotRecord):
    round_instrument = models.ForeignKey('rounds.RoundInstrument', on_delete=models.PROTECT)
    member = models.ForeignKey('rounds.PopulationMember', on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='self_assessment_assignments')
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    duties = models.TextField()
    expected_levels = models.JSONField()
    applicable_question_ids = models.JSONField()

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=['round_instrument', 'member'], name='self_assignment_member_unique'),
            models.UniqueConstraint(fields=['round_instrument', 'user'], name='self_assignment_owner_unique'),
        ]

    def clean(self):
        super().clean()
        from apps.accounts.permissions import has_active_membership
        from .validation import assignment_questions
        selected = self.round_instrument
        r = selected.collection_round
        v = selected.instrument_version
        if r.status != 'ready' or v.instrument.code != 'F06' or v.assessment_method != 'self_report':
            raise ValidationError('Assign F06 after readiness and before opening collection.')
        if v.evidence_required or v.assessor_scoring or v.status != 'published':
            raise ValidationError('Use a published self-report version without evidence or assessor scoring.')
        if self.member.snapshot_id != r.population_snapshot_id or self.member.group.code not in {'ST1', 'ST2'}:
            raise ValidationError('Use a staff member from the frozen population of this round.')
        if not has_active_membership(self.user, r.scope):
            raise ValidationError('The owner must be an active organization member.')
        if not isinstance(self.duties, str) or not self.duties.strip() or len(self.duties) > 4000:
            raise ValidationError('Record the actual duties, up to 4000 characters.')
        assignment_questions(self, validate_configuration=True)


class SelfAssessmentRevision(SnapshotRecord):
    assignment = models.ForeignKey(SelfAssessmentAssignment, on_delete=models.PROTECT, related_name='revisions')
    revision = models.PositiveIntegerField()
    status = models.CharField(max_length=12, choices=[('draft', 'draft'), ('submitted', 'submitted')])
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)
    answers = models.JSONField(default=dict, blank=True)
    completeness = models.CharField(max_length=12, choices=[('partial', 'partial'), ('complete', 'complete')])
    idempotency_key = models.CharField(max_length=160)
    request_hash = models.CharField(max_length=64, validators=[HASH])

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=['assignment', 'revision'], name='self_revision_number_unique'),
            models.UniqueConstraint(fields=['assignment', 'idempotency_key'], name='self_revision_request_unique'),
            models.CheckConstraint(condition=models.Q(revision__gt=0), name='self_revision_positive'),
            models.CheckConstraint(condition=models.Q(status__in=['draft', 'submitted']), name='self_revision_state'),
        ]

    def clean(self):
        super().clean()
        from .validation import normalize_answers
        r = self.assignment.round_instrument.collection_round
        if not r.accepting_at(self.recorded_at) or timezone.is_naive(self.recorded_at) or self.recorded_at > timezone.now():
            raise ValidationError('The collection window is closed.')
        answers, completeness = normalize_answers(self.assignment, self.answers)
        if self.answers != answers or self.completeness != completeness:
            raise ValidationError('Response does not match the server-validated question schema.')
        expected = digest({'revision': self.revision-1, 'status': self.status, 'answers': self.answers})
        if expected != self.request_hash or not self.idempotency_key.strip():
            raise ValidationError('Revision request checksum mismatch.')
