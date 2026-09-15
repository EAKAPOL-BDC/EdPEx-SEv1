"""Build the offline M0 catalog from the unchanged supplied sources. No Django/DB."""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/source'
OUT = ROOT / 'catalog'
INAME = 'EdPEx_6_Instruments.md'
BNAME = 'EdPEx_System_Blueprint_v1.md'
I = (SOURCE / INAME).read_text(encoding='utf-8')
B = (SOURCE / BNAME).read_text(encoding='utf-8')
IL = I.splitlines()

def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def ref(line, document=INAME):
    return {'path': 'docs/source/' + document, 'line': line}

def locate(text):
    return next(n for n, line in enumerate(IL, 1) if text in line)

def block(text):
    start = I.index(text)
    end = I.find('\n\n', start)
    return I[start:end if end >= 0 else len(I)]

GROUPS = {
 'C1': 'ปริญญาตรี', 'C2.1': 'บัณฑิตศึกษาชาวไทย', 'C2.2': 'บัณฑิตศึกษาชาวต่างชาติ',
 'C3.1': 'ผู้เรียน Non-degree', 'C4.1': 'ผู้ให้ทุนวิจัยภาครัฐ', 'C5.1': 'ผู้รับบริการภาครัฐ',
 'C5.2': 'บุคคลทั่วไปหรือครู', 'C5.3': 'ชุมชน', 'S1': 'ผู้ปกครอง',
 'S3-1': 'ศิษย์เก่าปริญญาตรี', 'S3-2': 'ศิษย์เก่าบัณฑิตศึกษา', 'CO-1': 'คณะร่วมผลิต',
 'CO-2': 'คู่ความร่วมมือในประเทศมี MOU', 'CO-3': 'คู่ความร่วมมือต่างประเทศมี MOU',
 'CO-4': 'แหล่งฝึกปี 1–3 และเครือข่ายตามโครงร่าง', 'ST1': 'สายวิชาการ', 'ST2': 'สายสนับสนุน'}
LEARNERS = ['C1','C2.1','C2.2','C3.1']
CUSTOMERS = ['C4.1','C5.1','C5.2','C5.3']
PARTNERS = ['S1','S3-1','S3-2','CO-1','CO-2','CO-3','CO-4']
STAFF = ['ST1','ST2']
FG = {'F01':LEARNERS, 'F02':CUSTOMERS+PARTNERS, 'F03':STAFF, 'F04':STAFF, 'F05':STAFF, 'F06':STAFF}

questions = {}
def add(qid, text, line, details='', answer_type='text', scale=None, groups=None, required=False, visibility=None):
    assert qid not in questions, qid
    questions[qid] = {'question_id':qid, 'instrument_id':qid[:3], 'instrument_version':'1.1',
      'text':{'th':text,'en':None}, 'translation_status':{'th':'source','en':'missing'},
      'answer_type':answer_type, 'scale_id':scale, 'options':[],
      'group_codes':groups if groups is not None else FG[qid[:3]], 'required':required,
      'visibility_condition':visibility or {'op':'in_group'},
      'source':ref(line), 'source_details_th':details, 'source_indicator_codes':[],
      'blueprint_requirements':[2,6,7,9,10,25,33]}

# Table text is retained verbatim, including guidance and conditional text.
for n, line in enumerate(IL, 1):
    cells = [c.strip() for c in line.strip().strip('|').split('|')]
    if not line.startswith('|'):
        continue
    qcell = next((k for k,c in enumerate(cells) if re.fullmatch(r'F0[1-6]-[A-Z]+\d*',c)), None)
    if qcell is None:
        continue
    qid = cells[qcell]
    details = ' | '.join(cells[qcell+2:])
    if qcell:
        details = cells[0] + ' | ' + details
    add(qid,cells[qcell+1],n,details)

# Inline fields have explicit stable IDs, including shorthand P02..P05 in F06.
inline = {
 'F03-P01':'ประเภทบุคลากร', 'F03-H01':'โดยรวมในช่วง 3 เดือนที่ผ่านมา ท่านมีความสุขในการทำงานที่วิทยาลัยฯ เพียงใด',
 'F03-G08':'เลือกไม่เกิน 3 เรื่องจากรายการข้างต้นที่มีผลต่อความต้องการทำงานกับวิทยาลัยฯ ต่อไปมากที่สุด',
 'F03-O01':'ข้อเสนอแนะสำคัญที่สุดเพื่อพัฒนาการทำงานของวิทยาลัยฯ',
 'F04-P01':'ประเภทผู้ตอบ', 'F04-P02':'ผู้ถูกประเมิน', 'F04-P03':'ท่านมีข้อมูลเพียงพอที่จะประเมินหรือไม่',
 'F04-O01':'สิ่งที่ผู้ถูกประเมินทำได้ดี', 'F04-O02':'สิ่งที่ควรปรับปรุง',
 'F05-F01':'นำความรู้ไปใช้แล้วหรือยัง', 'F05-F02':'ใช้กับงานใด',
 'F05-F03':'เกิดผลเปลี่ยนแปลงอะไรหรือมีอุปสรรคใด', 'F05-F04':'หลักฐานผลการใช้ถ้ามี',
 'F06-P01':'รหัสบุคลากร', 'F06-P02':'ST1/ST2', 'F06-P03':'รอบ', 'F06-P04':'หน้าที่รับผิดชอบ',
 'F06-P05':'วันที่ประเมินตนเอง',
 'F06-K00':'ก่อนตอบแบบนี้ ท่านเคยได้รับการสื่อสารเกี่ยวกับวิสัยทัศน์หรือค่านิยมของวิทยาลัยฯ หรือไม่'}
