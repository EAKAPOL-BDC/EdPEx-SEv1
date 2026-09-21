from django import forms
from .models import QuestionOption
from .group_registry import group_choices


class SnapshotForm(forms.Form):
    snapshot = forms.CharField(widget=forms.HiddenInput)


class VersionCopyForm(SnapshotForm):
    title_th = forms.CharField(label='ชื่อแบบฟอร์ม (ไทย) / Thai title', max_length=1000)
    instruction = forms.CharField(label='คำชี้แจงผู้ตอบ (ไทย) / Respondent instructions', max_length=20000,
                                  widget=forms.Textarea(attrs={'rows': 10}))
    instructions_curated = forms.BooleanField(required=False,
        label='ตรวจความเหมาะสมของคำชี้แจงสำหรับผู้ตอบแล้ว / Instructions checked for respondents')


class QuestionForm(SnapshotForm):
    question_id = forms.RegexField(r'^F0[1-6]-[A-Z0-9-]+$', label='รหัสคำถาม / Question ID', max_length=40,
        help_text='เช่น F06-X01 รหัสเดิมเปลี่ยนไม่ได้ / Existing IDs are fixed.')
    text_th = forms.CharField(label='คำถามภาษาไทย / Thai question', max_length=8000, widget=forms.Textarea(attrs={'rows': 4}))
    answer_type = forms.ChoiceField(label='ประเภทคำตอบ / Answer type', choices=[
        ('context_reference', 'ข้อมูลบริบท / Context information'), ('date', 'วันที่ / Date'),
        ('date_time_range', 'ช่วงวันเวลา / Date and time range'), ('decimal', 'ตัวเลข / Number'),
        ('evidence_reference', 'อ้างอิงหลักฐาน / Evidence reference'), ('integer_scale', 'ระดับคะแนน / Rating scale'),
        ('multi_choice', 'เลือกได้หลายข้อ / Multiple choices'), ('review_metadata', 'ข้อมูลการตรวจ / Verification information'),
        ('single_choice', 'เลือกข้อเดียว / Single choice'), ('text', 'ข้อความ / Text')])
    group_codes = forms.MultipleChoiceField(label='กลุ่มผู้ตอบ / Respondent groups', widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, version, question=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(['snapshot', 'question_id', 'answer_type', 'text_th', 'group_codes'])
        self.fields['group_codes'].choices = group_choices(version.group_codes)
        if question:
            self.fields['question_id'].disabled = True
        if question and question.bindings.exists():
            self.fields['answer_type'].disabled = True
            self.fields['group_codes'].disabled = True
        if version.instrument.code == 'F06' and not question:
            self.fields['answer_type'].choices = [('text', 'ข้อความ / Text'), ('single_choice', 'เลือกข้อเดียว / Single choice'), ('integer_scale', 'คะแนน 1–5 / Score 1–5')]


class OptionForm(forms.Form):
    id = forms.ModelChoiceField(queryset=QuestionOption.objects.none(), required=False, widget=forms.HiddenInput)
    code = forms.CharField(label='รหัส / Code', max_length=80)
    label_th = forms.CharField(label='ตัวเลือกภาษาไทย / Thai choice', max_length=8000, widget=forms.Textarea(attrs={'rows': 2}))
    score = forms.DecimalField(label='คะแนน / Score', required=False, max_digits=12, decimal_places=4)
    answer_status = forms.ChoiceField(label='สถานะ / Status', choices=[('answered', 'คำตอบ / Answered'), ('not_applicable', 'ไม่เกี่ยวข้อง / Not applicable'), ('unable_to_assess', 'ประเมินไม่ได้ / Unable to assess')], initial='answered')

    def __init__(self, *args, question=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['id'].queryset = question.options.all() if question else QuestionOption.objects.none()


OptionFormSet = forms.formset_factory(OptionForm, extra=5, can_delete=True, max_num=40, validate_max=True)


class DeleteForm(SnapshotForm):
    reason = forms.CharField(label='เหตุผลการลบ / Deletion reason', max_length=1000, widget=forms.Textarea(attrs={'rows': 3}))
    confirm = forms.BooleanField(label='ยืนยันลบรายการนี้ / Confirm deletion')


class CloneForm(forms.Form):
    new_version = forms.CharField(label='หมายเลขรุ่นใหม่ / New version', max_length=40)


class TranslationForm(forms.Form):
    revision = forms.IntegerField(widget=forms.HiddenInput)
    source_digest = forms.CharField(widget=forms.HiddenInput)
    text = forms.CharField(label='คำแปลภาษาอังกฤษ / English translation', max_length=30000, widget=forms.Textarea(attrs={'rows': 8}))


class PublishForm(forms.Form):
    bundle = forms.ModelChoiceField(label='ชุดคำแปล / Translation bundle', queryset=None)
    confirm = forms.BooleanField(label='ตรวจเนื้อหาครบและยืนยันเผยแพร่รุ่นนี้ / Confirm publication of this reviewed version')

    def __init__(self, *args, version, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['bundle'].queryset = version.translation_bundles.exclude(status='retired')
        self.fields['bundle'].label_from_instance = lambda b: b.bundle_version
