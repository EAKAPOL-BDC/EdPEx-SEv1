"""Stored F05 sources: append-only revisions and explicit evidence review."""
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from apps.accounts.permissions import require_permission
from apps.rounds.models import RoundInstrument, CollectionRound
from apps.auditlog.services import record_event
from .models import ActivityRecord, ActivityRevision, StoredSourceSelection
from .services import SeriesInput, AttendanceSource, _record_calculation
from .engine import Attendance, CATEGORIES
from .revisions import ResponseContext


def validate_payload(data,r):
    try:
        start=datetime.fromisoformat(data['starts_at']);end=datetime.fromisoformat(data['ends_at'])
        training=Decimal(data['training_hours']);visit=Decimal(data['visit_hours'])
        if not all(v.is_finite() and v >= 0 for v in (training,visit)):raise ValueError()
        if timezone.is_naive(start) or timezone.is_naive(end) or end<=start:raise ValueError()
        if training+visit > Decimal(str((end-start).total_seconds()/3600)):raise ValueError()
        if not set(data['categories']) <= CATEGORIES or not isinstance(data['external_visit'],bool):raise ValueError()
        zone=ZoneInfo(r.scope.organization.timezone)
        if not r.period.start_date <= start.astimezone(zone).date() <= end.astimezone(zone).date() < r.period.end_date:raise ValueError()
        if not data['title'].strip() or len(data['title'])>300:raise ValueError()
        if not isinstance(data['evidence_reference'],str) or len(data['evidence_reference'])>2000:raise ValueError()
    except (KeyError,TypeError,ValueError,ArithmeticError):
        raise ValidationError('ตรวจวันเวลา ชั่วโมง หมวดกิจกรรม และช่วงรายงาน / Check dates, hours, categories and reporting period.')
    return start,end,training,visit


def audit(actor,r,event,revision):
    record_event(r.organization,actor,event,'ActivityRevision',revision.pk,reason=revision.reason,
        metadata={'scope_id':str(r.scope_id),'round_id':str(r.pk),'revision':revision.number,'status':revision.status})


def locked(selected_id,actor,action):
    selected=RoundInstrument.objects.select_related('instrument_version__instrument').get(pk=selected_id)
    r=CollectionRound.objects.select_for_update(of=('self',)).select_related('scope__organization','period','population_snapshot').get(pk=selected.collection_round_id)
    require_permission(actor,action,r.scope)
    if selected.instrument_version.instrument.code!='F05' or not r.population_snapshot_id or r.population_snapshot.status!='frozen' or r.status not in {'open','closed','review','approved'}:
        raise ValidationError('เปิดรอบ F05 และตรึงรายชื่อก่อน / Open an F05 round with a frozen roster first.')
    selected.collection_round=r
    return selected,r


@transaction.atomic
def save_entry(actor,selected_id,member,activity_code,session_code,payload,reason,status='draft',record_id=None,expected_revision=0):
    raise ValidationError('ส่วนนี้เป็นประวัติการเก็บรายบุคคล ให้ใช้เมนูเก็บข้อมูลไม่ระบุตัวตน F01–F06 สำหรับรอบใหม่ / This identified workflow is historical; use anonymous collection.')
    selected,r=locked(selected_id,actor,'source.manage')
    validate_payload(payload,r)
    if status not in {'draft','submitted'} or not reason.strip():raise ValidationError('Invalid entry action or missing reason.')
    if record_id:
        record=ActivityRecord.objects.get(pk=record_id,round_instrument=selected)
        if record.member_id!=member.pk or record.activity_code!=activity_code or record.session_code!=session_code:
            raise ValidationError('รหัสบุคคล กิจกรรม และครั้งเป็นรหัสคงที่ / Entry identity cannot change.')
    else:
        record=ActivityRecord(round_instrument=selected,member=member,activity_code=activity_code,session_code=session_code);record.save()
    latest=record.revisions.order_by('-number').first()
    if (latest.number if latest else 0)!=expected_revision:raise ValidationError('รายการเปลี่ยนแล้ว กรุณาเปิดใหม่ / Entry changed; reload before saving.')
    if latest and latest.status=='submitted':raise ValidationError('รอผลตรวจ หรือให้ผู้ตรวจส่งกลับแก้ไข / Await review or return for correction.')
    revision=ActivityRevision(record=record,number=expected_revision+1,actor=actor,status=status,payload=payload,reason=reason);revision.save()
    audit(actor,r,'activity.'+status,revision)
    return record


