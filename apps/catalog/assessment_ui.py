"""Presentation only. The stored questionnaire and server validation are unchanged."""
import re
from collections import OrderedDict

TITLES = {
    'P': ('ข้อมูลประกอบการประเมิน', 'About this assessment'),
    'S': ('ความพึงพอใจ', 'Satisfaction'),
    'D': ('ประสบการณ์และสิ่งที่ต้องการปรับปรุง', 'Experience and improvements'),
    'E': ('ความผูกพัน', 'Engagement'),
    'G': ('ปัจจัยในการทำงาน', 'Work experience'),
    'H': ('ความสุขในการทำงาน', 'Happiness at work'),
    'R': ('การแนะนำและบอกต่อ', 'Recommendation'),
    'C': ('การสื่อสาร', 'Communication'),
    'K': ('ความเข้าใจเกี่ยวกับองค์กร', 'Understanding the organization'),
    'O': ('ข้อเสนอแนะ', 'Suggestions'),
    'DE': ('การบริหารของคณบดี', 'Dean'),
    'BO': ('การกำกับดูแลของคณะกรรมการ', 'Board'),
    'VD': ('การบริหารของรองคณบดี', 'Vice dean'),
    'AS': ('การปฏิบัติงานของผู้ช่วยคณบดี', 'Assistant dean'),
    'PC': ('การบริหารหลักสูตร', 'Program chair'),
    'ET': ('ความเชื่อมั่นและจริยธรรม', 'Trust and ethics'),
}
FORM_TITLES = {
    'F05': {'Y':('การอบรมและศึกษาดูงานในปีงบประมาณ','Training and study visits during the fiscal year'),'A':('ข้อมูลกิจกรรม','Activity details'),'P':('ผู้เข้าร่วม','Participants'),
            'F':('การติดตามผล','Follow-up'),'V':('การตรวจรับ','Verification')},
    'F06': {'A':('สมรรถนะหลัก','Core competencies'),'M':('ความสามารถในการทำงานตามพันธกิจ','Capabilities supporting institutional missions'),
            'T':('ความสามารถในการทำงานตามกลยุทธ์','Capabilities supporting institutional strategies'),'D':('ทักษะดิจิทัล','Digital skills'),
            'K':('วิสัยทัศน์และค่านิยม','Vision and values'),'V':('พฤติกรรมตามค่านิยม','Values in practice')},
}


def sections(form, *, english=False, notes=None):
    groups = OrderedDict()
    notes = notes or {}
    for field in form.visible_fields():
        qid = field.name
        parts = qid.split('-')
        if len(parts)<2: continue
        key = re.match(r'[A-Z]+', parts[1]).group()
        titles = FORM_TITLES.get(parts[0], {})
        label = titles.get(key, TITLES.get(key, ('รายการเพิ่มเติม','Additional items')))[int(english)]
        groups.setdefault(key, {'key':key, 'title':label, 'number':len(groups)+1,'items':[]})['items'].append({
            'id':qid,'label':str(field.label).removeprefix(qid+' · '),'field':field,'note':notes.get(qid,'')})
    return list(groups.values())
