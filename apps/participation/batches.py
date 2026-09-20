"""Multi-group anonymous collection setup with separate counting contexts."""
import uuid
from datetime import timedelta
from django import forms
from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import get_language
from apps.accounts.models import AccessScope
from apps.accounts.permissions import require_permission, can_access
from apps.accounts.templatetags.portal_ui import ui_wording
from apps.catalog.models import TranslationBundle
from apps.rounds.models import ReportingPeriod
from apps.rounds.services import transition_round
from apps.selfassessments.operator_web import page
from apps.surveys.operator import selected_for
from .models import AssessmentBatch, AssessmentBatchItem, PublicCollection
from .public_catalog import GROUPS, LEVELS, PROGRAMMES
from .setup import SetupForm
from .public_setup import build_public_collection
from . import public_admission, services

SALT = 'nexora.public.batch.v1'


def authorize(actor, scope):
    public_admission.enabled()
    for permission in ('round.manage', 'population.manage', 'source.manage'):
        require_permission(actor, permission, scope)


def contexts(group, code):
    if code == 'F01' and group in LEVELS:
        return [(level, key, th+' / '+en) for level in LEVELS[group] for key, th, en in PROGRAMMES[level]]
    return [('', '', GROUPS[group][0]+' / '+GROUPS[group][1])]


class BatchForm(SetupForm):
    bundle = forms.ModelChoiceField(queryset=TranslationBundle.objects.none(), label='แบบประเมินและรุ่นที่เผยแพร่ / Published assessment version')
    period = forms.ModelChoiceField(queryset=ReportingPeriod.objects.none(), label='ปีที่นำผลไปรายงาน / Reporting period')
    group_codes = forms.MultipleChoiceField(widget=forms.CheckboxSelectMultiple, label='กลุ่มผู้ตอบ เลือกได้หลายกลุ่ม / Respondent groups — select multiple')

    def __init__(self, *args, scope, bundle, **kwargs):
        super().__init__(*args, **kwargs)
        self.scope, self.bundle = scope, bundle
        self.fields.pop('count')
        self.fields['bundle'].queryset = TranslationBundle.objects.filter(pk=bundle.pk, instrument_version__instrument__scope=scope, status='published', instrument_version__status='published')
        self.fields['bundle'].initial = bundle.pk
        self.fields['bundle'].widget = forms.HiddenInput()
        self.fields['period'].queryset = ReportingPeriod.objects.filter(calendar__scope=scope, approved=True).select_related('calendar').order_by('-reporting_year_be')
        self.fields['period'].label_from_instance = lambda p: f'{p.reporting_year_be} · {p.code} · {p.calendar.label}'
        self.fields['code'].label = 'ชื่อรอบหลัก / Main collection name'
        self.fields['code'].help_text = 'เช่น แบบสำรวจประสบการณ์ผู้เรียน ปีการศึกษา 2568 / Example: Student Experience Survey, Academic Year 2568.'
        self.fields['group_codes'].help_text = 'เลือกทุกกลุ่มที่ต้องการ ไม่ต้องเพิ่มรายชื่อผู้ตอบ / Select all eligible groups; no respondent roster is needed.'
        self.fields['period'].help_text = 'F01 ใช้ปีการศึกษา ส่วน F02–F06 ใช้ปีงบประมาณ ตรวจชื่อปีก่อนบันทึก / F01 uses an academic year; F02–F06 use a fiscal year.'
        code = bundle.instrument_version.instrument.code
        groups = [g for g in bundle.instrument_version.group_codes if g in GROUPS]
        self.fields['group_codes'].choices = [(g, g+' · '+ui_wording(GROUPS[g][0]+' / '+GROUPS[g][1], get_language())) for g in groups]
        self.cards, self.context_fields = [], []
        for index, group in enumerate(groups):
            rows = []
            for offset, (level, programme, label) in enumerate(contexts(group, code)):
                name = f'count_{index}_{offset}'
                self.fields[name] = forms.IntegerField(required=False, min_value=1, max_value=100000,
                    label=ui_wording(label, get_language()), help_text='จำนวนอ้างอิง เช่น 120 / Reference count, e.g. 120',
                    widget=forms.NumberInput(attrs={'placeholder': '—', 'inputmode': 'numeric'}))
                self.context_fields.append((name, group, level, programme, label))
                rows.append(self[name])
            unit = f'unit_{index}'
            self.fields[unit] = forms.ChoiceField(required=False, label='หน่วยนับ / Counting unit', initial='person',
                choices=[('person', 'บุคคล / Person'), ('organization_representative', 'ผู้แทนองค์กร / Organisation representative'), ('community_representative', 'ผู้แทนชุมชน / Community representative')])
            if code != 'F02':
                self.fields[unit].widget = forms.HiddenInput()
            self.cards.append({'group': group, 'title': group+' · '+ui_wording(GROUPS[group][0]+' / '+GROUPS[group][1], get_language()), 'rows': rows, 'unit': self[unit]})
        self.fields['confirm'].label = 'ตรวจกลุ่ม หลักสูตร จำนวนอ้างอิง และเข้าใจว่านี่เป็นรอบทดสอบที่ยังไม่เปิดรับ / I reviewed groups, programmes and counts; this test batch will not open automatically'
        for field in self.fields.values():
            field.label = ui_wording(field.label, get_language())
            field.help_text = ui_wording(field.help_text, get_language())

    def clean(self):
        data = super().clean()
        period = data.get('period')
        if period:
            from apps.governance.policies import validate_period
            try:
                validate_period(self.bundle.instrument_version.instrument.code, period)
            except ValidationError as exc:
                self.add_error('period', exc)
        selected = set(data.get('group_codes', []))
        entries = []
        for name, group, level, programme, label in self.context_fields:
            count = data.get(name)
            if count and group not in selected:
                self.add_error(name, 'เลือกกลุ่มนี้ด้วย หรือเว้นจำนวนว่าง / Select this group or leave its count blank.')
            if count and group in selected:
                index = name.split('_')[1]
                unit = data.get('unit_'+index) or 'person'
                if self.bundle.instrument_version.instrument.code != 'F02' and unit != 'person':
                    self.add_error('unit_'+index, 'แบบนี้นับบุคคล / This assessment counts people.')
                entries.append(dict(group_code=group, level=level, programme=programme, count=count, counting_unit=unit, description=label))
        for group in selected:
            if not any(e['group_code'] == group for e in entries):
                self.add_error('group_codes', group+': ระบุจำนวนอย่างน้อยหนึ่งหลักสูตร/รายการ / Enter a count for at least one programme or context.')
        data['entries'] = entries
        return data


