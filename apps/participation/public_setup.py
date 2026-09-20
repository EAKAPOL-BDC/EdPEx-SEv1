"""Staff-only creation and publication of anonymous public collections."""
import uuid
from datetime import timedelta
from django import forms
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from apps.accounts.permissions import require_permission
from apps.catalog.group_registry import group_label
from apps.rounds.models import CollectionRound, RoundInstrument, RespondentGroup, DataSource, PopulationSnapshot
from apps.rounds.services import create_record, freeze_population, transition_round
from apps.rounds.web import form_page
from apps.surveys.models import SurveyProfile
from apps.surveys.operator import selected_for
from apps.surveys.services import require_manager
from apps.selfassessments.operator_web import page
from . import services, public_admission
from .models import PublicCollection, PublicSession, ReceiptPolicy
from .public_catalog import GROUPS, LEVELS, YEARS, PROGRAMMES, validate_context
from .setup import SetupForm
from . import collection_mode

SALT = 'nexora.public.setup.2026-09-19'


class PublicSetupForm(SetupForm):
    group_code = forms.ChoiceField(label='กลุ่มผู้ตอบ / Respondent group')
    programme_key = forms.ChoiceField(required=False, label='หลักสูตร / Programme')
    counting_unit = forms.ChoiceField(label='หน่วยนับของจำนวนอ้างอิง / Reference counting unit', choices=[
        ('person', 'บุคคล / Person'), ('organization_representative', 'ผู้แทนองค์กร / Organisation representative'),
        ('community_representative', 'ผู้แทนชุมชน / Community representative')],
        help_text='จำนวนอ้างอิงต้องใช้หน่วยเดียวกับผู้ตอบ เช่น F02 ผู้แทนชุมชนให้นับหน่วยชุมชนที่เป็นตัวแทน ไม่รวมกับจำนวนบุคคล / Match the reference count to the response unit; do not mix people, organisations and communities.')

    def __init__(self, *args, source, **kwargs):
        super().__init__(*args, **kwargs)
        self.source = source
        self.fields['counting_unit'].initial = source.survey_profile.counting_unit
        if source.instrument_version.instrument.code != 'F02':
            self.fields['counting_unit'].choices = [('person', 'บุคคล / Person')]
            self.fields['counting_unit'].widget = forms.HiddenInput()
            self.fields['counting_unit'].initial = 'person'
        if source.instrument_version.instrument.code != 'F01':
            self.fields['programme_key'].widget = forms.HiddenInput()
        if source.instrument_version.instrument.code == 'F04':
            for name in ('context_th', 'context_en'):
                self.fields[name].widget = forms.HiddenInput()
                self.fields[name].initial = getattr(source.survey_profile, name)
        if source.instrument_version.instrument.code == 'F04':
            self.fields['context_th'].help_text = 'ใช้ข้อมูลผู้บริหารทุกตำแหน่งจากทะเบียนปีเดียวกับต้นแบบ / Uses every leader and position from the template’s annual register.'
        self.fields['group_code'].choices = [('', '—')] + [(g, GROUPS[g][0]+' / '+GROUPS[g][1])
            for g in source.instrument_version.group_codes if g in GROUPS]
        self.fields['programme_key'].choices = [('', 'ไม่ใช้กับกลุ่มนี้ / Not applicable')] + [
            (level+':'+key, th+' / '+en) for level, rows in PROGRAMMES.items() for key, th, en in rows]
        self.fields['group_code'].help_text = 'เลือกกลุ่มตามบทบาท ระบบไม่ขอรายชื่อ เช่น ST2 บุคลากรสายสนับสนุน / Select the respondent role, e.g. ST2 support staff. No roster is requested.'
        self.fields['programme_key'].help_text = 'ใช้เฉพาะ C1, C2.1 และ C2.2 แยกรอบต่อหลักสูตร ผู้ตอบเลือกชั้นปีเอง / C1, C2.1 and C2.2 only: one programme per collection; respondents select their year.'
        self.fields['code'].label = 'ชื่อรอบสาธารณะใหม่ / New public collection name'
        self.fields['code'].help_text = 'เช่น ประสบการณ์ผู้เรียน สะเต็มศึกษา ปี 2569 / Example: STEM learner experiences 2569.'
        self.fields['count'].label = 'จำนวนผู้มีสิทธิ์ตามแหล่งอ้างอิง / Aggregate reference population'
        self.fields['count'].help_text = 'จำนวนรวมเพื่ออ้างอิงตัวหาร ไม่ใช่จำนวนคนตอบที่ยืนยันตัวตนแล้ว เช่น 120 คน ไม่ต้องแนบรายชื่อ / Reference denominator, e.g. 120 people. This is not an identity-verified respondent count; do not attach a roster.'
        self.fields['confirm'].label = collection_mode.confirm_label()
        # Persistent hints, not placeholder-only explanations. Existing setup
        # guidance supplies field examples; these hints remain without JavaScript.
        hints = {
            'context_th': 'ข้อความที่ผู้ตอบเห็น เช่น ประสบการณ์นิสิตหลักสูตรสะเต็มศึกษา / Describe the shared context in Thai, without respondent names.',
            'context_en': 'เช่น Learning experiences of STEM Education students / English version of the same context.',
            'open_at': 'วันและเวลาแรกที่อนุญาตให้ตอบตามเขตเวลาของหน่วยงาน / Earliest response time in the organisation’s time zone.',
            'due_at': 'วันเป้าหมายให้ตอบเสร็จ ต้องไม่เกินวันปิด / Target completion date; no later than closing.',
            'close_at': 'หลังเวลานี้ระบบไม่รับคำตอบ แม้เปิดหน้าไว้แล้ว / Submissions stop at this time, including already-open forms.',
            'source_title': 'เช่น สรุปจำนวนนิสิตจากงานทะเบียน / Example: Aggregate student count from the registrar.',
            'source_reference': 'เช่น รายงานสรุปเดือนกันยายน 2569 หน้า 2 ระบุที่มาโดยไม่แนบรายชื่อ / Cite the aggregate report and page; no personal roster.',
            'privacy_notice': 'อธิบายวัตถุประสงค์ ผู้ควบคุมข้อมูล ระยะเวลาเก็บ และช่องทางติดต่อจริง ทั้งไทยและอังกฤษ / Include purpose, controller, retention and actual contact details in both languages.',
            'label_th': 'เช่น เข้าร่วมประเมินประสบการณ์บุคลากร F03 ปี 2569 ไม่ใส่ชื่อผู้ตอบ / Shared activity name, without respondent identity.',
            'label_en': 'เช่น F03 Staff Experience Assessment 2569 / English activity name shown on proof.',
            'expires_at': 'วันที่สิ้นสุดการตรวจหลักฐาน ต้องหลังวันปิดรอบ / Last date for proof verification; must follow collection closing.',
            'workload': 'อนุญาตให้ผู้ตรวจที่ได้รับสิทธิ์ใช้สอบทวนภาระงาน ไม่ให้ชั่วโมงอัตโนมัติ / Enable authorised workload verification; no automatic hours.',
            'prize': 'อนุญาตให้ผู้ตรวจสอบทวนสิทธิ์รางวัลหลังปิดรอบ ไม่จับรางวัลอัตโนมัติ / Enable reward verification after closing; no automatic draw.',
        }
        for name, hint in hints.items():
            self.fields[name].help_text = hint
        if source.instrument_version.instrument.code == 'F04':
            from apps.leadership.public_collections import add_staff_fields
            add_staff_fields(self)
        from apps.accounts.templatetags.portal_ui import ui_wording
        from django.utils.translation import get_language
        for field in self.fields.values():
            field.label = ui_wording(field.label, get_language()) if field.label else field.label
            field.help_text = ui_wording(field.help_text, get_language()) if field.help_text else field.help_text

    class Media:
        js = ('participation/public-setup.js',)

    def clean(self):
        data = super().clean()
        if self.source.instrument_version.instrument.code == 'F04':
            from apps.leadership.public_collections import validate_staff_fields
            validate_staff_fields(self, data)
            data['group_code'] = 'ST1'
        group, programme_key = data.get('group_code'), data.get('programme_key', '')
        level, programme = programme_key.split(':', 1) if ':' in programme_key else ('', '')
        try:
            validate_context(group, level, programme, YEARS[level][0] if level in YEARS else '')
        except (ValueError, TypeError):
            self.add_error('programme_key', 'เลือกหลักสูตรให้ตรงกลุ่ม เช่น C2.2 ใช้เฉพาะปริญญาเอก / Choose a programme appropriate to the group; C2.2 is doctoral only.')
        data.update(level=level, programme=programme)
        return data


