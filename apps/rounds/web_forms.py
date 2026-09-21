from django import forms
from apps.catalog.group_registry import group_display
from django.contrib.auth import get_user_model
from .models import ReportingPeriod, Calendar, RespondentGroup
from apps.catalog.models import TranslationBundle


class PeriodForm(forms.Form):
    return_to = forms.ChoiceField(required=False, widget=forms.HiddenInput,
        choices=[('', 'Round setup'), ('survey', 'F01–F04'), ('f06', 'F06')])
    code = forms.CharField(label='ชื่อช่วงรายงาน / Reporting period', max_length=80)
    calendar_type = forms.ChoiceField(label='ประเภทปี / Calendar type', choices=[('academic','ปีการศึกษา / Academic year'),('fiscal','ปีงบประมาณ / Fiscal year')])
    reporting_year_be = forms.IntegerField(label='ปีรายงาน พ.ศ. / Reporting year (B.E.)', min_value=2565)
    start_date = forms.DateField(label='วันแรก (ค.ศ.) / First day', widget=forms.DateInput(attrs={'type': 'date'}))
    last_date = forms.DateField(label='วันสุดท้าย (รวมวันนี้, ค.ศ.) / Last day (inclusive)', widget=forms.DateInput(attrs={'type': 'date'}))
    reason = forms.CharField(label='ที่มาของช่วงวันที่ / Basis for these dates', max_length=1000)
    confirm = forms.BooleanField(label='ตรวจวันเริ่มและวันสิ้นสุดกับปฏิทินของหน่วยงานแล้ว / I checked the dates against our reporting calendar')

    def clean(self):
        data = super().clean()
        if data.get('start_date') and data.get('last_date') and data['start_date'] > data['last_date']:
            self.add_error('last_date', 'วันสุดท้ายต้องไม่ก่อนวันแรก / End must not precede start.')
        if data.get('calendar_type')=='fiscal' and data.get('reporting_year_be'):
            from datetime import date
            y=data['reporting_year_be']
            if (data.get('start_date'),data.get('last_date')) != (date(y-544,10,1),date(y-543,9,30)):
                self.add_error('last_date','ปีงบประมาณนี้ต้องเริ่ม 1 ต.ค. ปีก่อน และสิ้นสุด 30 ก.ย. ของปีที่ระบุ / Fiscal years run October–September.')
        return data