@transaction.atomic
def create_batch(actor, scope, data):
    authorize(actor, scope)
    AccessScope.objects.select_for_update().get(pk=scope.pk)
    stamp = signing.loads(data['setup_stamp'], salt=SALT, max_age=3600)
    if stamp['actor'] != str(actor.pk) or stamp['scope'] != str(scope.pk):
        raise signing.BadSignature()
    batch_id = uuid.UUID(stamp['nonce'])
    bundle = TranslationBundle.objects.select_for_update().select_related('instrument_version__instrument').get(pk=data['bundle'].pk)
    if (bundle.instrument_version.instrument.scope_id != scope.pk or bundle.status != 'published'
            or bundle.instrument_version.status != 'published' or bundle.instrument_version.instrument.code == 'F04'):
        raise ValidationError('ตรวจรุ่นแบบประเมิน; F04 ใช้ทะเบียนผู้บริหาร / Check the published form; F04 uses the leadership register.')
    if bundle.instrument_version.instrument.code == 'F05' and bundle.instrument_version.version != '2.1-quantitative':
        raise ValidationError('F05 ใช้รุ่นข้อมูลเชิงปริมาณ 2.1 / F05 requires the quantitative 2.1 version.')
    period = ReportingPeriod.objects.select_for_update().select_related('calendar').get(pk=data['period'].pk)
    if period.calendar.scope_id != scope.pk or not period.approved:
        raise ValidationError('ปีไม่ตรงพื้นที่ / Invalid reporting period.')
    from apps.governance.policies import validate_period
    validate_period(bundle.instrument_version.instrument.code, period)
    entries = data['entries']
    if not entries or set(e['group_code'] for e in entries) != set(data['group_codes']):
        raise ValidationError('ตรวจรายการกลุ่มและจำนวน / Check groups and counts.')
    keys = set()
    for entry in entries:
        key = (entry['group_code'], entry['level'], entry['programme'])
        valid = {(l, p) for l, p, label in contexts(entry['group_code'], bundle.instrument_version.instrument.code)} if entry['group_code'] in GROUPS else set()
        if (key in keys or entry['group_code'] not in bundle.instrument_version.group_codes or key[1:] not in valid
                or type(entry['count']) is not int or not 1 <= entry['count'] <= 100000):
            raise ValidationError('กลุ่ม หลักสูตร หรือจำนวนไม่ถูกต้อง / Invalid group, programme or count.')
        keys.add(key)
    if AssessmentBatch.objects.filter(pk=batch_id).exists():
        return AssessmentBatch.objects.get(pk=batch_id, scope=scope, created_by=actor)
    batch = AssessmentBatch.objects.create(id=batch_id, scope=scope, title=data['code'], created_by=actor)
    for index, entry in enumerate(entries):
        values = {**data, **entry}
        values['code'] = data['code'][:40]+' · '+entry['group_code']+' · '+batch_id.hex[:8]+'-'+str(index+1)
        values['context_th'] = (data['context_th']+' · '+entry['description'].split(' / ')[0])[:1200]
        values['context_en'] = (data['context_en']+' · '+entry['description'].split(' / ')[-1])[:1200]
        b = build_public_collection(actor, scope, period, bundle, values, activity='batch-'+uuid.uuid5(batch_id, str(index)).hex)
        AssessmentBatchItem.objects.create(batch=batch, binding=b)
    return batch