for qid, text in inline.items():
    marker = 'ก่อนเริ่ม: F06-P01' if qid.startswith('F06-P') else qid
    line = locate(marker)
    add(qid,text,line,IL[line-1])

# External knowledge questions share content, but never IDs or F06 answer keys.
kstart = locate('# ชุด K สำหรับผู้ตอบ:')
klines = IL[kstart:]
for number in range(7):
    pos = next(k for k,l in enumerate(klines) if l.startswith(f'K{number:02} '))
    raw = klines[pos]
    opts = []
    if number:
        for line in klines[pos+1:]:
            if line.startswith('K') or line.startswith('#'):
                break
            m = re.match(r'- ([ABCDU]) (.*)',line)
            if m:
                opts.append({'code':m[1], 'label':{'th':m[2],'en':None}})
    else:
        opts = [{'code':c,'label':{'th':t,'en':None}} for c,t in [('seen','เคย'),('not_seen','ไม่เคย'),('cannot_recall','จำไม่ได้')]]
    for form in ['F01','F02']:
        qid = f'{form}-K{number:02}'
        add(qid,raw[4:],kstart+pos+1,raw,'single_choice')
        questions[qid]['options'] = opts

# Source-defined repeated optional questions; expansion is explicit, not a new measure.
for form, count in [('F01',5),('F03',2)]:
    marker = 'เมื่อข้อใดตอบ Y' if form=='F01' else 'เมื่อ D01 หรือ D02=Y'
    line = locate(marker)
    choices = ('เข้าถึงยาก/ล่าช้า/ข้อมูลไม่ชัดเจน/คุณภาพไม่ตรงความต้องการ/การปฏิบัติไม่เหมาะสม/สิ่งอำนวยความสะดวก/อื่น ๆ'
        if form=='F01' else 'การเข้าถึงโอกาส/ขั้นตอนล่าช้า/ข้อมูลไม่ชัดเจน/ความเป็นธรรม/ไม่ตรงความต้องการ/การสนับสนุนไม่เพียงพอ/อื่น ๆ')
    for num in range(1,count+1):
        parent=f'{form}-D{num:02}'
        for suffix,text,kind in [('CAUSE','ปัญหาหลักคืออะไร','multi_choice'),('FIX','ต้องการให้ปรับปรุงอย่างไร','text')]:
            qid=parent+'-'+suffix
            add(qid,text,line,IL[line-1],kind,visibility={'op':'eq','question_id':parent,'value':'Y'})
            if suffix=='CAUSE':
                questions[qid]['options']=[{'code':f'cause_{i}', 'label':{'th':t,'en':None}} for i,t in enumerate(choices.split('/'),1)]
            else:
                questions[qid]['max_length']=500
            questions[qid]['derived_from_source_template']=True
for suffix in ['S','E','U','P']:
    qid='F06-V'+suffix+'-EX'
    marker='ต่อท้ายแต่ละข้อเพิ่ม -EX'
    add(qid,'หากต้องการ โปรดยกตัวอย่างการนำค่านิยมไปใช้หนึ่งกรณี',locate(marker),block(marker))
    questions[qid]['derived_from_source_template']=True

scales = {}
for n,line in enumerate(IL[:locate('# F01 แบบสำรวจ')-1],1):
    m=re.match(r'\| (SAT|AGR|DIS|FREQ|ADM) \| (.*?) \|$',line)
    if m:
        sid,raw=m.groups()
        opts=[]
        for item in raw.split(' / '):
            code, label=item.split(' ',1)
            opts.append({'code':code,'score':int(code) if code.isdigit() else None,'label':{'th':label,'en':None}})
        scales[sid]={'scale_id':sid,'options':opts,'source':ref(n),'source_text_th':raw}
for sid,marker in [('SELF_5','เกณฑ์คะแนน 1–5:'),('SELF_UNDERSTANDING','มาตราความเข้าใจ:')]:
    scales[sid]={'scale_id':sid,'source':ref(locate(marker)), 'source_text_th':block(marker),
        'options':[{'code':str(n),'score':n} for n in range(1,6)], 'non_score_status':'unable_to_assess'}
scales['HAPPINESS_10']={'scale_id':'HAPPINESS_10','source':ref(locate('F03-H01:')),
    'source_text_th':block('F03-H01:'),'options':[{'code':str(n),'score':n} for n in range(11)],'non_score_status':'skipped'}

