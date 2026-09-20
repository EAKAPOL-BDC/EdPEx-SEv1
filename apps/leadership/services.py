"""Scoped, audited register workflow. No respondent identity enters results."""
from datetime import timedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from apps.accounts.permissions import require_permission
from apps.accounts.models import AccessScope
from apps.auditlog.services import record_event
from apps.rounds.models import CollectionRound, RoundInstrument, PopulationMember
from apps.rounds.services import create_record, freeze_population, transition_round
from apps.rounds.web_services import create_period, save_population, save_member
from .models import Person, Programme, Position, AnnualPlan, AnnualTarget, Eligibility, fiscal_window

EDIT_FIELDS = {
    Person: {'code','name_th','name_en','user'}, Programme: {'code','name_th','name_en'},
    Position: {'code','role','title_th','title_en','programme'},
    AnnualTarget: {'plan','person','position','title_th','title_en','responsibility_th','responsibility_en',
                   'start_date','end_date','appointment_kind','source_reference','eligibility_basis'},
    Eligibility: {'target','person','group_code','relationship'},
}


def authorize(actor, scope, roster=False):
    require_permission(actor, 'round.manage', scope)
    if roster:
        require_permission(actor, 'population.manage', scope)


def audit(actor, record, action, reason=''):
    record_event(record.scope.organization, actor, 'leadership.'+action, record._meta.label_lower,
                 str(record.pk), reason=reason, metadata={'scope_id':str(record.scope_id)})


@transaction.atomic
def save_record(actor, scope, model, data, pk=None, reason=''):
    authorize(actor, scope, roster=model in {Person, Eligibility})
    AccessScope.objects.select_for_update().get(pk=scope.pk)
    if model not in EDIT_FIELDS or set(data)-EDIT_FIELDS[model]:
        raise ValidationError('Unsupported register fields.')
    if pk and not reason.strip():
        raise ValidationError('ระบุเหตุผลแก้ไข / Record a change reason.')
    record = model.objects.get(pk=pk, scope=scope) if pk else model(scope=scope)
    for field, value in data.items():
        if hasattr(value, 'pk'):
            setattr(record, field+'_id', value.pk)
        else:
            setattr(record, field, value)
    record.save()
    audit(actor, record, 'updated' if pk else 'created', reason)
    return record


@transaction.atomic
def create_plan(actor, scope, year):
    authorize(actor, scope)
    AccessScope.objects.select_for_update().get(pk=scope.pk)
    previous = AnnualPlan.objects.filter(scope=scope, fiscal_year=year).first()
    if previous:
        return previous
    start, end = fiscal_window(year)
    from apps.rounds.models import ReportingPeriod
    period = ReportingPeriod.objects.filter(calendar__scope=scope, calendar__calendar_type='fiscal', approved=True,
        reporting_year_be=year, parent__isnull=True, start_date=start, end_date=end).first()
    if period is None:
        period = create_period(actor, scope, {'code':f'ปีงบประมาณ {year}', 'calendar_type':'fiscal',
            'reporting_year_be':year,'start_date':start,'last_date':end-timedelta(days=1),
            'reason':'F04 fiscal-year register: October through September, confirmed by operator.'})
    plan = AnnualPlan(scope=scope, fiscal_year=year, period=period)
    plan.save(); audit(actor, plan, 'plan_created')
    return plan


def snapshot_for(target):
    p, pos = target.person, target.position
    programme = pos.programme
    return {'target_id':str(target.pk), 'fiscal_year':target.plan.fiscal_year,
        'person_id':str(p.pk),'person_code':p.code,'person_th':p.name_th,'person_en':p.name_en,
        'evaluatee_user_id':str(p.user_id) if p.user_id else '',
        'position_id':str(pos.pk),'position_code':pos.code,'role':pos.role,
        'title_th':target.title_th,'title_en':target.title_en,
        'programme_id':str(programme.pk) if programme else '',
        'programme_code':programme.code if programme else '',
        'programme_th':programme.name_th if programme else '', 'programme_en':programme.name_en if programme else '',
        'start_date':target.start_date.isoformat(),'last_date':target.last_date.isoformat(),
        'appointment_kind':target.appointment_kind,
        'responsibility_th':target.responsibility_th,'responsibility_en':target.responsibility_en}