@transaction.atomic
def control(actor, batch, action, reason=''):
    authorize(actor, batch.scope)
    AssessmentBatch.objects.select_for_update().get(pk=batch.pk)
    if action not in {'launch', 'publish', 'withdraw', 'open', 'close'}:
        raise ValidationError('เลือกการดำเนินการที่รองรับ / Invalid action.')
    items = list(batch.items.select_related('binding__collection_round', 'binding__survey_profile').order_by('pk'))
    if not items:
        raise ValidationError('ไม่มีรายการ / Empty batch.')
    if action == 'close' and not reason.strip():
        raise ValidationError('ระบุเหตุผลที่ปิด / Provide a closing reason.')
    states = {item.binding.collection_round.status for item in items}
    if action in {'launch', 'open', 'publish'} and not states <= {'ready', 'open'}:
        raise ValidationError('มีรายการที่ปิดแล้วหรือไม่พร้อม ต้องตรวจสถานะทุกรายการ / Some collections are closed or not ready. Review every item.')
    if action == 'close' and not states <= {'open', 'closed'}:
        raise ValidationError('ปิดได้เฉพาะรายการที่เปิดรับแล้ว / Only opened collections can be closed.')
    for item in items:
        b = item.binding
        if b.collection_round.scope_id != batch.scope_id:
            raise ValidationError('รายการต่างพื้นที่ / Scope mismatch.')
        if action == 'launch':
            if b.collection_round.status != 'open':
                transition_round(actor, b.collection_round, 'open', reason='Operator opened and published collection')
            public_admission.set_published(actor, b.pk, True)
        elif action in {'publish', 'withdraw'}:
            public_admission.set_published(actor, b.pk, action == 'publish')
        elif action == 'open' and b.collection_round.status != 'open':
            transition_round(actor, b.collection_round, 'open', reason='Opened public multi-group batch')
        elif action == 'close':
            public_admission.set_published(actor, b.pk, False)
            if b.collection_round.status == 'open':
                transition_round(actor, b.collection_round, 'closed', reason=reason)


