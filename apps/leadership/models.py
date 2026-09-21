"""Fiscal-year F04 appointment segments and target-specific eligibility.

An AnnualTarget is the dated appointment segment for one fiscal year. Master
labels may change; a ready target and its historical snapshot never do.
"""
from datetime import date
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, Q
from apps.rounds.models import DomainRecord
from apps.accounts.models import AccessScope

ROLES = [('DE', 'คณบดี / Dean'), ('VD', 'รองคณบดี / Vice dean'),
         ('AS', 'ผู้ช่วยคณบดี / Assistant dean'), ('PC', 'ประธานหลักสูตร / Programme chair')]


def fiscal_window(year):
    if not isinstance(year, int) or not 2565 <= year <= 3000:
        raise ValidationError('ระบุปีงบประมาณ พ.ศ. ตั้งแต่ 2565 / Invalid fiscal year.')
    return date(year-544, 10, 1), date(year-543, 10, 1)


class RegisterRecord(DomainRecord):
    scope = models.ForeignKey('accounts.AccessScope', on_delete=models.PROTECT)

    class Meta:
        abstract = True

    def lock_dependencies(self):
        self.scope = AccessScope.objects.select_for_update().get(pk=self.scope_id)
        for field in self._meta.concrete_fields:
            if field.is_relation and field.name not in {'scope','organization'}:
                self._state.fields_cache.pop(field.name, None)

    def delete(self, *args, **kwargs):
        raise ValidationError('เก็บประวัติทะเบียนไว้ / Registry history is retained.')

    def check_history(self, previous):
        if self.scope_id != previous.scope_id or (hasattr(self, 'code') and self.code != previous.code):
            raise ValidationError('รหัสและหน่วยงานเปลี่ยนไม่ได้ / Stable code and scope are immutable.')


class Person(RegisterRecord):
    code = models.CharField(max_length=80)
    name_th = models.CharField(max_length=240)
    name_en = models.CharField(max_length=240)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['scope', 'code'], name='f04_person_scope_code')]

    def clean(self):
        super().clean()
        if self.user_id:
            from apps.accounts.models import Membership
            if not Membership.objects.filter(user_id=self.user_id, organization_id=self.scope.organization_id).exists():
                raise ValidationError('บัญชีต้องเป็นสมาชิกในหน่วยงาน / Account must belong to this organization.')

    def __str__(self):
        return f'{self.code} · {self.name_th}'


class Programme(RegisterRecord):
    code = models.CharField(max_length=80)
    name_th = models.CharField(max_length=300)
    name_en = models.CharField(max_length=300)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['scope', 'code'], name='f04_programme_scope_code')]

    def __str__(self):
        return f'{self.code} · {self.name_th}'


class Position(RegisterRecord):
    code = models.CharField(max_length=80)
    role = models.CharField(max_length=2, choices=ROLES)
    title_th = models.CharField(max_length=300)
    title_en = models.CharField(max_length=300)
    programme = models.ForeignKey(Programme, null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['scope', 'code'], name='f04_position_scope_code'),
            models.CheckConstraint(condition=Q(role='PC', programme__isnull=False) | Q(role__in=['DE','VD','AS'], programme__isnull=True), name='f04_position_role_programme'),
        ]

    def clean(self):
        super().clean()
        if (self.role == 'PC') != bool(self.programme_id):
            raise ValidationError('ประธานหลักสูตรต้องระบุหนึ่งหลักสูตร / One programme is required for PC only.')
        if self.programme_id and self.programme.scope_id != self.scope_id:
            raise ValidationError('หลักสูตรต่างหน่วยงาน / Programme scope mismatch.')

    def check_history(self, previous):
        super().check_history(previous)
        if (self.role, self.programme_id) != (previous.role, previous.programme_id) and self.targets.exists():
            raise ValidationError('ประเภท/หลักสูตรที่ใช้แล้วเปลี่ยนไม่ได้ ให้สร้างตำแหน่งใหม่ / Create a new position for a changed role or programme.')

    def __str__(self):
        return f'{self.code} · {self.title_th}'


class AnnualPlan(RegisterRecord):
    fiscal_year = models.PositiveIntegerField()
    period = models.ForeignKey('rounds.ReportingPeriod', on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['scope', 'fiscal_year'], name='f04_plan_scope_year')]

    def clean(self):
        super().clean()
        start, end = fiscal_window(self.fiscal_year)
        p = self.period
        if (p.calendar.scope_id != self.scope_id or p.calendar.calendar_type != 'fiscal' or not p.approved
                or p.parent_id or p.reporting_year_be != self.fiscal_year or (p.start_date, p.end_date) != (start, end)):
            raise ValidationError('ใช้ช่วงปีงบประมาณที่รับรอง 1 ต.ค. ถึง 30 ก.ย. / Use the approved full fiscal year.')

    def check_history(self, previous):
        self.unchanged(previous)

    def __str__(self):
        return f'F04 · ปีงบประมาณ {self.fiscal_year}'