@transaction.atomic
def freeze_target(actor, scope, pk, reason, *, public_all_staff=False):
    authorize(actor, scope, roster=True)
    AccessScope.objects.select_for_update().get(pk=scope.pk)
    target = AnnualTarget.objects.select_for_update().get(pk=pk, scope=scope)
    if target.status != 'draft' or not reason.strip() or (not public_all_staff and not target.eligibility.exists()):
        raise ValidationError('ต้องเป็นร่าง มีรายชื่อผู้เกี่ยวข้อง และเหตุผลยืนยัน / Review a draft with an explicit related-person roster.')
    target.full_clean()
    if public_all_staff:
        from apps.participation.public_admission import enabled
        enabled()
        if target.eligibility.exists():
            raise ValidationError('ทางเข้าสาธารณะไม่ใช้ทะเบียนผู้ตอบ ตรวจและลบรายชื่อในรายการร่างก่อน / Public entry does not use a respondent roster; review and remove draft eligibility entries first.')
    for item in target.eligibility.select_related('person','target','scope'):
        item.full_clean()
    target.snapshot = snapshot_for(target)
    if public_all_staff:
        target.snapshot['respondent_policy'] = 'all_staff_public'
    target.frozen_by, target.frozen_at = actor, timezone.now()
    target.status = 'ready'; target._allow_transition = True
    target.save(); audit(actor, target, 'target_frozen', reason)
    return target


def target_context(snapshot, locale):
    programme = (' · '+snapshot['programme_'+locale]) if snapshot['programme_id'] else ''
    return f"{snapshot['person_'+locale]} · {snapshot['title_'+locale]}{programme} · {snapshot['start_date']} - {snapshot['last_date']}"


def validate_binding(binding, snapshot=None, *, accepting=False):
    from apps.surveys.models import SurveyProfile
    profile = SurveyProfile.objects.filter(binding_id=binding.pk).select_related('annual_target').first()
    if not profile or not profile.annual_target_id:
        return None
    t = profile.annual_target
    if (t.scope_id != binding.collection_round.scope_id or t.plan.period_id != binding.collection_round.period_id
            or not t.snapshot or profile.assessor_role != t.snapshot['role']
            or binding.instrument_version.instrument.code != 'F04'
            or binding.context != 'f04-target-'+str(t.pk)):
        raise ValidationError('บริบทไม่ตรงทะเบียน F04 / F04 target context mismatch.')
    if accepting and t.status != 'ready':
        raise ValidationError('รายการนี้ถูกแทนที่หรือยกเว้นแล้ว / Target is no longer accepting responses.')
    if profile.context_th != target_context(t.snapshot,'th') or profile.context_en != target_context(t.snapshot,'en'):
        raise ValidationError('ชื่อผู้ถูกประเมินต้องตรงสำเนาที่ตรึง / Target labels must match the frozen snapshot.')
    if snapshot is not None:
        from apps.participation.models import PublicCollection
        if PublicCollection.objects.filter(binding=binding).exists():
            from apps.participation.public_admission import validate_population
            validate_population(binding, snapshot)
            return t
        expected = set(t.eligibility.filter(group_code=profile.group_code).values_list('person__code', flat=True))
        actual = set(snapshot.members.filter(group__code=profile.group_code).values_list('eligible_unit_key', flat=True))
        if not expected or expected != actual or snapshot.members.count()!=len(expected):
            raise ValidationError('รายชื่อไม่ตรงผู้เกี่ยวข้องที่ตรึงไว้ / Roster differs from the approved related-person list.')
    return t