class RoundForm(forms.Form):
    code = forms.CharField(label='ชื่อรอบ / Round name', max_length=80)
    period = forms.ModelChoiceField(label='ช่วงรายงานที่รับรองแล้ว / Approved reporting period', queryset=ReportingPeriod.objects.none())
    owner = forms.ModelChoiceField(label='ผู้รับผิดชอบรอบ / Round owner', queryset=get_user_model().objects.none())
    bundle = forms.ModelChoiceField(label='F06 และชุดคำแปลที่เผยแพร่แล้ว / Published F06 and translations', queryset=TranslationBundle.objects.none())
    open_at = forms.DateTimeField(label='เปิดรับคำตอบ / Opens', widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}))
    due_at = forms.DateTimeField(label='กำหนดส่ง / Due', widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}))
    close_at = forms.DateTimeField(label='ปิดรับคำตอบ (ไม่รวมเวลานี้) / Closes (exclusive)', widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}))
    privacy_notice = forms.CharField(label='คำชี้แจงการใช้ข้อมูลของรอบ / Round data-use notice', max_length=15000,
        widget=forms.Textarea(attrs={'rows': 5}), help_text='ระบุวัตถุประสงค์ ผู้เข้าถึง ระยะเก็บ และช่องทางติดต่อให้ตรงกับการใช้งาน / State purpose, access, retention and contact details.')
    reason = forms.CharField(label='เหตุผลแก้ไข / Change reason', required=False, max_length=1000)

    def __init__(self, *args, scope, editing=False, instrument_code="F06", **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['period'].queryset = ReportingPeriod.objects.filter(calendar__scope=scope, approved=True).order_by('-reporting_year_be', 'code')
        self.fields['period'].label_from_instance = lambda p: f'{p.code} · {p.calendar.get_calendar_type_display()} · พ.ศ. {p.reporting_year_be}'
        self.fields['period'].help_text = 'F01 ใช้ปีการศึกษา; F02–F06 ใช้ปีงบประมาณ วันรับคำตอบกำหนดแยกจากปีรายงานได้ / Reporting year and collection dates are separate.'
        self.fields['owner'].queryset = get_user_model().objects.filter(is_active=True, membership__organization=scope.organization, membership__is_active=True).distinct().order_by('username')
        self.fields['owner'].label_from_instance = lambda u: u.get_username()
        self.fields['bundle'].queryset = TranslationBundle.objects.filter(status='published', instrument_version__status='published', instrument_version__instrument__scope=scope, instrument_version__instrument__code=instrument_code).select_related('instrument_version').order_by('-created_at')
        self.fields['bundle'].label_from_instance = lambda b: f'{instrument_code} · {b.instrument_version.version} · {b.bundle_version}'
        self.fields['bundle'].label = instrument_code+' และชุดคำแปลที่เผยแพร่ / Published instrument and translations'
        if editing:
            self.fields['period'].disabled = self.fields['bundle'].disabled = True
            self.fields['reason'].required = True


class PopulationForm(forms.Form):
    definition = forms.CharField(label='ใครบ้างที่มีสิทธิ์ตอบ / Eligible population definition', max_length=6000, widget=forms.Textarea(attrs={'rows': 3}))
    st1 = forms.IntegerField(label='จำนวนสายวิชาการ ST1 ที่มีสิทธิ์ / Eligible academic staff', min_value=0)
    st2 = forms.IntegerField(label='จำนวนสายสนับสนุน ST2 ที่มีสิทธิ์ / Eligible support staff', min_value=0)
    source_title = forms.CharField(label='ชื่อทะเบียนหรือเอกสารอ้างอิง / Roster source title', max_length=500)
    source_location = forms.CharField(label='ที่เก็บหรือเลขอ้างอิงทะเบียน / Source location or reference', max_length=3000,
        help_text='ใช้อ้างอิงที่มีอยู่จริง ไม่ต้องใส่รหัสผ่านหรือลิงก์ที่มีรหัสลับ / Use an actual reference without passwords or secret links.')
    captured_at = forms.DateTimeField(label='ข้อมูลรายชื่อ ณ วันเวลา / Roster as of', widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}))
    reason = forms.CharField(label='เหตุผลแก้ไข / Change reason', required=False, max_length=1000)

    def clean(self):
        data = super().clean()
        if data.get('st1') == 0 and data.get('st2') == 0:
            raise forms.ValidationError('ต้องมีผู้มีสิทธิ์อย่างน้อยหนึ่งคน / At least one eligible person is required.')
        return data


class MemberForm(forms.Form):
    eligible_unit_key = forms.CharField(label='รหัสบุคลากร / Staff ID', max_length=160)
    group = forms.ModelChoiceField(label='กลุ่มผู้ตอบ / Respondent group', queryset=RespondentGroup.objects.none())
    reason = forms.CharField(label='เหตุผลแก้ไข / Change reason', required=False, max_length=1000)

    def __init__(self, *args, scope, editing=False, groups=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['eligible_unit_key'].label = 'รหัสหน่วยผู้มีสิทธิ์ / Eligible unit ID'
        self.fields['group'].queryset = RespondentGroup.objects.filter(scope=scope, code__in=groups or ['ST1', 'ST2'], active=True).order_by('code')
        self.fields['group'].label_from_instance = lambda g: group_display(g.code, g.label)
        self.fields['reason'].required = editing


class ActionForm(forms.Form):
    reason = forms.CharField(label='เหตุผล / Reason', max_length=1000, widget=forms.Textarea(attrs={'rows': 3}))
    confirm = forms.BooleanField(label='ตรวจข้อมูลและยืนยันดำเนินการ / I reviewed the data and confirm this action')
