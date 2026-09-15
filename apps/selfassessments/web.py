"""Server-rendered owner workspace; no reviewer controls on a self-report form."""
import uuid
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from apps.calculations.services import IdempotencyConflict
from .services import list_own_assignments, read_own_assignment, save_revision


class SelfReportForm(forms.Form):
    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    idempotency_key = forms.CharField(max_length=160, widget=forms.HiddenInput)

    def __init__(self, schema, *args, english=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.schema = schema
        self.initial.update(expected_revision=schema['revision'], idempotency_key=str(uuid.uuid4()))
        for q in schema['questions']:
            qid = q['id']
            previous = schema['answers'].get(qid, {})
            if q['type'] == 'text':
                field = forms.CharField(required=False, max_length=4000, widget=forms.Textarea(attrs={'rows': 3}))
                initial = previous.get('value', '')
            else:
                choices = [('', 'Not answered' if english else 'ยังไม่ตอบ')]
                choices += [('value:'+str(o['value']), o['label']) for o in q['options'] if o['code'] != 'NA']
                if q['allow_na']:
                    choices.append(('not_applicable', 'Not applicable / no opportunity' if english else 'ไม่เกี่ยวข้อง / ไม่มีโอกาส'))
                choices += [('unable_to_assess', 'Unable to assess' if english else 'ยังประเมินไม่ได้'),
                            ('skipped', 'Prefer to skip' if english else 'เลือกข้าม')]
                field = forms.ChoiceField(required=False, choices=choices)
                initial = 'value:'+str(previous['value']) if previous.get('status') == 'answered' else previous.get('status', '')
                if initial == 'missing':
                    initial = ''
            field.label = qid+' · '+q['text']
            if q['expected_level'] is not None:
                field.help_text = ('Expected level: ' if english else 'ระดับที่คาดหวัง: ')+str(q['expected_level'])
            field.initial = initial
            self.fields[qid] = field
            if q['type'] == 'integer_scale':
                for suffix, label, limit in [('reason', 'Reason' if english else 'เหตุผลกรณีไม่เกี่ยวข้อง', 1000),
                        ('example', 'Example (optional)' if english else 'ตัวอย่างพฤติกรรม (เลือกกรอก)', 4000),
                        ('development_plan', 'Development plan (optional)' if english else 'แผนพัฒนา (เลือกกรอก)', 4000)]:
                    self.fields[qid+'__'+suffix] = forms.CharField(required=False, label=label, max_length=limit,
                        initial=previous.get(suffix, ''), widget=forms.Textarea(attrs={'rows': 2}))
            if not schema['editable']:
                for name, item in self.fields.items():
                    if name.startswith(qid):
                        item.disabled = True

    def answers(self):
        result = {}
        for q in self.schema['questions']:
            qid = q['id']
            raw = self.cleaned_data[qid]
            value = {'status': 'missing'}
            if q['type'] == 'text':
                if raw:
                    value = {'status': 'answered', 'value': raw}
            elif raw.startswith('value:'):
                chosen = raw[6:]
                value = {'status': 'answered', 'value': int(chosen) if q['type'] == 'integer_scale' else chosen}
            elif raw:
                value = {'status': raw}
            for suffix in ('reason', 'example', 'development_plan'):
                text = self.cleaned_data.get(qid+'__'+suffix, '')
                if text:
                    value[suffix] = text
            result[qid] = value
        return result


@login_required
@never_cache
@require_http_methods(['GET'])
def mine(request):
    return render(request, 'selfassessments/list.html', {'assignments': list_own_assignments(request.user)})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def detail(request, assignment_id):
    english = request.LANGUAGE_CODE == 'en'
    try:
        schema = read_own_assignment(request.user, assignment_id=assignment_id, locale='en' if english else 'th')
    except ObjectDoesNotExist:
        raise Http404 from None
    form = SelfReportForm(schema, request.POST if request.method == 'POST' else None, english=english)
    code = 200
    if request.method == 'POST' and form.is_valid():
        try:
            mode = request.POST.get('action')
            if mode not in {'draft', 'submitted'} or not schema['editable']:
                raise ValidationError('Invalid action or closed window.')
            save_revision(request.user, assignment_id=assignment_id, expected_revision=form.cleaned_data['expected_revision'],
                idempotency_key=form.cleaned_data['idempotency_key'], status=mode, answers=form.answers())
            messages.success(request, ('Answers saved.' if english else 'บันทึกคำตอบแล้ว') if mode == 'draft'
                             else ('Self-report submitted.' if english else 'ส่งคำตอบประเมินตนเองแล้ว'))
            return redirect('self-assessment-detail', assignment_id=assignment_id)
        except IdempotencyConflict:
            code = 409
            form.add_error(None, 'A newer version exists. Reload before saving.' if english else 'มีคำตอบรุ่นใหม่แล้ว กรุณาเปิดหน้าคำตอบใหม่ก่อนบันทึก')
        except ValidationError:
            code = 422
            form.add_error(None, 'Check your answers and the reason for not-applicable dimensions; the round must be open.' if english
                           else 'ตรวจคำตอบและเหตุผลในข้อที่ไม่เกี่ยวข้อง โดยรอบต้องยังเปิดรับคำตอบ')
    return render(request, 'selfassessments/detail.html', {'schema': schema, 'form': form}, status=code)