@transaction.atomic
def create_collection(actor, source, data, *, target_override=None):
    public_admission.enabled()
    r_source = CollectionRound.objects.select_for_update().get(pk=source.collection_round_id)
    require_manager(actor, source)
    require_permission(actor, 'source.manage', r_source.scope)
    if (r_source.data_kind != collection_mode.data_kind() or source.translation_bundle.status != 'published'
            or source.instrument_version.status != 'published'):
        raise ValidationError('ใช้ต้นแบบที่เผยแพร่แล้วและมีชนิดข้อมูลตรงกับสภาพแวดล้อมนี้ / Use a published template matching this environment’s data kind.')
    ticket = signing.loads(data['setup_stamp'], salt=SALT, max_age=3600)
    if ticket.get('actor') != str(actor.pk) or ticket.get('source') != str(source.pk):
        raise signing.BadSignature
    nonce = uuid.UUID(ticket['nonce'])
    activity = 'public-'+(uuid.uuid5(nonce, str(target_override.pk)+':'+data['group_code']).hex if target_override else nonce.hex)
    if ReceiptPolicy.objects.filter(activity_code=activity, binding__collection_round__scope=r_source.scope).exists():
        raise ValidationError('สร้างรอบจากคำขอนี้แล้ว / This request already created a collection.')
    target = (target_override or source.survey_profile.annual_target) if source.instrument_version.instrument.code == 'F04' else None
    return build_public_collection(actor, r_source.scope, r_source.period, source.translation_bundle, data,
                                   target=target, activity=activity)


