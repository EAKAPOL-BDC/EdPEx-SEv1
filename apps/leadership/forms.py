from datetime import timedelta
from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone
from apps.catalog.models import TranslationBundle
from apps.rounds.web_forms import ActionForm
from .models import Person, Programme, Position, AnnualPlan, AnnualTarget, ROLES, fiscal_window

DATE = {'widget':forms.DateInput(attrs={'type':'date'},format='%Y-%m-%d'), 'input_formats':['%Y-%m-%d','%d/%m/%Y']}


class YearForm(forms.Form):
    fiscal_year = forms.IntegerField(label='ปีงบประมาณ พ.ศ. / Fiscal year (B.E.)',min_value=2565,max_value=3000)
    confirm = forms.BooleanField(label='ยืนยันใช้ปีงบประมาณ 1 ต.ค. ถึง 30 ก.ย. / Confirm October-September fiscal year')


class ReasonForm(forms.Form):
    reason = forms.CharField(label='เหตุผลแก้ไข / Change reason', required=False, max_length=2000)


class PersonForm(ReasonForm):
    code = forms.CharField(label='รหัสบุคลากรคงที่ / Stable staff code',max_length=80)
    name_th = forms.CharField(label='ชื่อ-สกุลภาษาไทย / Thai name',max_length=240)
    name_en = forms.CharField(label='ชื่อ-สกุลภาษาอังกฤษ / English name',max_length=240)
    user = forms.ModelChoiceField(label='บัญชีเว็บของบุคคลนี้ (ถ้ามี) / Web account, if any',required=False,queryset=get_user_model().objects.none())
    def __init__(self,*args,scope,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['user'].queryset=get_user_model().objects.filter(membership__organization=scope.organization).distinct()


class ProgrammeForm(ReasonForm):
    code=forms.CharField(label='รหัสหลักสูตร / Programme code',max_length=80)
    name_th=forms.CharField(label='ชื่อหลักสูตรภาษาไทย / Thai programme name',max_length=300)
    name_en=forms.CharField(label='ชื่อหลักสูตรภาษาอังกฤษ / English programme name',max_length=300)
    def __init__(self,*args,scope,**kwargs):super().__init__(*args,**kwargs)


class PositionForm(ReasonForm):
    code=forms.CharField(label='รหัสตำแหน่งเฉพาะ เช่น VD-001 / Position code',max_length=80)
    role=forms.ChoiceField(label='ประเภทตำแหน่ง / Role',choices=ROLES)
    title_th=forms.CharField(label='ชื่อตำแหน่งตั้งต้นภาษาไทย / Default Thai title',max_length=300)
    title_en=forms.CharField(label='ชื่อตำแหน่งตั้งต้นภาษาอังกฤษ / Default English title',max_length=300)
    programme=forms.ModelChoiceField(label='หลักสูตร (เฉพาะประธานหลักสูตร) / Programme for PC',required=False,queryset=Programme.objects.none())
    def __init__(self,*args,scope,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['programme'].queryset=Programme.objects.filter(scope=scope).order_by('code')


class TargetForm(ReasonForm):
    person=forms.ModelChoiceField(label='ผู้ถูกประเมิน / Evaluatee',queryset=Person.objects.none())
    position=forms.ModelChoiceField(label='ตำแหน่ง / Position',queryset=Position.objects.none())
    title_th=forms.CharField(label='ชื่อตำแหน่งที่ใช้ในช่วงนี้ ภาษาไทย / Thai title for this segment',required=False,max_length=300,help_text='เว้นว่างเพื่อใช้ชื่อจากทะเบียนตำแหน่ง / Leave blank to use the position title.')
    title_en=forms.CharField(label='ชื่อตำแหน่งที่ใช้ในช่วงนี้ ภาษาอังกฤษ / English title for this segment',required=False,max_length=300)
    responsibility_th=forms.CharField(label='ภารกิจที่ประเมิน ภาษาไทย / Thai responsibilities',max_length=2000,widget=forms.Textarea(attrs={'rows':3}))
    responsibility_en=forms.CharField(label='ภารกิจที่ประเมิน ภาษาอังกฤษ / English responsibilities',max_length=2000,widget=forms.Textarea(attrs={'rows':3}))
    start_date=forms.DateField(label='วันแรกของช่วงผลงาน (ค.ศ.) / First assessed date',**DATE)
    last_date=forms.DateField(label='วันสุดท้ายของช่วงผลงาน รวมวันนี้ (ค.ศ.) / Last assessed date, inclusive',**DATE)
    appointment_kind=forms.ChoiceField(label='สถานะการดำรงตำแหน่ง / Appointment type',choices=[('substantive','ดำรงตำแหน่ง / Substantive'),('acting','รักษาการ / Acting')])
    source_reference=forms.CharField(label='คำสั่งแต่งตั้ง/แหล่งยืนยันช่วงเวลา / Appointment reference',max_length=1000)
    eligibility_basis=forms.CharField(label='ใครเกี่ยวข้องและมีสิทธิ์ประเมินรายการนี้ / Eligibility basis for this target',max_length=2000,widget=forms.Textarea(attrs={'rows':3}))
    def __init__(self,*args,scope,**kwargs):
        super().__init__(*args,**kwargs)
        from django.conf import settings
        if getattr(settings, 'NEXORA_PUBLIC_ASSESSMENTS_ENABLED', False):
            self.fields['eligibility_basis'].label='หลักเกณฑ์ผู้ตอบ · ST1 และ ST2 ทุกคน / Respondent basis · all ST1 and ST2'
            self.fields['eligibility_basis'].help_text='ทั้งสองกลุ่มประเมินผู้บริหารทุกคนทุกตำแหน่ง ไม่ต้องระบุชื่อผู้ตอบ / Both staff groups assess every leader and position; do not list respondents.'
            if not self.initial.get('eligibility_basis'):
                self.fields['eligibility_basis'].initial='บุคลากรสายวิชาการ ST1 และสายสนับสนุน ST2 ทุกคน ประเมินผู้บริหารทุกคนทุกตำแหน่ง'
        self.fields['person'].queryset=Person.objects.filter(scope=scope).order_by('code')
        self.fields['position'].queryset=Position.objects.filter(scope=scope).order_by('code')
    def clean(self):
        d=super().clean()
        if d.get('position'):
            d['title_th']=d.get('title_th') or d['position'].title_th
            d['title_en']=d.get('title_en') or d['position'].title_en
        if d.get('last_date'):
            d['end_date']=d['last_date']+timedelta(days=1)
        return d


class EligibilityForm(forms.Form):
    people=forms.ModelMultipleChoiceField(label='รายชื่อผู้ตอบแบบเดิม (ไม่ใช่ผู้ถูกประเมิน) / Legacy respondents (not evaluatees)',queryset=Person.objects.none(),widget=forms.CheckboxSelectMultiple)
    group_code=forms.ChoiceField(label='กลุ่มประจำตัวของผู้ตอบที่เลือก / Selected respondents’ own group',choices=[('ST1','ST1 สายวิชาการ / Academic'),('ST2','ST2 สายสนับสนุน / Support')])
    relationship=forms.CharField(label='ความเกี่ยวข้องกับตำแหน่ง/หลักสูตรนี้ / Relationship to this position or programme',max_length=500,widget=forms.Textarea(attrs={'rows':3}))
    def __init__(self,*args,target,scope,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['people'].queryset=Person.objects.filter(scope=scope).exclude(pk__in=target.eligibility.values('person_id')).order_by('code')


class CollectionForm(forms.Form):
    targets=forms.ModelMultipleChoiceField(label='รายการผู้ถูกประเมินที่ตรึงแล้ว / Frozen assessment targets',queryset=AnnualTarget.objects.none(),widget=forms.CheckboxSelectMultiple)
    bundle=forms.ModelChoiceField(label='F04 และคำแปลที่เผยแพร่แล้ว / Published F04 wording',queryset=TranslationBundle.objects.none())
    owner=forms.ModelChoiceField(label='ผู้รับผิดชอบรอบ / Collection owner',queryset=get_user_model().objects.none())
    open_at=forms.DateTimeField(label='เปิดรับคำตอบ / Opens',widget=forms.DateTimeInput(attrs={'type':'datetime-local'},format='%Y-%m-%dT%H:%M'))
    due_at=forms.DateTimeField(label='กำหนดส่ง / Due',widget=forms.DateTimeInput(attrs={'type':'datetime-local'},format='%Y-%m-%dT%H:%M'))
    close_at=forms.DateTimeField(label='ปิดรับคำตอบ / Closes',widget=forms.DateTimeInput(attrs={'type':'datetime-local'},format='%Y-%m-%dT%H:%M'))
    privacy_notice=forms.CharField(label='คำชี้แจงการใช้ข้อมูล / Data-use notice',max_length=15000,widget=forms.Textarea(attrs={'rows':4}))
    confirm=forms.BooleanField(label='ตรวจรายชื่อ ช่วงเวลา และผู้เกี่ยวข้องแล้ว / I checked targets, dates and eligibility')
    def __init__(self,*args,scope,plan,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['targets'].queryset=plan.targets.filter(status='ready').select_related('person','position').order_by('position__code','start_date')
        self.fields['bundle'].queryset=TranslationBundle.objects.exclude(pk__in=TranslationBundle.objects.filter(instrument_version__source_metadata__synthetic_only=True)).filter(status='published',instrument_version__status='published',instrument_version__instrument__code='F04',instrument_version__instrument__scope=scope)
        self.fields['bundle'].label_from_instance=lambda b: 'F04 · '+b.instrument_version.version+' · '+b.bundle_version
        self.fields['owner'].queryset=get_user_model().objects.filter(is_active=True,membership__organization=scope.organization,membership__is_active=True).distinct()
    def clean(self):
        d=super().clean()
        if all(d.get(x) for x in ['open_at','due_at','close_at']):
            if not d['open_at']<=d['due_at']<=d['close_at'] or d['open_at']==d['close_at']:
                raise forms.ValidationError('ตรวจลำดับเปิดรับ กำหนดส่ง และปิดรับ / Check collection dates.')
        return d


class SplitForm(ActionForm):
    change_date=forms.DateField(label='วันแรกของคนใหม่/ชื่อใหม่ (ค.ศ.) / Effective change date',**DATE)
    new_person=forms.ModelChoiceField(label='ผู้ดำรงตำแหน่งหลังวันเปลี่ยน / Person after change',queryset=Person.objects.none())
    title_th=forms.CharField(label='ชื่อตำแหน่งหลังวันเปลี่ยน ภาษาไทย / New Thai title',max_length=300)
    title_en=forms.CharField(label='ชื่อตำแหน่งหลังวันเปลี่ยน ภาษาอังกฤษ / New English title',max_length=300)
    def __init__(self,*args,scope,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['new_person'].queryset=Person.objects.filter(scope=scope).order_by('code')


class CopyForm(ActionForm):
    source=forms.ModelChoiceField(label='ทะเบียนปีก่อน / Previous fiscal year',queryset=AnnualPlan.objects.none())
    def __init__(self,*args,plan,scope,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['source'].queryset=AnnualPlan.objects.filter(scope=scope,fiscal_year=plan.fiscal_year-1)