class AnnualTarget(RegisterRecord):
    plan = models.ForeignKey(AnnualPlan, on_delete=models.PROTECT, related_name='targets')
    person = models.ForeignKey(Person, on_delete=models.PROTECT)
    position = models.ForeignKey(Position, on_delete=models.PROTECT, related_name='targets')
    title_th = models.CharField(max_length=300)
    title_en = models.CharField(max_length=300)
    responsibility_th = models.TextField(max_length=2000)
    responsibility_en = models.TextField(max_length=2000)
    start_date = models.DateField()
    end_date = models.DateField(help_text='Exclusive end of the assessed appointment segment')
    appointment_kind = models.CharField(max_length=12, choices=[('substantive','ดำรงตำแหน่ง / Substantive'),('acting','รักษาการ / Acting')], default='substantive')
    source_reference = models.CharField(max_length=1000)
    eligibility_basis = models.TextField(max_length=2000)
    status = models.CharField(max_length=12, default='draft', choices=[('draft','ร่าง / Draft'),('ready','ตรึงแล้ว / Ready'),('superseded','แทนที่แล้ว / Superseded'),('exempt','ยกเว้น / Exempt')])
    status_reason = models.TextField(blank=True, max_length=2000)
    snapshot = models.JSONField(default=dict, blank=True)
    frozen_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    frozen_at = models.DateTimeField(null=True, blank=True)
    supersedes = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='successors')

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(end_date__gt=F('start_date')), name='f04_target_dates'),
            models.CheckConstraint(condition=Q(status__in=['draft','ready','superseded','exempt']), name='f04_target_status'),
        ]

    def clean(self):
        super().clean()
        if any(obj.scope_id != self.scope_id for obj in [self.plan, self.person, self.position]):
            raise ValidationError('ข้อมูลผู้ถูกประเมินต่างหน่วยงาน / Target scope mismatch.')
        start, end = fiscal_window(self.plan.fiscal_year)
        if not self.start_date or not self.end_date or not start <= self.start_date < self.end_date <= end:
            raise ValidationError('ช่วงผลงานต้องอยู่ภายในปีงบประมาณ / Assessment segment must be within the fiscal year.')
        if self.status in {'draft','ready'}:
            overlaps = type(self).objects.filter(plan_id=self.plan_id, position_id=self.position_id,
                status__in=['draft','ready'], start_date__lt=self.end_date, end_date__gt=self.start_date).exclude(pk=self.pk)
            if overlaps.exists():
                raise ValidationError('ช่วงเวลาของตำแหน่งนี้ซ้ำกับรายการเดิม ให้แก้หรือแบ่งช่วงเดิมก่อน / This position has an overlapping segment.')
        if self.supersedes_id and (self.supersedes_id == self.pk or self.supersedes.plan_id != self.plan_id or self.supersedes.status != 'superseded'):
            raise ValidationError('รายการทดแทนต้องอ้างอิงรายการที่แทนที่แล้วในปีเดียวกัน / Invalid replacement target.')
        if self.status in {'superseded','exempt'} and not self.status_reason.strip():
            raise ValidationError('ระบุเหตุผล / A reason is required.')
        if self._state.adding and self.status != 'draft':
            raise ValidationError('สร้างรายการร่างก่อน / Create a draft target first.')

    def check_history(self, previous):
        super().check_history(previous)
        if self.plan_id != previous.plan_id:
            raise ValidationError('ย้ายรายการข้ามปีไม่ได้ / Target year is immutable.')
        if previous.status in {'superseded','exempt'}:
            self.unchanged(previous)
        elif previous.status == 'ready':
            self.unchanged(previous, exceptions=('status','status_reason'))
        if self.status != previous.status and not getattr(self, '_allow_transition', False):
            raise ValidationError('ใช้ขั้นตอนตรึงหรือแทนที่รายการ / Use the target lifecycle service.')
        if previous.status == 'draft' and self.status == 'draft' and (self.snapshot or self.frozen_by_id or self.frozen_at):
            raise ValidationError('รายการร่างยังไม่มีสำเนาตรึง / A draft cannot claim a frozen snapshot.')

    @property
    def last_date(self):
        from datetime import timedelta
        return self.end_date - timedelta(days=1)

    def __str__(self):
        return f'{self.person.name_th} · {self.title_th} · {self.start_date} - {self.last_date}'


class Eligibility(RegisterRecord):
    target = models.ForeignKey(AnnualTarget, on_delete=models.PROTECT, related_name='eligibility')
    person = models.ForeignKey(Person, on_delete=models.PROTECT)
    group_code = models.CharField(max_length=3, choices=[('ST1','ST1 สายวิชาการ / Academic'),('ST2','ST2 สายสนับสนุน / Support')])
    relationship = models.CharField(max_length=500)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['target','person'], name='f04_eligible_target_person'),
            models.CheckConstraint(condition=Q(group_code__in=['ST1','ST2']), name='f04_eligible_group'),
        ]

    def clean(self):
        super().clean()
        if self.target.scope_id != self.scope_id or self.person.scope_id != self.scope_id:
            raise ValidationError('ผู้มีสิทธิ์ต่างหน่วยงาน / Eligibility scope mismatch.')
        if self.target.status != 'draft':
            raise ValidationError('รายชื่อผู้เกี่ยวข้องถูกตรึงแล้ว / Related-person roster is frozen.')

    def check_history(self, previous):
        super().check_history(previous)
        if (self.target_id, self.person_id) != (previous.target_id, previous.person_id):
            raise ValidationError('เปลี่ยนตัวตนรายการสิทธิ์ไม่ได้ / Stable eligibility identity.')

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            self.lock_dependencies()
            self.target = AnnualTarget.objects.get(pk=self.target_id)
            if self.target.status != 'draft':
                raise ValidationError('รายชื่อผู้เกี่ยวข้องถูกตรึงแล้ว / Roster is frozen.')
            return models.Model.delete(self, *args, **kwargs)