@transaction.atomic
def build_public_collection(actor, scope, period, bundle, data, *, target=None, activity):
    # Internal builder; callers validate and lock the batch.
    kind, realm = collection_mode.creation_contract()
    group = data['group_code']
    validate_context(group, data['level'], data['programme'], YEARS[data['level']][0] if data['level'] in YEARS else '')
    code = bundle.instrument_version.instrument.code
    values = {k: data[k] for k in ('code', 'open_at', 'due_at', 'close_at', 'privacy_notice')}
    r = create_record(actor, CollectionRound, scope=scope, period=period, owner=actor,
                      data_kind=kind, schedule_confirmed=True, **values)
    context = 'f04-target-'+str(target.pk) if target else 'public-'+uuid.uuid4().hex
    b = create_record(actor, RoundInstrument, collection_round=r, instrument_version=bundle.instrument_version,
                      translation_bundle=bundle, context=context)
    profile = SurveyProfile(binding=b, intake_method='public', group_code=group,
        counting_unit=data.get('counting_unit', 'person'), context_th=data['context_th'], context_en=data['context_en'],
        annual_target=target, assessor_role=target.snapshot['role'] if target else '',
        study_options=['option_1'] if code == 'F01' and group in LEVELS else [])
    if target:
        from apps.leadership.services import target_context
        profile.context_th, profile.context_en = (target_context(target.snapshot, lang) for lang in ('th', 'en'))
    profile.save()
    public_admission.configure(actor, b.pk, level=data['level'], programme=data['programme'])
    if not RespondentGroup.objects.filter(scope=r.scope, code=group).exists():
        create_record(actor, RespondentGroup, scope=r.scope, code=group, label=group_label(group, language='th'))
    source_record = create_record(actor, DataSource, scope=r.scope, title=data['source_title'], location=data['source_reference'],
        source_type='aggregate', original_method='Public self-selected participation; aggregate reference only, no respondent roster')
    population = create_record(actor, PopulationSnapshot, collection_round=r, definition='Reference population; submissions are not verified unique persons',
        counting_unit=profile.counting_unit, counts_by_group={group: data['count']}, captured_at=timezone.now(), source=source_record)
    freeze_population(actor, population)
    services.configure_policy(actor, b.pk, activity_code=activity, label_th=data['label_th'], label_en=data['label_en'],
        expires_at=data['expires_at'], workload=data['workload'], prize=data['prize'], realm=realm)
    b.collection_round = transition_round(actor, r, 'ready', reason=f'New public {kind} collection, not yet published or opened')
    return b


@transaction.atomic
def create_all_leaders(actor, source, data):
    """One separate assessment/proof per target, covering the whole annual plan."""
    require_manager(actor, source)
    plan = source.survey_profile.annual_target.plan
    from apps.leadership.models import AnnualPlan
    AnnualPlan.objects.select_for_update().get(pk=plan.pk)
    if plan.targets.filter(status='draft').exists():
        raise ValidationError('ตรวจและตรึงผู้บริหารทุกรายการในทะเบียนปีก่อน / Review and freeze every draft target in the annual register first.')
    targets = list(plan.targets.filter(status='ready').order_by('position__code', 'start_date'))
    if not targets:
        raise ValidationError('ยังไม่มีผู้บริหารที่ตรึงแล้ว / No frozen targets are available.')
    groups = data.get('group_codes', [])
    if set(groups) != {'ST1', 'ST2'}:
        raise ValidationError('F04 ต้องครอบคลุม ST1 และ ST2 / F04 must include ST1 and ST2.')
    created = []
    for target in targets:
        for group in groups:
            old = SurveyProfile.objects.filter(annual_target=target, group_code=group, intake_method='public',
                binding__collection_round__data_kind=collection_mode.data_kind()).first()
            if old:
                created.append(old.binding)
                continue
            values = dict(data, group_code=group, count=data.get('count_'+group.lower(), data.get('count')))
            values['code'] = data['code'][:35]+'-'+target.position.code[:18]+'-'+str(target.pk)[:8]+'-'+group
            values['label_th'] = (data['label_th'][:110]+' · '+target.title_th)[:200]
            values['label_en'] = (data['label_en'][:110]+' · '+target.title_en)[:200]
            created.append(create_collection(actor, source, values, target_override=target))
    return created