@transaction.atomic
def generate_collections(actor, scope, target_ids, data, *, data_kind='real'):
    for permission in ('round.manage','population.manage','source.manage'):
        require_permission(actor, permission, scope)
    AccessScope.objects.select_for_update().get(pk=scope.pk)
    targets = list(AnnualTarget.objects.select_for_update().filter(pk__in=target_ids,scope=scope).order_by('pk'))
    if len(targets)!=len(set(map(str,target_ids))) or not targets:
        raise ValidationError('เลือกผู้ถูกประเมินในหน่วยงานนี้ / Select targets in this scope.')
    from apps.catalog.models import TranslationBundle
    from apps.surveys.models import SurveyProfile
    from apps.surveys.validation import validate_schema
    bundle = TranslationBundle.objects.select_related('instrument_version__instrument').get(pk=data['bundle'].pk)
    if bundle.status!='published' or bundle.instrument_version.status!='published' or bundle.instrument_version.instrument.code!='F04' or bundle.instrument_version.instrument.scope_id!=scope.pk:
        raise ValidationError('เลือก F04 และคำแปลที่เผยแพร่แล้ว / Select published F04 wording.')
    if bundle.instrument_version.source_metadata.get('synthetic_only') and data_kind!='synthetic':
        raise ValidationError('แบบฟอร์มจำลองใช้เก็บข้อมูลจริงไม่ได้ / Simulation-only form.')
    created=[]
    for target in targets:
        if target.status!='ready':
            raise ValidationError('ตรึงทะเบียนและผู้เกี่ยวข้องก่อนสร้างรอบ / Freeze each target and roster first.')
        if target.snapshot.get('respondent_policy') == 'all_staff_public':
            raise ValidationError('ใช้การสร้างรอบสาธารณะครบ ST1 และ ST2 สำหรับรายการนี้ / Use the two-group public collection workflow for this target.')
        for group in target.eligibility.values_list('group_code',flat=True).distinct().order_by('group_code'):
            old=SurveyProfile.objects.filter(annual_target=target,group_code=group,intake_method='invitation').first()
            if old:
                created.append(old.binding); continue
            values={k:data[k] for k in ('owner','open_at','due_at','close_at','privacy_notice')}
            r=create_record(actor,CollectionRound,scope=scope,period=target.plan.period,data_kind=data_kind,
                code=f'F04-{target.plan.fiscal_year}-{target.position.code[:25]}-{str(target.pk)[:8]}-{group}',**values)
            binding=create_record(actor,RoundInstrument,collection_round=r,instrument_version=bundle.instrument_version,
                translation_bundle=bundle,context='f04-target-'+str(target.pk))
            profile=SurveyProfile(binding=binding,annual_target=target,group_code=group,counting_unit='person',
                context_th=target_context(target.snapshot,'th'),context_en=target_context(target.snapshot,'en'),assessor_role=target.snapshot['role'])
            profile.save(); validate_schema(profile)
            eligible=list(target.eligibility.filter(group_code=group).select_related('person'))
            pop=save_population(actor,r,{'definition':target.eligibility_basis,'count':len(eligible),'captured_at':target.frozen_at,
                'source_title':f'F04 related-person roster {target.pk}', 'source_location':f'F04 registry target {target.pk}; {target.source_reference}'})
            from apps.rounds.models import RespondentGroup
            group_record=RespondentGroup.objects.get(scope=scope,code=group)
            for item in eligible:
                save_member(actor,r,{'eligible_unit_key':item.person.code,'group':group_record})
            freeze_population(actor,pop)
            binding.collection_round=transition_round(actor,r,'ready')
            created.append(binding)
            audit(actor,target,'collection_created')
    return created