for qid,q in questions.items():
    f, part=qid.split('-',1)
    scale=None
    if f in ['F01','F02','F03']:
        if re.fullmatch(r'S\d+',part) or part=='C01' or (f=='F03' and re.fullmatch(r'G0[1-7]',part)): scale='SAT'
        if re.fullmatch(r'E\d+',part) or part=='R01': scale='AGR'
        if (f=='F01' and re.fullmatch(r'D\d+',part)) or (f=='F02' and part=='D01') or (f=='F03' and part in ['D01','D02']): scale='DIS'
        if part=='H01': scale='HAPPINESS_10'
    if f=='F04' and re.fullmatch(r'(DE|BO|VD|AS|PC)\d+',part): scale='ADM'
    if f=='F04' and part.startswith('ET'): scale='AGR'
    if f=='F06':
        if re.fullmatch(r'[AMTD]\d+',part): scale='SELF_5'
        if re.fullmatch(r'K0[1-6]',part): scale='SELF_UNDERSTANDING'
        if part in ['VS','VE','VU','VP']: scale='FREQ'
        q['assessment_method']='self_report'
        q['evidence_allowed']=False
        q['reviewer_step']=False
    if scale:
        q['scale_id']=scale
        q['answer_type']='single_choice' if scale=='DIS' else 'integer_scale'
    if f=='F01':
        if re.fullmatch(r'(S0[1-8]|D0[1-4]|E0[1-3])(?:-.*)?',part): q['group_codes']=['C1','C2.1']
        if part.startswith(('S09','D05')): q['group_codes']=['C2.2','C3.1']
        if part=='P03': q['group_codes']=['C1','C2.1','C2.2']
        if part=='P04': q['group_codes']=['C3.1']
    if f=='F06' and part in ['A06','A07','A08','A09']: q['group_codes']=['ST2']
    if f=='F06' and part[:1] in ['M','T']:
        q['applicability']={'self_declared':True,'reason_required':True,'approval_required':False}
    if re.fullmatch(r'P\d+',part) and f!='F05':
        q['answer_type']='context_reference'
        q['required']=part in ['P01','P02'] or (f=='F06')
    if f=='F04' and scale:
        q['visibility_condition']={'op':'context_role_and_information','role':part[:2] if scale=='ADM' else 'DE','information':['sufficient','partial'],'invitation_locked':True}
    if f=='F02' and part in ['D02','D03']:
        q['visibility_condition']={'op':'eq','question_id':'F02-D01','value':'Y'}
        q['answer_type']='multi_choice' if part=='D02' else 'text'
    if f=='F03' and part=='G08':
        q['answer_type']='multi_choice'; q['max_selected']=3
    if f=='F05':
        q['required']='จำเป็น' in q['source_details_th']
        if part in ['A08','P03']: q['answer_type']='decimal'; q['minimum']=0
        if part=='A05': q['answer_type']='date_time_range'
        if part in ['A09','P05','F04']: q['answer_type']='evidence_reference'
        if part in ['A04','A06','P02','P04','V01','F01']: q['answer_type']='single_choice'
        if part=='A07': q['answer_type']='multi_choice'

# Configure non-scale options explicitly. These codes are implementation keys;
# Thai source wording and original baseline question IDs stay unchanged.
def options(qid, labels, kind='single_choice', codes=None):
    q=questions[qid]; q['answer_type']=kind
    q['options']=[{'code':codes[n] if codes else f'option_{n+1}', 'label':{'th':label,'en':None}} for n,label in enumerate(labels)]

for qid,gs in [('F01-P01',LEARNERS),('F02-P01',CUSTOMERS+PARTNERS),('F03-P01',STAFF),('F04-P01',STAFF),('F05-P02',STAFF),('F06-P02',STAFF)]:
    options(qid,[GROUPS[g] for g in gs],codes=gs)
options('F01-C02',['อาจารย์','เจ้าหน้าที่','เว็บไซต์','สื่อสังคม','กลุ่มสื่อสาร','กิจกรรมพบปะ','ไม่เคยได้รับ','อื่น ๆ'],'multi_choice')
questions['F01-C02']['exclusive_option_codes']=['option_7']
options('F01-P03',['ชั้นปี 1','ชั้นปี 2','ชั้นปี 3','ชั้นปี 4','ชั้นปี 5 ขึ้นไป','ช่วงรายวิชา','วิทยานิพนธ์','ทั้งสองส่วน'])
questions['F01-P03']['source_details_th']+='; ตั้งตัวเลือกชั้นปี/ช่วงการศึกษาให้ตรงหลักสูตร ไม่เปิดทุกตัวเลือกโดยไม่ตรวจบริบท'
options('F02-P03',['บุคคล','ผู้แทนหน่วยงาน','ผู้แทนชุมชน'],codes=['person','organization_representative','community_representative'])
questions['F02-P03']['system_assigned']=True
options('F02-P04',['เดือน/ปี','จำไม่ได้'],codes=['month_year','cannot_recall'])
questions['F02-P04']['optional_fields']={'last_service_month':{'type':'month_year','required_if':{'question_id':'F02-P04','value':'month_year'}}}
questions['F02-P04']['required']=False
options('F02-D02',['ความล่าช้า','ข้อมูลหรือข้อตกลงไม่ชัดเจน','คุณภาพงาน','เข้าถึงผู้ประสานงานยาก','การปฏิบัติไม่เหมาะสม','อื่น ๆ'],'multi_choice')
options('F02-C02',['อีเมล','โทรศัพท์','ผู้ประสานงาน','เว็บไซต์','สื่อสังคม','หนังสือราชการ','อื่น ๆ'])
options('F03-G08',[questions[f'F03-G{n:02}']['text']['th'] for n in range(1,8)]+['อื่น ๆ (ระบุ)','ไม่มีเรื่องใดชัดเจน'],'multi_choice',[f'G{n:02}' for n in range(1,8)]+['other','none'])
questions['F03-G08']['exclusive_option_codes']=['none']
options('F04-P03',['มี','มีบางด้าน','ไม่มี'],codes=['sufficient','partial','none'])
questions['F04-P03']['required']=True
questions['F04-P03']['terminal_option']={'code':'none','status':'unable_to_assess','score':None}
questions['F04-P02']['system_assigned']=True
options('F05-A04',['อบรม','สัมมนาเพื่อพัฒนา','ศึกษาดูงาน','อื่น ๆ'])
options('F05-A06',['ณ สถานที่','ออนไลน์','ผสมผสาน'])
options('F05-A07',['เทคโนโลยีสมัยใหม่','ทักษะดิจิทัล','ความปลอดภัย','อาชีวอนามัย','พลังงาน','ประกันคุณภาพ','อื่น ๆ'],'multi_choice',['T45','T46','T47S','T47H','T47E','T48','OTHER'])
options('F05-P04',['เข้าร่วมครบ','บางส่วน','ไม่ได้เข้าร่วม'])
options('F05-V01',['ร่าง','ส่งตรวจ','ขอแก้ไข','ตรวจรับ','ไม่รับรายการ'],codes=['draft','submitted','needs_correction','verified','rejected'])
options('F05-F01',['ใช้แล้ว','กำลังดำเนินการ','ยังไม่ได้ใช้'])
options('F06-K00',['เคย','ไม่เคย','จำไม่ได้'],codes=['seen','not_seen','cannot_recall'])
questions['F06-P05']['answer_type']='date'
questions['F06-P05']['system_assigned']=True
questions['F01-P04']['required']=True
questions['F02-D03']['max_length']=500
for qid in ['F05-A01','F05-P02','F05-V02']:
    questions[qid]['system_assigned']=True