@page(['GET', 'POST'])
def setup(request, scope, selected_id):
    public_admission.enabled()
    source = selected_for(scope, selected_id)
    require_manager(request.user, source)
    require_permission(request.user, 'source.manage', scope)
    if request.method == 'GET' and source.instrument_version.instrument.code != 'F04':
        return redirect(reverse('assessment-batch-new', args=[scope.pk]) + '?source=' + str(source.pk))
    now = timezone.localtime().replace(second=0, microsecond=0)
    initial = {'open_at': now, 'due_at': now+timedelta(days=7), 'close_at': now+timedelta(days=8),
               'expires_at': now+timedelta(days=38), 'group_code': source.survey_profile.group_code,
               'setup_stamp': signing.dumps({'actor': str(request.user.pk), 'source': str(source.pk), 'nonce': str(uuid.uuid4())}, salt=SALT)}
    form = PublicSetupForm(request.POST if request.method == 'POST' else None, source=source, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            if source.instrument_version.instrument.code == 'F04' and source.survey_profile.annual_target_id:
                b = create_all_leaders(request.user, source, form.cleaned_data)[0]
            else:
                b = create_collection(request.user, source, form.cleaned_data)
        except (ValidationError, IntegrityError, signing.BadSignature, services.ReceiptError) as exc:
            form.add_error(None, exc if isinstance(exc, ValidationError) else 'สร้างรอบไม่ได้ กรุณาตรวจข้อมูลและสถานะต้นแบบ / Unable to create; check settings and template state.')
        else:
            return redirect('public-assessment-manage', scope_id=scope.pk, selected_id=b.pk)
    return form_page(request, scope, form, 'เตรียมรอบประเมินสาธารณะ / Prepare a public assessment collection',
        notice=collection_mode.setup_notice())


@page(['GET', 'POST'])
def manage(request, scope, selected_id):
    public_admission.enabled()
    b = selected_for(scope, selected_id)
    require_manager(request.user, b)
    if request.method == 'POST' and hasattr(b, 'batch_item'):
        return redirect('assessment-batch-manage', scope_id=scope.pk, batch_id=b.batch_item.batch_id)
    from django.shortcuts import get_object_or_404
    public = get_object_or_404(PublicCollection, binding=b)
    error = ''
    if request.method == 'POST':
        try:
            if request.POST.get('confirm') != 'on':
                raise ValidationError('ตรวจข้อมูลและยืนยันก่อนดำเนินการ / Review and confirm this action.')
            action = request.POST.get('action')
            if action not in {'publish', 'withdraw', 'open', 'close'}:
                raise ValidationError('เลือกการดำเนินการที่รองรับ / Choose a supported action.')
            targets = public_admission.leadership_collections(b, all_groups=True, require_complete=action in {'publish', 'open'})
            with transaction.atomic():
                for target in targets:
                    if action in {'publish', 'withdraw'}:
                        public_admission.set_published(request.user, target.binding_id, action == 'publish')
                    elif action == 'open':
                        if target.binding.collection_round.status != 'open':
                            transition_round(request.user, target.binding.collection_round, 'open', reason='Operator opened public collection')
                    elif action == 'close':
                        reason = request.POST.get('reason', '').strip()
                        if not reason:
                            raise ValidationError('ระบุเหตุผลที่ปิดรอบ / Provide a closing reason.')
                        public_admission.set_published(request.user, target.binding_id, False)
                        if target.binding.collection_round.status == 'open':
                            transition_round(request.user, target.binding.collection_round, 'closed', reason=reason)
        except ValidationError as exc:
            error = ' '.join(exc.messages)
        except (services.ReceiptError, IntegrityError):
            error = 'ยังดำเนินการไม่ได้ ตรวจสถานะ ช่วงเวลา และช่องยืนยัน / Action unavailable. Check status, dates and confirmation.'
        else:
            return redirect('public-assessment-manage', scope_id=scope.pk, selected_id=b.pk)
    count = b.survey_responses.count()
    return render(request, 'participation/public_manage.html', {'scope': scope, 'selected': b,
        'round': b.collection_round, 'public': public, 'submitted': count, 'error': error,
        'reference': b.collection_round.population_snapshot.counts_by_group.get(b.survey_profile.group_code, 0)}, status=422 if error else 200)