@page(['GET', 'POST'])
def setup(request, scope):
    authorize(request.user, scope)
    bundles = TranslationBundle.objects.filter(instrument_version__instrument__scope=scope, status='published', instrument_version__status='published', instrument_version__instrument__code__in=['F01', 'F02', 'F03', 'F05', 'F06']).select_related('instrument_version__instrument')
    bundles = bundles.exclude(Q(instrument_version__instrument__code='F05') & ~Q(instrument_version__version='2.1-quantitative'))
    source = None
    if request.GET.get('source'):
        source = selected_for(scope, request.GET['source'])
    bundle_id = request.POST.get('bundle') if request.method == 'POST' else request.GET.get('bundle') or (source.translation_bundle_id if source else None)
    try:
        bundle = bundles.filter(pk=bundle_id).first() if bundle_id else None
    except (ValidationError, ValueError):
        bundle = None
    if bundle is None:
        if request.method == 'POST':
            from django.http import HttpResponse
            return HttpResponse('รุ่นแบบประเมินไม่พร้อมใช้งาน / Assessment version unavailable.', status=422)
        return render(request, 'participation/batch_choose.html', {'scope': scope, 'bundles': bundles})
    now = timezone.localtime().replace(second=0, microsecond=0)
    initial = {'open_at': now, 'due_at': now+timedelta(days=7), 'close_at': now+timedelta(days=8), 'expires_at': now+timedelta(days=38), 'period': request.GET.get('period'),
        'setup_stamp': signing.dumps({'actor': str(request.user.pk), 'scope': str(scope.pk), 'nonce': str(uuid.uuid4())}, salt=SALT)}
    if source:
        initial.update({k: getattr(source.collection_round, k) for k in ('code', 'period', 'open_at', 'due_at', 'close_at', 'privacy_notice')})
        initial.update({k: getattr(source.survey_profile, k) for k in ('context_th', 'context_en')})
        initial['group_codes'] = [source.survey_profile.group_code]
    form = BatchForm(request.POST if request.method == 'POST' else None, scope=scope, bundle=bundle, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            batch = create_batch(request.user, scope, form.cleaned_data)
        except (ValidationError, IntegrityError, signing.BadSignature, services.ReceiptError) as exc:
            form.add_error(None, exc if isinstance(exc, ValidationError) else 'สร้างไม่ได้ กรุณาตรวจข้อมูลหรือเปิดแบบฟอร์มใหม่ / Unable to create; review entries or reopen this form.')
        else:
            return redirect('assessment-batch-manage', scope_id=scope.pk, batch_id=batch.pk)
    sections = [('01', 'ข้อมูลรอบ / Collection', ['code', 'period', 'context_th', 'context_en']),
        ('03', 'ช่วงเวลาและแหล่งอ้างอิง / Schedule and source', ['open_at', 'due_at', 'close_at', 'source_title', 'source_reference']),
        ('04', 'คำชี้แจงและหลักฐาน / Notice and proof', ['privacy_notice', 'label_th', 'label_en', 'expires_at', 'workload', 'prize'])]
    return render(request, 'participation/batch_form.html', {'scope': scope, 'form': form, 'bundle': bundle, 'source': source,
        'can_period': can_access(request.user, 'calendar.manage', scope),
        'sections': [(n, t, [form[k] for k in keys]) for n, t, keys in sections]}, status=422 if form.errors else 200)


@page(['GET', 'POST'])
def manage(request, scope, batch_id):
    authorize(request.user, scope)
    batch = get_object_or_404(AssessmentBatch, pk=batch_id, scope=scope)
    error = ''
    if request.method == 'POST':
        try:
            if request.POST.get('confirm') != 'on':
                raise ValidationError('ตรวจข้อมูลและยืนยัน / Review and confirm.')
            control(request.user, batch, request.POST.get('action'), request.POST.get('reason', ''))
        except (ValidationError, IntegrityError, services.ReceiptError) as exc:
            error = ' '.join(exc.messages) if isinstance(exc, ValidationError) else 'ดำเนินการไม่ได้ ไม่มีรายการใดถูกเปลี่ยน / Action failed; no items changed.'
        else:
            return redirect('assessment-batch-manage', scope_id=scope.pk, batch_id=batch.pk)
    from .collection_presentation import collection_state, aggregate_state, short_context
    rows = []
    for item in batch.items.select_related('binding__collection_round__population_snapshot', 'binding__survey_profile', 'binding__public_collection'):
        b = item.binding
        rows.append({'state': collection_state(b), 'title':short_context(b.public_collection, get_language().startswith('en')), 'binding': b, 'group': b.survey_profile.group_code, 'context': b.survey_profile.context_en if get_language().startswith('en') else b.survey_profile.context_th,
            'count': b.collection_round.population_snapshot.counts_by_group[b.survey_profile.group_code], 'submitted': b.survey_responses.count(), 'public': b.public_collection})
    states = {row['binding'].collection_round.status for row in rows}
    return render(request, 'participation/batch_manage.html', {'scope': scope, 'batch': batch, 'rows': rows, 'error': error, 'state':aggregate_state([row['binding'] for row in rows]), 'total_responses':sum(row['submitted'] for row in rows), 'group_count':len({row['group'] for row in rows}),
        'can_launch': bool(rows) and states <= {'ready','open'} and all(row['binding'].collection_round.close_at > timezone.now() for row in rows) and any(row['binding'].collection_round.status != 'open' or not row['public'].published for row in rows),
        'can_open': bool(rows) and 'ready' in states and states <= {'ready', 'open'},
        'can_publish': bool(rows) and states <= {'ready', 'open'}, 'can_close': bool(rows) and 'open' in states and states <= {'open', 'closed'}}, status=422 if error else 200)