questions['F05-A01']['answer_type']='context_reference'
questions['F05-A01']['unique']=True
questions['F05-P02']['answer_type']='context_reference'
questions['F05-P02']['reference_source']='employment_snapshot.ST_type'
questions['F05-P01']['answer_type']='context_reference'
questions['F05-P01']['reference_source']='personnel_registry.person_id'
questions['F05-V02']['answer_type']='review_metadata'
questions['F05-V02']['write_policy']='server_records_authenticated_F05_reviewer_and_time'
scale_labels={
 'SELF_5':['ยังทำงานพื้นฐานด้านนั้นไม่ได้โดยลำพังและต้องแนะนำใกล้ชิด','ทำงานพื้นฐานได้แต่ยังต้องแนะนำ','ทำได้ตามมาตรฐานด้วยตนเอง','แก้ปัญหาและปรับปรุงงานด้านนั้นได้','ถ่ายทอดหรือพัฒนาวิธีที่ผู้อื่นนำไปใช้ได้'],
 'SELF_UNDERSTANDING':['ยังไม่เข้าใจ','เข้าใจบางส่วนแต่ยังอธิบายไม่ได้','เข้าใจสาระหลักและอธิบายได้บางส่วน','เข้าใจและอธิบายสาระได้ชัดเจน','เข้าใจชัดเจนและเชื่อมโยงกับงานของตนได้']}
for sid,labels in scale_labels.items():
    for opt,label in zip(scales[sid]['options'],labels): opt['label']={'th':label,'en':None}
for opt in scales['HAPPINESS_10']['options']:
    opt['label']={'th':{'0':'ไม่มีความสุขเลย','10':'มีความสุขมากที่สุด'}.get(opt['code'],opt['code']),'en':None}
for q in questions.values():
    q['audience']='server_only' if q['question_id'] in ['F05-V01','F05-V02'] else 'respondent'
    q['answer_statuses']=['answered','skipped','not_applicable','unable_to_assess','not_shown']
    if q['scale_id']:
        q['options']=scales[q['scale_id']]['options']
    if q['instrument_id']=='F06' and q['scale_id']=='SELF_5':
        q['optional_fields']={'example':{'required':False,'affects_score':False},'development_plan':{'required':False,'affects_score':False}}
        q['expected_level_rule']='freeze_before_round'
        q['gap_formula']='max(expected_level - self_score, 0); null if self_score missing'
    if re.fullmatch(r'F01-D0[1-5]',q['question_id']):
        q['follow_up_reuse']={'field_key':'survey.same_incident_question_id','label_th':'เหตุการณ์เดียวกับข้อ...',
            'required':False,'visible_if_value':'Y','references':'other_visible_Y_questions_in_same_response',
            'reuse_fields':['CAUSE','FIX'],'reject_self_reference':True,'reject_cycles':True}

formulas=[]
in_formula=False
for n,line in enumerate(B.splitlines(),1):
    if line.startswith('## 11.'): in_formula=True
    if line.startswith('## 12.'): in_formula=False
    if in_formula:
        m=re.match(r'\| ([A-Z][A-Z0-9_]+) \| (.*?) \|$',line)
        if m:
            key,definition=m.groups()
            formulas.append({'formula_id':key,'formula_version':'1.1','definition_th':definition,
                'source':ref(n,BNAME),'blueprint_requirements':[11,12,33],
                'execution_status':'specification_only_M2_pending',
                'zero_denominator':{'status':'no_valid_data','value':None},
                'rounding':'display_only_2_decimals','missing_is_zero':False})

bindings=[]
def qrange(form,prefix,first,last): return [f'{form}-{prefix}{n:02}' for n in range(first,last+1)]
def bind(code,ids,formula,groups,**extra):
    bindings.append({'indicator_code':code,'source_question_ids':ids,'formula_id':formula,
       'formula_version':'1.1','group_codes':groups,**extra})