@transaction.atomic
def review_entry(actor,record_id,outcome,reason,expected_revision,evidence_confirmed=False,exception_reason=''):
    raise ValidationError('ส่วนนี้เป็นประวัติการเก็บรายบุคคล ให้ใช้เมนูเก็บข้อมูลไม่ระบุตัวตน F01–F06 สำหรับรอบใหม่ / This identified workflow is historical; use anonymous collection.')
    initial=ActivityRecord.objects.get(pk=record_id)
    selected,r=locked(initial.round_instrument_id,actor,'calculation.validate')
    latest=initial.revisions.order_by('-number').first()
    if not latest or latest.number!=expected_revision or latest.status!='submitted':raise ValidationError('รายการไม่อยู่ระหว่างตรวจ หรือข้อมูลเปลี่ยนแล้ว / Entry is not awaiting this review.')
    if outcome not in {'accepted','rejected','revision_requested'} or not reason.strip():raise ValidationError('Choose a review outcome and reason.')
    start,end,training,visit=validate_payload(latest.payload,r)
    if outcome=='accepted':
        if end>timezone.now() or not evidence_confirmed or not latest.payload['evidence_reference'].strip():
            raise ValidationError('ตรวจรับหลังจบกิจกรรม และต้องยืนยันตรวจหลักฐาน / Acceptance requires a completed activity and verified evidence reference.')
        unusual=training+visit>12
        overlap=False
        for record in ActivityRecord.objects.filter(round_instrument=selected,member=initial.member).exclude(pk=initial.pk):
            other=record.revisions.order_by('-number').first()
            if other and other.status=='accepted':
                a,b,_,_=validate_payload(other.payload,r)
                overlap=overlap or start<b and a<end
        if (unusual or overlap) and not exception_reason.strip():
            raise ValidationError('ชั่วโมงเกิน 12 หรือเวลาซ้อน ต้องระบุเหตุผลยืนยัน / Over 12 hours or overlapping attendance requires an explicit review explanation.')
    combined=reason+('\nException: '+exception_reason if exception_reason.strip() else '')
    revision=ActivityRevision(record=initial,number=latest.number+1,actor=actor,status=outcome,payload=latest.payload,reason=combined);revision.save()
    audit(actor,r,'activity.'+outcome,revision)
    return revision


def stored_series(selected,cutoff):
    r=selected.collection_round
    context=ResponseContext(str(r.scope_id),str(r.pk),'F05',selected.instrument_version.version,selected.context)
    by_group={}
    for member in r.population_snapshot.members.select_related('group').all():by_group[member.group_id]=member.group
    sources={pk:[] for pk in by_group}
    for record in selected.activity_records.select_related('member').all():
        revision=record.revisions.filter(created_at__lte=cutoff).order_by('-number').first()
        if not revision:continue
        p=revision.payload
        attendance=Attendance(record.member.eligible_unit_key,record.activity_code,record.session_code,
            Decimal(p['training_hours']),Decimal(p['visit_hours']),frozenset(p['categories']),revision.status,p['external_visit'],revision.status=='accepted')
        sources[record.member.group_id].append(AttendanceSource(str(revision.pk),revision.number,context,revision.created_at,
            datetime.fromisoformat(p['starts_at']).astimezone(ZoneInfo(r.scope.organization.timezone)).date(),attendance))
    return [SeriesInput(selected.pk,b.pk,group.pk,attendance_sources=tuple(sources[group.pk]))
        for b in selected.instrument_version.bindings.all() for group in by_group.values() if group.code in b.group_rules['group_codes']]


@transaction.atomic
def calculate(actor,selected_id,cutoff,idempotency_key,dry_run=False):
    selected,r=locked(selected_id,actor,'calculation.run')
    result=_record_calculation(actor,round_id=r.pk,inputs=stored_series(selected,cutoff),cutoff=cutoff,idempotency_key=idempotency_key,dry_run=dry_run,permissions=('calculation.run',))
    if not dry_run:StoredSourceSelection.objects.get_or_create(run_id=result.run_id,defaults={'round_instrument':selected,'source_kind':'f05_activity_revisions'})
    return asdict(result)
