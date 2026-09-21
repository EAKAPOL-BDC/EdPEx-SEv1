from django import forms
from django.db.models import Q
from apps.catalog.group_registry import group_choices
from apps.rounds.web_forms import RoundForm, PopulationForm
from apps.catalog.models import TranslationBundle
from .models import SurveyProfile
from .schema import questions, fixed, options, normalize, respondent_schema


class SurveyRoundForm(RoundForm):
    group_code = forms.ChoiceField(label='กลุ่มผู้ตอบหนึ่งกลุ่มในรอบนี้ / One respondent group for this round',
        help_text='เลือกกลุ่มที่แบบฟอร์มและรุ่นที่เลือกใช้รองรับ โดยชื่อในวงเล็บคือกลุ่มหลัก / Select a group supported by the selected form version. Parent groups appear in parentheses.')
    counting_unit = forms.ChoiceField(label='หน่วยนับ / Counting unit', choices=[('person','บุคคล / Person'),('organization_representative','ผู้แทนองค์กร / Organization'),('community_representative','ผู้แทนชุมชน / Community')])
    context_th = forms.CharField(label='บริบทภาษาไทย / Thai context',max_length=1200,help_text='หลักสูตร/โครงการ/รอบบุคลากร หรือผู้บริหารและช่วงดำรงตำแหน่ง ใช้บริบทเดียวกันสำหรับผู้ตอบในรอบนี้')
    context_en = forms.CharField(label='บริบทภาษาอังกฤษ / English context',max_length=1200)
    assessor_role = forms.ChoiceField(label='ตำแหน่งผู้ถูกประเมิน (F04) / F04 leadership role',required=False,choices=[('','—'),('DE','คณบดี / Dean'),('BO','กรรมการ / Board'),('VD','รองคณบดี / Vice dean'),('AS','ผู้ช่วยคณบดี / Assistant dean'),('PC','ประธานหลักสูตร / Program chair')])
    study_options = forms.MultipleChoiceField(label='ชั้นปี/ช่วงศึกษาที่ใช้ใน F01 / F01 study stages',required=False,widget=forms.CheckboxSelectMultiple,
        choices=[(f'option_{n}',label) for n,label in enumerate(['ปี 1 / Year 1','ปี 2 / Year 2','ปี 3 / Year 3','ปี 4 / Year 4','ปี 5+ / Year 5+','รายวิชา / Coursework','วิทยานิพนธ์ / Thesis','ทั้งสองส่วน / Both'],1)])
    context_checked = forms.BooleanField(label='ตรวจกลุ่ม หน่วยนับ และบริบททั้งสองภาษาแล้ว / I checked the group, counting unit and bilingual context')

    def __init__(self,*args,scope,**kwargs):
        super().__init__(*args,scope=scope,**kwargs)
        self.fields['bundle'].label = 'แบบสำรวจและคำแปลที่เผยแพร่แล้ว / Published survey and translations'
        self.fields['bundle'].queryset = TranslationBundle.objects.exclude(pk__in=TranslationBundle.objects.filter(instrument_version__source_metadata__synthetic_only=True)).filter(status='published',instrument_version__status='published',instrument_version__instrument__scope=scope,instrument_version__instrument__code__in=['F01','F02','F03','F04','F05','F06']).exclude(Q(instrument_version__instrument__code='F05') & ~Q(instrument_version__version='2.1-quantitative')).select_related('instrument_version__instrument')
        if kwargs.get('editing') and self.initial.get('bundle'):
            pinned=getattr(self.initial['bundle'],'pk',self.initial['bundle'])
            self.fields['bundle'].queryset=TranslationBundle.objects.filter(
                Q(pk__in=self.fields['bundle'].queryset.values('pk')) | Q(pk=pinned,instrument_version__instrument__scope=scope))
        self.fields['bundle'].label_from_instance = lambda b:f'{b.instrument_version.instrument.code} · {b.instrument_version.version} · {b.bundle_version}'
        codes = sorted({g for b in self.fields['bundle'].queryset for g in b.instrument_version.group_codes})
        self.fields['group_code'].choices = [('', '—'), *group_choices(codes)]

    def clean(self):
        data = super().clean()
        bundle, group = data.get('bundle'), data.get('group_code')
        if bundle and group and group not in bundle.instrument_version.group_codes:
            self.add_error('group_code', 'กลุ่มนี้ไม่อยู่ในรุ่นแบบฟอร์มที่เลือก / This group is not supported by the selected form version.')
        if bundle and data.get('period'):
            from apps.governance.policies import validate_period
            try: validate_period(bundle.instrument_version.instrument.code,data['period'])
            except forms.ValidationError as exc:self.add_error('period',exc)
        return data



class SurveyPopulationForm(PopulationForm):
    count = forms.IntegerField(label='จำนวนหน่วยที่มีสิทธิ์ตอบจริง / Actual eligible units',min_value=1)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields.pop('st1'); self.fields.pop('st2')


class AccessForm(forms.Form):
    code = forms.CharField(label='รหัสคำเชิญ / Invitation code',min_length=30,max_length=100,widget=forms.PasswordInput(attrs={'autocomplete':'off'}))


