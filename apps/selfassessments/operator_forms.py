"""Staff forms use the pinned F06 schema and existing scoped services."""
import uuid

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import SelfAssessmentAssignment
from .validation import DIMENSION_PREFIXES, assignment_questions


def wording(english, th, en):
    return en if english else th


class AssignmentForm(forms.Form):
    def __init__(self, *args, selected, member, english=False, **kwargs):
        super().__init__(*args, **kwargs)
        assignment = SelfAssessmentAssignment(round_instrument=selected, member=member)
        self.questions = assignment_questions(assignment)
        translated = dict(selected.translation_bundle.translations.filter(
            locale='en' if english else 'th').values_list('content_key', 'text'))
        users = get_user_model().objects.filter(is_active=True, membership__is_active=True,
            membership__organization=selected.collection_round.organization).exclude(
            self_assessment_assignments__round_instrument=selected).distinct().order_by('username')
        self.fields['owner'] = forms.ModelChoiceField(queryset=users,
            label=wording(english, 'บัญชีเจ้าของแบบประเมิน', 'Self-report owner'))
        self.fields['duties'] = forms.CharField(max_length=4000, widget=forms.Textarea(attrs={'rows': 3}),
            label=wording(english, 'หน้าที่ที่ปฏิบัติจริง', 'Actual duties'))
        optional = []
        for qid, question in self.questions.items():
            label = qid+' · '+translated.get(qid+'.text', question.text_th)
            if qid.startswith(DIMENSION_PREFIXES):
                optional.append((qid, label))
            if question.answer_type == 'integer_scale':
                self.fields['expected_'+qid] = forms.TypedChoiceField(coerce=int,
                    choices=[('', wording(english, 'เลือกระดับที่คาดหวัง', 'Choose expected level'))]
                            + [(str(n), str(n)) for n in range(1, 6)], label=label)
        self.fields['dimensions'] = forms.MultipleChoiceField(required=False, choices=optional,
            widget=forms.CheckboxSelectMultiple,
            label=wording(english, 'ด้าน M/T ที่เกี่ยวข้องกับหน้าที่', 'Applicable M/T dimensions'),
            help_text=wording(english, 'เลือกเฉพาะด้านที่เกี่ยวข้อง ข้ออื่นในกลุ่มคงอยู่ทุกข้อ',
                             'Select applicable dimensions. All other questions in this group remain included.'))

    def assignment_data(self):
        return {'user_id': self.cleaned_data['owner'].pk, 'duties': self.cleaned_data['duties'],
            'expected_levels': {qid: self.cleaned_data['expected_'+qid]
                for qid, q in self.questions.items() if q.answer_type == 'integer_scale'},
            'applicable_question_ids': [qid for qid in self.questions if not qid.startswith(DIMENSION_PREFIXES)]
                + self.cleaned_data['dimensions']}


class ReasonForm(forms.Form):
    def __init__(self, *args, english=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['reason'] = forms.CharField(max_length=2000, widget=forms.Textarea(attrs={'rows': 3}),
            label=wording(english, 'เหตุผล', 'Reason'), help_text=wording(english,
                'ระบุเหตุผลของการดำเนินการโดยไม่ใส่คำตอบหรือข้อมูลรายบุคคล',
                'Describe this action without including individual answers or personal information.'))


class CalculationForm(forms.Form):
    idempotency_key = forms.CharField(max_length=160, widget=forms.HiddenInput)

    def __init__(self, *args, english=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial.update(idempotency_key=str(uuid.uuid4()), cutoff=timezone.now().replace(microsecond=0))
        self.fields['cutoff'] = forms.DateTimeField(label=wording(english,
            'ใช้คำตอบที่ส่งถึงวันและเวลา (cutoff)', 'Include submissions up to (cutoff)'),
            widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M:%S', attrs={'type': 'datetime-local', 'step': '1'}))


class DecisionForm(ReasonForm):
    reviewed_token = forms.CharField(max_length=64, min_length=64, widget=forms.HiddenInput)

    def __init__(self, *args, english=False, **kwargs):
        super().__init__(*args, english=english, **kwargs)
        self.fields['outcome'] = forms.ChoiceField(label=wording(english, 'ผลการตรวจ', 'Decision'),
            choices=[('', wording(english, 'เลือกผลการตรวจ', 'Choose a decision')),
                     ('approved', wording(english, 'รับรองผลรวม', 'Approve aggregate results')),
                     ('returned', wording(english, 'ส่งกลับให้จัดทำชุดผลใหม่', 'Return for a new result set'))])
