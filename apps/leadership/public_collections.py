"""Create both staff audiences for every frozen F04 target, without a roster."""
import uuid
from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from apps.accounts.permissions import require_permission
from apps.catalog.models import TranslationBundle
from apps.participation.setup import SetupForm
from apps.participation import public_admission
from apps.surveys.models import SurveyProfile
from .models import AnnualPlan

STAFF_GROUPS = [('ST1', 'ST1 บุคลากรสายวิชาการ / Academic staff'),
                ('ST2', 'ST2 บุคลากรสายสนับสนุน / Support staff')]


def add_staff_fields(form):
    for key in ('group_code', 'count'):
        form.fields.pop(key, None)
    form.fields['group_codes'] = forms.MultipleChoiceField(
        label='กลุ่มผู้ตอบ · ต้องครบทั้งสองกลุ่ม / Respondent groups · both required',
        choices=STAFF_GROUPS, initial=['ST1', 'ST2'], widget=forms.CheckboxSelectMultiple,
        help_text='ทั้งสองกลุ่มประเมินผู้บริหารทุกคนทุกตำแหน่ง ไม่เลือกรายชื่อผู้ตอบ / Both groups assess every leader and position; no respondent roster.')
    for code, label in STAFF_GROUPS:
        form.fields['count_'+code.lower()] = forms.IntegerField(min_value=1, max_value=100000,
            label='จำนวนอ้างอิง '+label,
            help_text='กรอกจำนวนรวมของกลุ่มนี้แยกจากอีกกลุ่ม ตามแหล่งอ้างอิง ไม่แนบรายชื่อและไม่ใช่จำนวนผู้ตอบที่ยืนยันตัวตน / Separate aggregate reference count, not identity-verified participation.')


def validate_staff_fields(form, data):
    if set(data.get('group_codes', [])) != {'ST1', 'ST2'}:
        form.add_error('group_codes', 'ต้องเลือกทั้ง ST1 และ ST2 / Select both ST1 and ST2.')


class StaffCollectionForm(SetupForm):
    bundle = forms.ModelChoiceField(label='ชุด F04 และคำแปลที่เผยแพร่แล้ว / Published F04 wording', queryset=TranslationBundle.objects.none())

    def __init__(self, *args, scope, **kwargs):
        super().__init__(*args, **kwargs)
        for key in ('context_th', 'context_en', 'setup_stamp'):
            self.fields.pop(key, None)
        add_staff_fields(self)
        self.fields['bundle'].queryset = TranslationBundle.objects.filter(
            status='published', instrument_version__status='published',
            instrument_version__instrument__code='F04', instrument_version__instrument__scope=scope)
        self.fields['bundle'].label_from_instance = lambda b: 'F04 · '+b.instrument_version.version+' · '+b.bundle_version
        self.fields['bundle'].help_text = 'ต้องมีคำถามรองรับทั้ง ST1 และ ST2 และทุกตำแหน่งที่ตรึงแล้ว / Must support both staff groups and all frozen positions.'
        self.fields['code'].help_text = 'เช่น F04 ทดสอบปี 2569 ระบบต่อท้ายตำแหน่งและกลุ่มให้อัตโนมัติ / Example: F04 test 2569; position and group suffixes are added automatically.'
        self.order_fields(['code', 'bundle', 'group_codes', 'count_st1', 'count_st2'])

    def clean(self):
        data = super().clean()
        validate_staff_fields(self, data)
        return data


@transaction.atomic
def create_staff_collections(actor, scope, plan_id, data):
    public_admission.enabled()
    for permission in ('round.manage', 'population.manage', 'source.manage'):
        require_permission(actor, permission, scope)
    plan = AnnualPlan.objects.select_for_update().get(pk=plan_id, scope=scope)
    if set(data.get('group_codes', [])) != {'ST1', 'ST2'}:
        raise ValidationError('ต้องเลือกทั้ง ST1 และ ST2 / Both staff groups are required.')
    targets = list(plan.targets.filter(status='ready').order_by('position__code', 'start_date'))
    if not targets or plan.targets.filter(status='draft').exists():
        raise ValidationError('ตรวจและตรึงผู้บริหารให้ครบทุกคนทุกตำแหน่งก่อน / Freeze every draft target first.')
    bundle = TranslationBundle.objects.select_related('instrument_version__instrument').get(pk=data['bundle'].pk)
    if (bundle.status != 'published' or bundle.instrument_version.status != 'published'
            or bundle.instrument_version.instrument.scope_id != scope.pk
            or bundle.instrument_version.instrument.code != 'F04'
            or not {'ST1', 'ST2'} <= set(bundle.instrument_version.group_codes)):
        raise ValidationError('เลือก F04 ที่เผยแพร่และรองรับ ST1 กับ ST2 ในพื้นที่นี้ / Choose published F04 wording for both groups in this workspace.')
    from apps.participation.public_setup import build_public_collection
    rows = []
    for target in targets:
        for group, _ in STAFF_GROUPS:
            existing = SurveyProfile.objects.filter(annual_target=target, group_code=group, intake_method='public').select_related('binding').first()
            if existing:
                rows.append(existing.binding)
                continue
            count = data.get('count_'+group.lower())
            if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 100000:
                raise ValidationError('ระบุจำนวนอ้างอิงแต่ละกลุ่ม / Supply each group reference count.')
            values = dict(data, group_code=group, count=count, level='', programme='', counting_unit='person',
                          context_th='', context_en='')
            values['code'] = data['code'][:35]+'-'+target.position.code[:18]+'-'+str(target.pk)[:8]+'-'+group
            values['label_th'] = (data['label_th'][:110]+' · '+target.title_th)[:200]
            values['label_en'] = (data['label_en'][:110]+' · '+target.title_en)[:200]
            rows.append(build_public_collection(actor, scope, plan.period, bundle, values,
                        target=target, activity='public-'+uuid.uuid4().hex))
    return rows


@transaction.atomic
def control_plan(actor, scope, plan_id, action, reason=''):
    """One reviewed operation for all leaders and both staff audiences."""
    public_admission.enabled()
    for permission in ('round.manage', 'population.manage', 'source.manage'):
        require_permission(actor, permission, scope)
    plan = AnnualPlan.objects.select_for_update().get(pk=plan_id, scope=scope)
    if action not in {'launch', 'withdraw', 'close'}:
        raise ValidationError('คำสั่งไม่ถูกต้อง / Invalid action.')
    profile = SurveyProfile.objects.filter(annual_target__plan=plan, intake_method='public').select_related('binding').first()
    if not profile:
        raise ValidationError('สร้างรอบประเมินผู้บริหารก่อน / Create leadership collections first.')
    rows = public_admission.leadership_collections(profile.binding, all_groups=True, require_complete=action == 'launch')
    if action == 'close' and not reason.strip():
        raise ValidationError('ระบุเหตุผลที่ปิด / Provide a closing reason.')
    from apps.rounds.services import transition_round
    for row in rows:
        r = row.binding.collection_round
        if r.scope_id != scope.pk:
            raise ValidationError('ขอบเขตไม่ตรงกัน / Scope mismatch.')
        if action == 'launch':
            if r.status != 'open':
                transition_round(actor, r, 'open', reason='Operator opened and published annual F04 collections')
            public_admission.set_published(actor, row.binding_id, True)
        else:
            public_admission.set_published(actor, row.binding_id, False)
            if action == 'close' and r.status == 'open':
                transition_round(actor, r, 'closed', reason=reason)
    return rows
