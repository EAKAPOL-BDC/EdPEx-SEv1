import uuid
from datetime import timedelta
from django.core.exceptions import ValidationError
from apps.catalog.group_registry import group_label
from django.db import transaction
from apps.accounts.permissions import require_permission
from .models import Calendar, ReportingPeriod, CollectionRound, RoundInstrument, PopulationSnapshot, PopulationMember, RespondentGroup, DataSource
from .services import create_record, update_record, delete_draft, approve_period


@transaction.atomic
def create_period(actor, scope, data):
    require_permission(actor, 'calendar.manage', scope)
    calendar = create_record(actor, Calendar, scope=scope, code='WEB-'+uuid.uuid4().hex,
        label=data['code'], calendar_type=data['calendar_type'], timezone=scope.organization.timezone)
    period = create_record(actor, ReportingPeriod, calendar=calendar, code=data['code'],
        reporting_year_be=data['reporting_year_be'], start_date=data['start_date'], end_date=data['last_date']+timedelta(days=1))
    return approve_period(actor, period, reason=data['reason'])


@transaction.atomic
def save_round(actor, scope, data, round_id=None, instrument_code="F06"):
    if round_id is None:raise ValidationError('สร้างรอบจากเมนูเก็บข้อมูลไม่ระบุตัวตน / Create a round from anonymous collection.')
    if instrument_code not in {"F05","F06"}: raise ValidationError("Unsupported instrument")
    require_permission(actor, 'round.manage', scope)
    values = {k: data[k] for k in ('code', 'owner', 'open_at', 'due_at', 'close_at', 'privacy_notice')}
    if round_id:
        r = CollectionRound.objects.select_for_update().get(pk=round_id, scope=scope)
        if r.status != 'draft':
            raise ValidationError('แก้ไขได้เฉพาะรอบร่าง / Only draft rounds may be edited.')
        return update_record(actor, r, reason=data['reason'], schedule_confirmed=True, **values)
    bundle = data['bundle'].__class__.objects.select_related('instrument_version__instrument').get(pk=data['bundle'].pk)
    if bundle.status != 'published' or bundle.instrument_version.status != 'published' or bundle.instrument_version.instrument.scope_id != scope.pk or bundle.instrument_version.instrument.code != instrument_code:
        raise ValidationError('Select a published '+instrument_code+' in this scope.')
    r = create_record(actor, CollectionRound, scope=scope, period=data['period'], **values)
    create_record(actor, RoundInstrument, collection_round=r, instrument_version=bundle.instrument_version, translation_bundle=bundle, context=instrument_code)
    return r


@transaction.atomic
def save_population(actor, r, data):
    # Snapshot -> round follows the existing population domain locking order.
    snapshot = r.population_snapshots.select_for_update().order_by('-version').first()
    r = CollectionRound.objects.select_for_update().get(pk=r.pk)
    require_permission(actor, 'population.manage', r.scope)
    require_permission(actor, 'source.manage', r.scope)
    if r.status != 'draft' or (snapshot and snapshot.status != 'draft'):
        raise ValidationError('รายชื่อถูกตรึงแล้วหรือรอบไม่ใช่ร่าง / The population or round is locked.')
    profile = survey_profile(r)
    codes = group_codes(r)
    for code, label in [(c,group_label(c, language='th')) for c in codes]:
        if not RespondentGroup.objects.filter(scope=r.scope, code=code).exists():
            create_record(actor, RespondentGroup, scope=r.scope, code=code, label=label)
    values = {'definition': data['definition'], 'counting_unit': profile.counting_unit if profile else 'person',
              'counts_by_group': {profile.group_code:data['count']} if profile else {'ST1': data['st1'], 'ST2': data['st2']}, 'captured_at': data['captured_at']}
    source = snapshot.source if snapshot else None
    if not source or (source.title, source.location) != (data['source_title'], data['source_location']):
        source = create_record(actor, DataSource, scope=r.scope, title=data['source_title'], location=data['source_location'],
            source_type='raw', original_method='Staff eligibility roster specified by the round operator')
    values['source'] = source
    if snapshot:
        return update_record(actor, snapshot, reason=data['reason'], **values)
    return create_record(actor, PopulationSnapshot, collection_round=r, **values)


@transaction.atomic
def save_member(actor, r, data, member_id=None):
    member = PopulationMember.objects.select_for_update().get(pk=member_id, snapshot__collection_round=r) if member_id else None
    snapshot = r.population_snapshots.select_for_update().order_by('-version').first()
    require_permission(actor, 'population.manage', r.scope)
    if not snapshot or snapshot.status != 'draft':
        raise ValidationError('สร้างประชากรฉบับร่างก่อน / Create a draft population first.')
    if data['group'].code not in group_codes(r) or data['group'].scope_id != r.scope_id:
        raise ValidationError('กลุ่มผู้ตอบไม่ถูกต้อง / Invalid staff group.')
    if snapshot.members.filter(eligible_unit_key=data['eligible_unit_key']).exclude(pk=member_id).exists():
        raise ValidationError('รหัสบุคลากรนี้อยู่ในรายชื่อแล้ว / Staff ID already exists in this roster.')
    values = {k: data[k] for k in ('eligible_unit_key', 'group')}
    if member:
        return update_record(actor, member, reason=data['reason'], **values)
    return create_record(actor, PopulationMember, snapshot=snapshot, **values)


@transaction.atomic
def remove_empty_draft_round(actor, r, reason):
    r = CollectionRound.objects.select_for_update().get(pk=r.pk)
    require_permission(actor, 'round.manage', r.scope)
    if r.status != 'draft' or r.population_snapshots.exists() or r.responsibilities.exists():
        raise ValidationError('ลบได้เฉพาะรอบร่างที่ยังไม่มีประชากรหรือประวัติงาน / Only an unused draft round can be deleted.')
    from apps.surveys.models import SurveyProfile
    SurveyProfile.objects.filter(binding__collection_round=r).delete()
    for binding in r.round_instruments.all():
        delete_draft(actor, binding, reason=reason)
    delete_draft(actor, r, reason=reason)


def survey_profile(r):
    from apps.surveys.models import SurveyProfile
    return SurveyProfile.objects.filter(binding__collection_round=r).first()


def group_codes(r):
    profile = survey_profile(r)
    return {profile.group_code} if profile else {'ST1','ST2'}
