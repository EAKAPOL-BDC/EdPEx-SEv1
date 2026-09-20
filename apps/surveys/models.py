"""Eligibility and response stores deliberately have no shared person identifier."""
import uuid
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone


class SurveyProfile(models.Model):
    binding = models.OneToOneField('rounds.RoundInstrument', primary_key=True, on_delete=models.CASCADE, related_name='survey_profile')
    group_code = models.CharField(max_length=80)
    counting_unit = models.CharField(max_length=40, default='person')
    context_th = models.CharField(max_length=1200)
    context_en = models.CharField(max_length=1200)
    intake_method = models.CharField(max_length=16, default='invitation', choices=[('invitation', 'Invitation'), ('public', 'Public')])
    annual_target = models.ForeignKey('leadership.AnnualTarget', null=True, blank=True, on_delete=models.PROTECT, related_name='survey_profiles')
    assessor_role = models.CharField(max_length=2, blank=True)
    # Explicit allowed year/study-stage choices, never the entire mixed list.
    study_options = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['annual_target','group_code','intake_method'], name='f04_target_group_intake')]

    def clean(self):
        v = self.binding.instrument_version
        code = v.instrument.code
        if self.annual_target_id:
            from apps.leadership.services import target_context
            t = self.annual_target
            if (code != 'F04' or t.scope_id != self.binding.collection_round.scope_id
                    or t.plan.period_id != self.binding.collection_round.period_id or not t.snapshot
                    or self.assessor_role != t.snapshot['role'] or self.binding.context != 'f04-target-'+str(t.pk)
                    or self.context_th != target_context(t.snapshot,'th') or self.context_en != target_context(t.snapshot,'en')):
                raise ValidationError('บริบทไม่ตรงทะเบียนผู้ถูกประเมิน / F04 target context mismatch.')
            if self._state.adding and t.status != 'ready':
                raise ValidationError('ตรึงผู้ถูกประเมินก่อน / Freeze the target first.')
        elif self._state.adding and code == 'F04' and self.assessor_role != 'BO':
            raise ValidationError('สร้าง F04 จากทะเบียนผู้ถูกประเมินรายปี / Create F04 from the annual target register.')
        if v.assessment_method != ('self_report' if code in {'F05','F06'} else 'survey'):
            raise ValidationError('Anonymous intake requires the survey method.')
        if code not in {'F01', 'F02', 'F03', 'F04', 'F05', 'F06'} or self.group_code not in v.group_codes:
            raise ValidationError('กลุ่มไม่ตรงกับแบบสำรวจ / Group does not belong to this survey.')
        if self.counting_unit not in {'person', 'organization_representative', 'community_representative'}:
            raise ValidationError('Invalid counting unit.')
        if code != 'F02' and self.counting_unit != 'person':
            raise ValidationError('This form counts people.')
        if (code == 'F04' and self.assessor_role not in {'DE','BO','VD','AS','PC'}) or (code != 'F04' and self.assessor_role):
            raise ValidationError('เลือกตำแหน่งผู้บริหารสำหรับ F04 / Select the fixed F04 leadership role.')
        allowed = {f'option_{n}' for n in (range(1,6) if self.group_code == 'C1' else range(1,9))}
        needs_year = code == 'F01' and self.group_code != 'C3.1'
        if not isinstance(self.study_options, list) or any(not isinstance(x,str) for x in self.study_options):
            raise ValidationError('Invalid study choices.')
        if needs_year and (not self.study_options or not set(self.study_options) <= allowed):
            raise ValidationError('กำหนดชั้นปี/ช่วงศึกษาที่ตรงกับหลักสูตร / Select study stages appropriate to this group.')
        if needs_year and set(self.study_options) & {f'option_{n}' for n in range(1,6)} and set(self.study_options) & {f'option_{n}' for n in range(6,9)}:
            raise ValidationError('เลือกชุดชั้นปีหรือชุดช่วงศึกษาให้ตรงหลักสูตร / Choose either year levels or study stages for this program.')
        if not needs_year and self.study_options:
            raise ValidationError('Study choices apply to F01 degree students only.')
        if not self.context_th.strip() or not self.context_en.strip():
            raise ValidationError('ระบุบริบททั้งสองภาษา / Both context languages are required.')

    def save(self, *args, **kwargs):
        if self.binding.collection_round.status != 'draft' or Invitation.objects.filter(binding_id=self.binding_id).exists():
            raise ValidationError('บริบทถูกตรึงแล้ว / Survey context is frozen.')
        self.full_clean()
        return super().save(*args, **kwargs)


class Invitation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    binding = models.ForeignKey('rounds.RoundInstrument', on_delete=models.PROTECT, related_name='survey_invitations')
    member = models.ForeignKey('rounds.PopulationMember', on_delete=models.PROTECT)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    spent = models.BooleanField(default=False)
    revoked = models.BooleanField(default=False)
    # No response FK or spent timestamp; avoid an operator timeline of submissions.
    class Meta:
        constraints = [models.UniqueConstraint(fields=['binding','member'], name='survey_one_invitation_per_unit')]
        default_permissions = ()


class AnonymousSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invitation = models.OneToOneField(Invitation, on_delete=models.CASCADE)
    secret_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    revision = models.PositiveIntegerField(default=0)
    draft = models.JSONField(default=dict)
    # Transient only, removed at submission, revocation or expiry. No persistent browser draft.
    class Meta:
        default_permissions = ()


class AnonymousResponse(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    binding = models.ForeignKey('rounds.RoundInstrument', on_delete=models.PROTECT, related_name='survey_responses')
    group_code = models.CharField(max_length=80)
    answers = models.JSONField()
    completion = models.CharField(max_length=24, choices=[('complete','complete'),('partial','partial'),('unable_to_assess','unable_to_assess')])
    submitted_at = models.DateTimeField(default=timezone.now)
    # NO user, member, invitation, session, token, IP or contact columns.
    class Meta:
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=models.Q(completion__in=['complete','partial','unable_to_assess']), name='survey_completion_status')]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Submitted responses are immutable.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Submitted responses are retained.')


class AccessThrottle(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    window_start = models.DateTimeField(default=timezone.now)
    attempts = models.PositiveIntegerField(default=0)
    class Meta:
        default_permissions = ()
