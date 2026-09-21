"""Current collection policy. Historical labels and results are never rewritten."""
from datetime import date
from django.core.exceptions import ValidationError
BASES={'F01':'academic',**{f'F{i:02}':'fiscal' for i in range(2,7)}}
LABELS={'academic':'ปีการศึกษา / Academic year','fiscal':'ปีงบประมาณ / Fiscal year'}

def validate_period(code, period):
    required=BASES.get(code)
    if not required:return
    if period.calendar.calendar_type!=required:
        raise ValidationError(f'{code} ต้องใช้ {LABELS[required]} กรุณาสร้างรอบใหม่โดยเลือกปีให้ตรงแบบฟอร์ม / Select the required reporting-year type.')
    if required=='fiscal':
        p=period.parent if period.parent_id else period
        y=p.reporting_year_be
        if (p.start_date,p.end_date)!=(date(y-544,10,1),date(y-543,10,1)):
            raise ValidationError('ปีงบประมาณเริ่ม 1 ต.ค. และสิ้นสุด 30 ก.ย. ส่วนวันเปิด–ปิดรับคำตอบกำหนดแยกได้ / Use the October–September fiscal year.')

def validate_current_round(r):
    for binding in r.round_instruments.select_related('instrument_version__instrument'):
        code=binding.instrument_version.instrument.code
        validate_period(code,r.period)
        if code in {'F05','F06'} and not hasattr(binding,'survey_profile'):
            raise ValidationError('รอบเดิมเก็บข้อมูลรายบุคคล ให้สร้างรอบแบบไม่ระบุตัวตนใหม่ ข้อมูลเดิมยังเปิดดูได้ / Create an anonymous collection; the old identified collection remains historical.')