def posted_payload(profile, data):
    """Parse form values, then let the closed service schema validate all values."""
    result = {}
    for qid,q in questions(profile).items():
        if fixed(profile,q) is not None:
            continue
        if q.answer_type == 'multi_choice':
            raw = data.getlist(qid)
        else:
            raw = data.get(qid,'')
        if not raw:
            result[qid] = {'status':'skipped'}
        elif q.answer_type in {'text','decimal'}:
            result[qid] = {'status':'answered','value':raw}
        elif q.answer_type == 'multi_choice':
            result[qid] = {'status':'answered','value':raw}
        elif raw.startswith('state:'):
            result[qid] = {'status':raw[6:]}
        else:
            value = raw[6:] if raw.startswith('value:') else raw
            if q.answer_type == 'integer_scale':
                try: value = int(value)
                except ValueError: pass
            result[qid] = {'status':'answered','value':value}
    for qid in list(result):
        if qid.startswith(('F06-M','F06-T')) and data.get(qid+'-reason'):
            result[qid]['reason']=data[qid+'-reason']
    if result.get('F02-P04',{}).get('value') == 'month_year':
        result['F02-P04']['month'] = data.get('F02-P04-month','')
    return result


class ResponseForm(forms.Form):
    revision = forms.IntegerField(min_value=0,widget=forms.HiddenInput)
    def __init__(self,profile,draft,revision,locale,*args,**kwargs):
        include_conditional = kwargs.pop('include_conditional', False)
        super().__init__(*args,**kwargs)
        self.schema = respondent_schema(profile,draft,locale,include_conditional=include_conditional)
        self.initial['revision'] = revision
        for q in self.schema['questions']:
            previous = draft.get(q['id'],{})
            opts = q['options']
            quantitative=self.schema.get('quantitative_f05',False)
            if q['type'] == 'text':
                field = forms.CharField(required=False,max_length=500,widget=forms.Textarea(attrs={'rows':3}))
                initial = previous.get('value','')
            elif q['type'] == 'decimal':
                field=forms.DecimalField(required=False,min_value=0,max_value=8784,decimal_places=2,max_digits=6,widget=forms.NumberInput(attrs={'step':'0.01'}))
                initial=previous.get('value','')
            elif q['type'] == 'multi_choice':
                field = forms.MultipleChoiceField(required=False,choices=[(o['code'],o['label']) for o in opts],widget=forms.CheckboxSelectMultiple(attrs={"class":"answer-options"}))
                initial = previous.get('value',[])
            else:
                choices = [] if quantitative else [('', 'ข้าม / Skip')]
                choices += [('value:'+str(o['value']) if o['status']=='answered' else 'state:'+o['status'],o['label']) for o in opts]
                if q['id'].startswith(('F06-M','F06-T')):
                    choices.append(('state:not_applicable','ไม่เกี่ยวข้องกับหน้าที่หรือไม่มีโอกาสปฏิบัติ / Not applicable to my duties or no opportunity'))
                if not quantitative and '-K' not in q['id']:
                    choices.append(('state:unable_to_assess','ยังประเมินไม่ได้ / Unable to assess'))
                field = forms.ChoiceField(required=False,choices=choices,widget=forms.RadioSelect(attrs={"class":"answer-options"}))
                initial = 'value:'+str(previous['value']) if previous.get('status')=='answered' else ('state:'+previous['status'] if previous.get('status') in {'not_applicable','unable_to_assess'} else '')
            if quantitative:
                field.required=self.is_bound and self.data.get('action')=='submit'
                field.error_messages['required']='กรุณาตอบข้อนี้ก่อนส่ง / Complete this item before submitting.'
                if q['id']=='F05-Y01':field.help_text='รวมชั่วโมงอบรมทุกเรื่องในปีงบประมาณ นับชั่วโมงเดียวกันครั้งเดียว ไม่ได้อบรมให้กรอก 0 เช่น 6 ชั่วโมง 30 นาที = 6.50 / Include all training topics; count each hour once. Enter 0 if none.'
            field.label = q['id']+' · '+q['text']
            field.initial = initial
            if q['id']=='F03-G08':field.help_text='เลือกได้ไม่เกิน 3 ข้อ และ “ไม่มี” เลือกเดี่ยว / Up to 3; select “none” on its own.'
            self.fields[q['id']] = field
            if q['id'].startswith(('F06-M','F06-T')):
                self.fields[q['id']+'-reason']=forms.CharField(label='เหตุผลเมื่อเลือกไม่เกี่ยวข้อง (ไม่ระบุชื่อหรืองานเฉพาะที่บอกตัวตน) / Reason if not applicable; avoid identifying details',required=False,max_length=1000,initial=previous.get('reason',''),widget=forms.Textarea(attrs={'rows':2}))
            if q['id']=='F02-P04':
                self.fields['F02-P04-month'] = forms.CharField(label='เดือนที่ติดต่อหรือใช้บริการครั้งล่าสุด (ค.ศ.) / Month of last contact or service',required=False,max_length=7,initial=previous.get('month',''),widget=forms.TextInput(attrs={'type':'month'}))