for n in range(1,8): bind(f'7.2-{n}',[f'F01-S{n:02}'],'SAT_TOP2',['C1','C2.1'])
for n in range(8,11): bind(f'7.2-{n}',[f'F01-D{n-7:02}'],'DIS_YES',['C1','C2.1'])
for code,qid,f,gs in [('11','S09','SAT_TOP2',['C2.2','C3.1']),('12','D05','DIS_YES',['C2.2','C3.1']),('14','S08','SAT_TOP2',['C1','C2.1']),('15','D04','DIS_YES',['C1','C2.1'])]:
    bind('7.2-'+code,['F01-'+qid],f,gs)
bind('7.2-13',['F02-S01'],'SAT_TOP2',['C5.3'],shared_source_with='7.2-17')
for code,qid,f,gs in [('17','S01','SAT_TOP2',CUSTOMERS),('18','D01','DIS_YES',CUSTOMERS),('19','S01','SAT_TOP2',PARTNERS),('20','D01','DIS_YES',PARTNERS),('34','R01','MEAN_5',PARTNERS),('35','R01','MEAN_5',CUSTOMERS)]:
    bind('7.2-'+code,['F02-'+qid],f,gs)
bind('7.2-24',qrange('F01','E',1,3),'ENG_3',['C1','C2.1'])
bind('7.2-25',['F01-R01'],'MEAN_5',['C1','C2.1'])
bind('7.2-36',['F01-R01'],'MEAN_5',['C2.2','C3.1'])
for n in range(25,29): bind(f'7.3-{n}',[f'F03-S{n-24:02}'],'SAT_TOP2',STAFF)
bind('7.3-29',['F03-D01'],'DIS_YES',STAFF)
bind('7.3-36',['F03-S05','F03-S06'],'PAIR_MEAN_TOP',STAFF)
bind('7.3-37',qrange('F03','E',1,3),'ENG_3',STAFF)
bind('7.3-38',['F03-H01'],'HAPPINESS_10',STAFF)
bind('7.3-39',qrange('F03','G',1,7),'DIMENSION_SAT',STAFF,series_dimensions=qrange('F03','G',1,7),overall=False)
bind('7.3-43',qrange('F06','D',1,5),'SELF_DIGITAL_POP',STAFF,denominator='frozen_eligible_population_including_nonrespondents')
for n,f in [(44,'TRAINING_HOURS'),(45,'TRAINING_PEOPLE'),(46,'TRAINING_PEOPLE'),(47,'SAFETY_ANY'),(48,'TRAINING_PEOPLE'),(49,'STUDY_VISIT')]:
    bind(f'7.3-{n}',['F05-A01','F05-A04','F05-A05','F05-A07','F05-A09','F05-P01','F05-P02','F05-P03','F05-P04','F05-P05','F05-V01','F05-V02'],f,STAFF,
      parameters={'accepted_only':True,'population':'frozen_eligible_staff','category':{45:['T45'],46:['T46'],47:['T47S','T47H','T47E'],48:['T48']}.get(n),
        'distinct_unit':'person_activity_session' if n==44 else 'person', 'external_visit_only':n==49},
      source_rules_th=I[I.index('## การตรวจและสูตร F05'):I.index('## ติดตามการนำไปใช้')])
bind('7.3-50',qrange('F06','A',1,5),'SELF_COMPETENCY',['ST1'],required_complete=5)
bind('7.3-51',qrange('F06','A',1,9),'SELF_COMPETENCY',['ST2'],required_complete=9)
bind('7.3-52',['F03-S07'],'SAT_TOP2',STAFF)
bind('7.3-53',['F03-D02'],'DIS_YES',STAFF)
for n,prefix in [(54,'M'),(55,'T')]: bind(f'7.3-{n}',qrange('F06',prefix,1,5),'SELF_DIMENSION',STAFF,series_dimensions=qrange('F06',prefix,1,5),overall=False)
bind('7.4-1',['F03-S08'],'SAT_TOP2',STAFF)
bind('7.4-2',['F03-S09'],'MEAN_5',STAFF)
bind('7.4-3',qrange('F06','K',1,2),'SELF_VISION',STAFF,denominator='complete_scored_pair')
bind('7.4-4',qrange('F06','K',3,6),'SELF_VALUES',STAFF,denominator='complete_scored_four')
bind('7.4-6',['F06-VS','F06-VE','F06-VU','F06-VP'],'SELF_BEHAVIOUR',STAFF,series_dimensions=['S','E','U','P','overall'],examples_affect_score=False)
for n,form,gs in [(7,'F01',LEARNERS),(9,'F02',CUSTOMERS),(11,'F02',PARTNERS)]:
    bind(f'7.4-{n}',[form+'-C01'],'SAT_TOP2',gs)
    bind(f'7.4-{n+1}',qrange(form,'K',0,6),'K_EXTERNAL',gs)
for n,prefix in [('13','DE'),('14','BO'),('18A','VD'),('18B','AS'),('18C','PC')]:
    bind('7.4-'+n,qrange('F04',prefix,1,5),'ADMIN_MEAN',STAFF,minimum_answered=4,series_dimensions=['person','role','appointment_dates','programme'],requires_configured_appointment=True)
bind('7.4-15',qrange('F04','ET',1,4),'ETHICS_TOP',STAFF,required_complete=4,role='DE')