@transaction.atomic
def split_target(actor, scope, pk, change_date, new_person, title_th, title_en, reason):
    """Replace a target by two explicit appointment segments; never move answers."""
    authorize(actor,scope,roster=True)
    AccessScope.objects.select_for_update().get(pk=scope.pk)
    t=AnnualTarget.objects.select_for_update().get(pk=pk,scope=scope)
    if t.status not in {'draft','ready'} or not t.start_date < change_date < t.end_date or not reason.strip():
        raise ValidationError('ระบุวันเปลี่ยนภายในช่วงเดิมและเหตุผล / Enter an internal split date and reason.')
    new_person=Person.objects.get(pk=new_person.pk,scope=scope)
    from apps.surveys.models import SurveyProfile
    for profile in SurveyProfile.objects.filter(annual_target=t).select_related('binding__collection_round'):
        r=profile.binding.collection_round
        if r.status=='open': transition_round(actor,r,'closed',reason=reason)
    t.status='superseded';t.status_reason=reason;t._allow_transition=True;t.save()
    results=[]
    for start,end,person,th,en in [(t.start_date,change_date,t.person,t.title_th,t.title_en),
                                  (change_date,t.end_date,new_person,title_th,title_en)]:
        successor=AnnualTarget(scope=scope,plan=t.plan,person=person,position=t.position,title_th=th,title_en=en,
            responsibility_th=t.responsibility_th,responsibility_en=t.responsibility_en,start_date=start,end_date=end,
            appointment_kind=t.appointment_kind,source_reference=t.source_reference,eligibility_basis=t.eligibility_basis,supersedes=t)
        successor.save()
        for item in t.eligibility.all():
            Eligibility(scope=scope,target=successor,person_id=item.person_id,group_code=item.group_code,relationship=item.relationship).save()
        audit(actor,successor,'split_draft_created',reason); results.append(successor)
    audit(actor,t,'superseded',reason)
    return results


@transaction.atomic
def exempt_target(actor,scope,pk,reason):
    authorize(actor,scope)
    AccessScope.objects.select_for_update().get(pk=scope.pk)
    t=AnnualTarget.objects.get(pk=pk,scope=scope)
    if t.status!='draft' or not reason.strip():
        raise ValidationError('ยกเว้นได้เฉพาะร่างและต้องระบุเหตุผล / Only draft targets can be exempted with a reason.')
    t.status='exempt';t.status_reason=reason;t._allow_transition=True;t.save();audit(actor,t,'exempt',reason)


@transaction.atomic
def remove_eligibility(actor,scope,pk,reason):
    authorize(actor,scope,roster=True)
    row=Eligibility.objects.get(pk=pk,scope=scope)
    if not reason.strip(): raise ValidationError('ระบุเหตุผล / Reason required.')
    audit(actor,row,'eligibility_removed',reason);row.delete()


@transaction.atomic
def copy_previous(actor,scope,plan_id,source_id):
    authorize(actor,scope,roster=True)
    AccessScope.objects.select_for_update().get(pk=scope.pk)
    plan=AnnualPlan.objects.get(pk=plan_id,scope=scope)
    source=AnnualPlan.objects.get(pk=source_id,scope=scope,fiscal_year=plan.fiscal_year-1)
    if plan.targets.exists():raise ValidationError('คัดลอกได้เฉพาะปีที่ยังไม่มีรายการ / Copy into an empty year only.')
    latest={}
    for t in source.targets.filter(status__in=['draft','ready']).order_by('end_date'):
        latest[t.position_id]=t
    for t in latest.values():
        start,end=fiscal_window(plan.fiscal_year)
        new=AnnualTarget(scope=scope,plan=plan,person=t.person,position=t.position,title_th=t.title_th,title_en=t.title_en,
            start_date=start,end_date=end,appointment_kind=t.appointment_kind,source_reference=t.source_reference,
            responsibility_th=t.responsibility_th,responsibility_en=t.responsibility_en,eligibility_basis=t.eligibility_basis)
        new.save()
        for row in t.eligibility.all():
            Eligibility(scope=scope,target=new,person=row.person,group_code=row.group_code,relationship=row.relationship).save()
        audit(actor,new,'copied_as_draft','Previous year copied for explicit date, appointment and eligibility review.')
    return plan