indicators=[]
for b in bindings:
    ids=b['source_question_ids']
    for qid in ids:
        questions[qid]['source_indicator_codes'].append(b['indicator_code'])
    self_report=ids[0].startswith('F06')
    f=b['formula_id']
    unit='score_5' if f in ['MEAN_5','ADMIN_MEAN','SELF_COMPETENCY','SELF_DIMENSION'] else 'score_10' if f=='HAPPINESS_10' else 'hours_per_person' if f=='TRAINING_HOURS' else 'percent'
    indicators.append({'code':b['indicator_code'],'original_name':None,
        'original_name_status':'awaiting_original_indicator_PDF_not_supplied',
        'display_name':{'th':' / '.join(questions[q]['text']['th'] for q in ids) if not ids[0].startswith('F05') else f,'en':None},
        'display_name_status':'derived_from_instrument_not_official_PDF_title',
        'unit':unit,'direction':'decrease' if f=='DIS_YES' else 'increase',
        'assessment_method':'self_report' if self_report else 'verified_activity' if ids[0].startswith('F05') else 'survey',
        'instrument_version':'1.1','owner':None,'target':None,'comparator':None,
        'binding':b,'blueprint_requirements':[1,2,6,10,11,12,13,17,24,25,26,28,31,33]})

review_labels={
 '7.3-43':'ร้อยละของบุคลากรที่ประเมินตนเองว่ามีทักษะด้านดิจิทัลและสารสนเทศตามเกณฑ์ที่กำหนด',
 '7.3-44':'ชั่วโมงอบรมจริงที่ตรวจรับเฉลี่ยต่อประชากรบุคลากรทั้งหมด',
 '7.3-45':'ร้อยละบุคลากรที่อบรมด้านเทคโนโลยีสมัยใหม่',
 '7.3-46':'ร้อยละบุคลากรที่อบรมด้านทักษะดิจิทัล',
 '7.3-47':'ร้อยละบุคลากรที่อบรมด้านความปลอดภัย อาชีวอนามัย หรือพลังงาน อย่างน้อยหนึ่งด้าน',
 '7.3-48':'ร้อยละบุคลากรที่อบรมด้านประกันคุณภาพ',
 '7.3-49':'ร้อยละบุคลากรที่ศึกษาดูงานหน่วยงานภายนอกจากรายการตรวจรับ',
 '7.3-50':'คะแนนสมรรถนะจากการประเมินตนเองของบุคลากรสายวิชาการ',
 '7.3-51':'คะแนนสมรรถนะจากการประเมินตนเองของบุคลากรสายสนับสนุน',
 '7.3-54':'คะแนนสมรรถนะจากการประเมินตนเองแยกพันธกิจ',
 '7.3-55':'คะแนนสมรรถนะจากการประเมินตนเองแยก SO',
 '7.4-3':'ร้อยละของผู้ตอบที่ประเมินตนเองว่ามีความเข้าใจวิสัยทัศน์ตามเกณฑ์',
 '7.4-4':'ร้อยละของผู้ตอบที่ประเมินตนเองว่ามีความเข้าใจค่านิยมตามเกณฑ์',
 '7.4-6':'ร้อยละของผู้ตอบที่ประเมินตนเองว่าปฏิบัติตามค่านิยม SEUP ตามเกณฑ์'}
for i in indicators:
    if i['code'] in review_labels: i['display_name']['th']=review_labels[i['code']]

# Full source sections preserve instructions, choices, rubrics and ancillary fields
# that do not have source question IDs. Never invent baseline question IDs for them.
sections=[]
heads=list(re.finditer(r'^#{1,3} .+$',I,re.M))
audience='configuration_only'
admin_manual=False
for idx,m in enumerate(heads):
    end=heads[idx+1].start() if idx+1<len(heads) else len(I)
    heading=m.group()
    if heading.startswith('# F') or heading.startswith('# ชุด K สำหรับผู้ตอบ:'):
        audience='respondent'
    if heading.startswith('# คู่มือผู้ดูแล:'):
        admin_manual=True
    if 'สำหรับผู้ดูแล' in heading or heading=='## การตรวจและสูตร F05' or admin_manual:
        audience='server_only'
    if heading=='## ติดตามการนำไปใช้ (ข้อมูลเพื่อปรับปรุง ไม่เพิ่มตัวชี้วัดบังคับ)':
        audience='respondent'
    sections.append({'section_id':f'INS-{idx+1:03}','heading_th':m.group(),
       'source':ref(I[:m.start()].count('\n')+1),'content_th':I[m.start():end].rstrip(),
       'content_en':None,'translation_status':'missing','audience':audience,
       'publication_rule':'select approved respondent fields; never expose the raw source-section collection'})
for q in questions.values():
    q['source_section_id']=next(s['section_id'] for s in reversed(sections) if s['source']['line']<=q['source']['line'])
    q['prompt_context_rule']='Read the linked source section for its shared question stem and instructions; text is the source item, not a replacement for the stem.'

req=[]
heads=list(re.finditer(r'^## (\d+)\. (.+)$',B,re.M))
milestones={1:'M0',2:'M0',3:'M1',4:'M1',5:'M3–M5',6:'M3–M4',7:'M2–M4',8:'M3',9:'M1',10:'M0',11:'M2',12:'M2',13:'M5',14:'M4',15:'M3–M5',16:'M6',17:'M0–M7',18:'reference_only',19:'M0–M7',20:'M6',21:'M1–M5',22:'M6–M7',23:'M0–M7',24:'M2/M5',25:'M3',26:'M1/M3',27:'M3',28:'M5',29:'M0–M6',30:'M1–M5',31:'M0–M7',32:'reference_only',33:'M0–M7'}
for idx,m in enumerate(heads):
    number=int(m[1]); end=heads[idx+1].start() if idx+1<len(heads) else B.index('## แหล่งอ้างอิง',m.start())
    artifacts=['catalog/requirements.json','docs/source/'+BNAME]
    if number in [1,2,6,9,10,17,23,25,31]: artifacts+=['catalog/questions.json','catalog/indicators.json','catalog/groups.json']
    if number in [2,10,11,12,26]: artifacts+=['catalog/formulas.json']
    if number==33: artifacts+=['catalog/translations.json','catalog/glossary.json']
    req.append({'requirement_id':f'BP-{number:02}','section':number,'title_th':m[2],
       'source':ref(B[:m.start()].count('\n')+1,BNAME),'content_th':B[m.start():end].rstrip(),
       'delivery_phase':milestones[number],'m0_artifacts':artifacts,
       'status':'catalog_specified_runtime_pending' if number not in [18,32] else 'embedded_prompt_not_execution_authority',
       'test_ids':sorted(set(re.findall(r'\b(?:CAL-\d{2}|U\d{2}|NEW\d{2}|LANG\d{2})\b',B[m.start():end])))})

translations=[]
for q in questions.values():
    translations.append({'key':q['question_id']+'.text','content_version':'1.1','th':q['text']['th'],'en':None,'status':'missing','source':q['source'],'audience':q['audience']})
    for opt in q['options']:
        translations.append({'key':q['question_id']+'.option.'+opt['code'],'content_version':'1.1','th':opt['label']['th'],'en':None,'status':'missing','source':q['source'],'audience':q['audience']})
for s in sections:
    translations.append({'key':s['section_id']+'.content','content_version':'1.1','th':s['content_th'],'en':None,'status':'missing','source':s['source'],'audience':s['audience']})
for g,label in GROUPS.items():
    translations.append({'key':'group.'+g+'.label','content_version':'1.1','th':label,'en':None,'status':'missing'})
for indicator in indicators:
    translations.append({'key':'indicator.'+indicator['code']+'.display_name','content_version':'1.1','th':indicator['display_name']['th'],'en':None,'status':'missing'})
glossary=[('การประเมินตนเอง','Self-assessment'),('ไม่เกี่ยวข้อง','Not applicable'),('ยังประเมินตนเองไม่ได้','Unable to self-assess'),('ไม่ทราบ','Do not know'),('ข้อมูลขาด','Missing data'),('ยังไม่มีข้อมูลที่ใช้คำนวณ','No valid data'),('ปกปิดผล','Suppressed'),('รับรองผลรวม','Aggregate result approval'),('เผยแพร่ผล','Result publication'),('ปีงบประมาณ','Fiscal year'),('ปีการศึกษา','Academic year'),('ปีปฏิทิน','Calendar year'),('ช่วงรายงาน','Reporting period'),('ช่วงเปิดรับข้อมูล','Collection window'),('ระดับคาดหวัง','Expected level'),('หลักฐาน F05','F05 evidence'),('กลุ่มผู้ตอบ','Respondent group'),('ตัวตั้ง','Numerator'),('ตัวหาร','Denominator'),('ส่งแล้วแต่ข้อมูลไม่ครบ','Submitted with incomplete data')]

def main():
    OUT.mkdir(exist_ok=True)
    assert len(indicators)==63 and len({i['code'] for i in indicators})==63
    assert [r['section'] for r in req]==list(range(1,34))
    save('questions.json',list(questions.values()))
    save('instruments.json',[{'instrument_id':f,'version':'1.1','title_th':next(line[2:] for line in IL if line.startswith('# '+f+' ')),
      'group_codes':FG[f],'question_ids':[q for q in questions if q.startswith(f+'-')],
      'response_unit':{'F01':'person_year; C3.1 person_course_cohort','F02':'invitation_role_context_unit_per_round','F03':'staff_year_anonymous','F04':'respondent_evaluatee_role_programme_appointment_round','F05':'person_activity_session','F06':'person_dimension_round_submitted_revision'}[f],
      'identity_domain':'identified' if f in ['F05','F06'] else 'anonymous_answers_separate_from_invitations',
      'assessment_method':'self_report' if f=='F06' else 'verified_activity' if f=='F05' else 'survey',
      'workflow':{'F05':['draft','submitted','needs_correction','verified','rejected'],'F06':['draft','submitted','revised_submission']}.get(f,['draft','submitted_read_only']),
      'completion_separate_from_submission':True,'blueprint_requirements':[1,2,6,7,8,9,10,26,33]} for f in FG])
    save('ancillary_fields.json',{'status':'implementation_field_keys_not_new_baseline_question_ids','fields':[
      {'field_key':'development.actual_visit_hours','source':ref(locate('แบบกระดาษใช้แถวผู้เข้าร่วม:')),'type':'decimal','minimum':0,'separate_from':'F05-P03'},
      {'field_key':'development.external_visit','source':ref(locate('- 7.3-49 =')),'type':'boolean','used_by':['7.3-49']},
      {'field_key':'development.session_key','source':ref(locate('- ตรวจซ้ำด้วยบุคลากร')),'type':'context_reference','purpose':'no_person_activity_session_duplicates'},
      {'field_key':'survey.same_incident_question_id','source':ref(locate('เมื่อข้อใดตอบ Y')),'type':'question_reference','required':False,'instruments':['F01'],'purpose':'reuse_same_incident_details_without_reasking'},
      {'field_key':'survey.last_service_month','source':ref(locate('| F02-P04 |')),'type':'month_year','required_if':'F02-P04=month_year','unknown_option':'cannot_recall'},
      {'field_key':'self.expected_level','source':ref(locate('ช่องบันทึกต่อด้าน:')),'type':'integer_scale','range':[1,5],'frozen_before_round':True},
      {'field_key':'self.optional_example','source':ref(locate('ช่องบันทึกต่อด้าน:')),'type':'text','required':False,'affects_score':False},
      {'field_key':'self.optional_development_plan','source':ref(locate('แบบบันทึก: รหัสบุคลากร')),'type':'structured_optional','required':False,'affects_submission':False,'source_text_th':block('แบบบันทึก: รหัสบุคลากร')},
      {'field_key':'self.applicability_reason','source':ref(locate('M01–05 รองรับ')),'type':'text','required_if':'self_declared_not_applicable','external_approval':False}
    ]})
    save('indicators.json',sorted(indicators,key=lambda x:x['code']))
    save('formulas.json',formulas)
    save('groups.json',[{'code':c,'label':{'th':t,'en':None},'active':True,'source':ref(locate('F01-P01' if c in LEARNERS else 'F03-P01' if c in STAFF else 'F02-P01'))} for c,t in GROUPS.items()])
    save('instrument_sections.json',sections)
    save('scales.json',list(scales.values()))
    save('requirements.json',req)
    save('translations.json',{'default_locale':'th','supported_locales':['th','en'],'bundle_version':'1.1-draft','publishable':False,
      'publication_rule':'Only approved respondent-audience entries may be sent to respondents. All active questions/options/instructions/rubrics must be semantically approved in th/en; no silent fallback; changed source marks translation stale.',
      'inventory':translations,'system_surfaces':['public','login','my_tasks','F01–F06','form_builder','validation','calendar','notification','email','dashboard_public','dashboard_executive','dashboard_admin','CSV','XLSX','PDF'],
      'invariants':['stable_question_option_indicator_ids','locale_does_not_change_scores_population_dates_permissions','language_switch_preserves_unsaved_answers','round_freezes_translation_bundle','cache_includes_locale_and_audience','notification_locale_does_not_duplicate_delivery','free_text_and_history_not_auto_translated']})
    save('glossary.json',[{'th':th,'en':en,'status':'needs_review','official_name':False} for th,en in glossary])
    save('answer_keys.server.json',{'access':'server_only_never_include_in_respondent_schema','instruments':['F01','F02'],'instrument_version':'1.1','correct_options':{'K01':'B','K02':'A','K03':'C','K04':'B','K05':'A','K06':'D'},'unknown_U_score':0,'blank':'missing','F06_uses_this_key':False})
    save('manifest.json',{'catalog_version':'1.1','blueprint_version':'1.2','status':'M0_offline_catalog','database_contacted':False,
      'source_documents':[{'path':'docs/source/'+n,'sha256':hashlib.sha256((SOURCE/n).read_bytes()).hexdigest(),'lines':len((SOURCE/n).read_text(encoding='utf-8').splitlines())} for n in [BNAME,INAME]],
      'counts':{'questions':len(questions),'indicators':len(indicators),'formulas':len(formulas),'groups':len(GROUPS),'blueprint_sections':len(req)},
      'source_location_policy':'docs/source is a directory. Root source files retained; supplied copies preserved byte-for-byte.',
      'limitations':['Official indicator names need the referenced PDF; no invented original titles.','English instrument translations and semantic approval remain M3 deliverables.','Runtime forms, formula execution, six UI prototypes and database seeding are not implemented by this catalog.','Original unnumbered ancillary fields are preserved in instrument_sections.json; assign new implementation field IDs separately from baseline IDs.']})
    rows=['# M0: ทะเบียนเชื่อมโยง 63 รหัส','', 'ฐานเครื่องมือ 1.1 / Blueprint 1.2; ข้อมูลนิยามเท่านั้น ไม่มีผลสำรวจจริง', '', '| รหัส | คำถาม | สูตร | กลุ่ม |','|---|---|---|---|']
    for i in sorted(indicators,key=lambda x:x['code']):
        b=i['binding']; rows.append('| '+i['code']+' | '+', '.join(b['source_question_ids'])+' | '+b['formula_id']+' | '+', '.join(b['group_codes'])+' |')
    (ROOT/'docs/m0-mapping.md').write_text('\n'.join(rows)+'\n',encoding='utf-8')
    rows=['# การเชื่อมโยงข้อกำหนด Blueprint 1–33','', 'การเชื่อมโยงนี้ระบุขอบเขตและตำแหน่งงาน ไม่อ้างว่าความสามารถทุกข้อพัฒนาเสร็จแล้ว', '', '| ข้อ | ข้อกำหนด | ระยะพัฒนา | สิ่งที่เชื่อมใน M0 |','|---|---|---|---|']
    for r in req: rows.append('| '+str(r['section'])+' | '+r['title_th']+' | '+r['delivery_phase']+' | '+', '.join(r['m0_artifacts'])+' |')
    (ROOT/'docs/requirements-traceability.md').write_text('\n'.join(rows)+'\n',encoding='utf-8')
    print(json.dumps({'questions':len(questions),'indicators':len(indicators),'formulas':len(formulas),'groups':len(GROUPS),'requirements':len(req)}))

if __name__=='__main__': main()
