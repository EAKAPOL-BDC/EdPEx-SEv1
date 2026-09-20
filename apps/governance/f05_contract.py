"""Versioned annual anonymous self-report; deliberately distinct from verified F05."""
from decimal import Decimal,InvalidOperation,localcontext
from django.core.exceptions import ValidationError
from django.db import transaction
from apps.accounts.permissions import require_permission
from apps.catalog.models import (Instrument,InstrumentVersion,Question,QuestionOption,InstrumentContent,
 FormulaVersion,Indicator,IndicatorBinding,BindingQuestion,TranslationBundle,ContentTranslation,source_hash)
from apps.calculations.types import FormulaSpec,CalculationInputError
from apps.calculations.codec import digest

CONTRACT='f05-anonymous-annual-v1'
VERSION='2.0-anonymous'
GROUPS=['ST1','ST2']
QUESTIONS={
 'F05-Y01':('decimal','ในปีงบประมาณนี้ คุณอบรมรวมกี่ชั่วโมง (ไม่นับชั่วโมงศึกษาดูงานซ้ำ; ไม่ได้อบรมให้ใส่ 0)','Total training hours this fiscal year, excluding study visits and duplicate hours. Enter 0 if none.'),
 'F05-Y02':('single_choice','คุณได้อบรมด้านเทคโนโลยีสมัยใหม่หรือไม่','Did you attend training in modern technology?'),
 'F05-Y03':('single_choice','คุณได้อบรมด้านดิจิทัลหรือไม่','Did you attend digital skills training?'),
 'F05-Y04':('single_choice','คุณได้อบรมด้านความปลอดภัยหรือไม่','Did you attend safety training?'),
 'F05-Y05':('single_choice','คุณได้อบรมด้านอาชีวอนามัยหรือไม่','Did you attend occupational health training?'),
 'F05-Y06':('single_choice','คุณได้อบรมด้านพลังงานหรือไม่','Did you attend energy training?'),
 'F05-Y07':('single_choice','คุณได้อบรมด้านประกันคุณภาพหรือไม่','Did you attend quality assurance training?'),
 'F05-Y08':('single_choice','คุณได้เข้าร่วมศึกษาดูงานหน่วยงานภายนอกหรือไม่','Did you participate in an external study visit?'),
 'F05-Y09':('text','ความรู้ที่นำไปใช้หรือเรื่องที่ต้องการพัฒนาต่อ (ไม่ระบุชื่อ หน่วยงานย่อย หรือกิจกรรมเฉพาะที่บอกตัวตน)','What have you applied or what would you like to develop? Avoid identifying details.'),
}
MAP={
 '7.3-44':('TRAINING_HOURS',['F05-Y01'],'ชั่วโมงอบรมเฉลี่ยต่อผู้ตอบที่ให้ข้อมูล (รายงานตนเอง)'),
 '7.3-45':('TRAINING_PEOPLE',['F05-Y02'],'ร้อยละผู้ตอบที่รายงานว่าอบรมด้านเทคโนโลยีสมัยใหม่'),
 '7.3-46':('TRAINING_PEOPLE',['F05-Y03'],'ร้อยละผู้ตอบที่รายงานว่าอบรมด้านดิจิทัล'),
 '7.3-47':('SAFETY_ANY',['F05-Y04','F05-Y05','F05-Y06'],'ร้อยละผู้ตอบที่รายงานว่าอบรมด้านความปลอดภัย อาชีวอนามัย หรือพลังงานอย่างน้อยหนึ่งด้าน'),
 '7.3-48':('TRAINING_PEOPLE',['F05-Y07'],'ร้อยละผู้ตอบที่รายงานว่าอบรมด้านประกันคุณภาพ'),
 '7.3-49':('STUDY_VISIT',['F05-Y08'],'ร้อยละผู้ตอบที่รายงานว่าเข้าศึกษาดูงานภายนอก'),
}
PARAMETERS={'contract':CONTRACT,'denominator':'valid_respondents','evidence_verified':False}
INSTRUCTION='ตอบข้อมูลรวมของคุณในปีงบประมาณที่ระบุเพียงครั้งเดียว ไม่กรอกชื่อ รหัสบุคลากร อีเมล หรือแนบหลักฐาน ข้ามข้อที่ไม่ทราบได้ การไม่ตอบจะไม่ถือว่าไม่ได้พัฒนา ผลเป็นภาพรวมจากคำบอกเล่าและคิดเฉพาะผู้ตอบที่ให้ข้อมูล ไม่ใช่ผลตรวจรับหลักฐานของบุคลากรทั้งหมด'
INSTRUCTION_EN='Submit one annual summary. Do not provide your name, staff ID, email or evidence. Skip unknown items. Missing answers do not mean no development. Results describe valid respondents and are self-reported, not verified whole-population records.'

@transaction.atomic
def prepare(actor,scope):
    require_permission(actor,'catalog.edit',scope)
    instrument=Instrument.objects.select_for_update().get(scope=scope,code='F05')
    existing=instrument.versions.filter(version=VERSION).first()
    if existing:return existing
    v=InstrumentVersion.objects.create(instrument=instrument,version=VERSION,title_th='F05 แบบสำรวจข้อมูลการพัฒนาตนเองของบุคลากร',assessment_method='self_report',identity_domain='anonymous',response_unit='one_person_fiscal_year',group_codes=GROUPS,workflow=['submitted'],instructions_curated=True,source_metadata={'contract':CONTRACT})
    texts={'F05.title':(v.title_th,'F05 Personnel self-development survey'),'F05.instructions':(INSTRUCTION,INSTRUCTION_EN)}
    InstrumentContent.objects.create(version=v,content_key='F05.title',kind='title',text_th=v.title_th,audience='respondent')
    InstrumentContent.objects.create(version=v,content_key='F05.instructions',kind='instruction',text_th=INSTRUCTION,audience='respondent')
    qs={}
    for qid,(kind,th,en) in QUESTIONS.items():
        qs[qid]=Question.objects.create(version=v,question_id=qid,text_th=th,answer_type=kind,group_codes=GROUPS,visibility_rule={'op':'in_group'},answer_statuses=['answered','skipped'],source_metadata={'contract':CONTRACT})
        texts[qid+'.text']=(th,en)
        if kind=='single_choice':
            for pos,(code,th,en) in enumerate([('yes','ได้เข้าร่วม','Yes'),('no','ไม่ได้เข้าร่วม','No')]):
                QuestionOption.objects.create(question=qs[qid],code=code,label_th=th,position=pos,answer_status='answered')
                texts[qid+'.option.'+code]=(th,en)
    for code,(key,qids,label) in MAP.items():
        indicator=Indicator.objects.get(scope=scope,code=code)
        formula,_=FormulaVersion.objects.get_or_create(scope=scope,key=key,version=VERSION,defaults={'definition_th':'ข้อมูลรายงานตนเองแบบไม่ระบุตัวตน: คำนวณจากผู้ตอบที่ให้ข้อมูลครบในตัวชี้วัดนั้น และแสดงจำนวนผู้ตอบเทียบผู้มีสิทธิ์ แยกจากข้อมูลตรวจรับหลักฐาน', 'parameters':PARAMETERS,'source_hash':digest(PARAMETERS)})
        binding=IndicatorBinding.objects.create(version=v,indicator=indicator,formula=formula,group_rules={'group_codes':GROUPS},source_metadata={'contract':CONTRACT,'source_question_ids':qids},indicator_snapshot={'code':code,'display_name_th':label,'unit':indicator.unit,'method':'anonymous_self_report','denominator':'valid_respondents'})
        for qid in qids:BindingQuestion.objects.create(binding=binding,question=qs[qid])
    bundle=TranslationBundle.objects.create(instrument_version=v,bundle_version=VERSION+'-draft')
    for key,(th,en) in texts.items():
        for locale,text in [('th',th),('en',en)]:ContentTranslation.objects.create(bundle=bundle,content_key=key,locale=locale,text=text,status='needs_review',source_hash=source_hash(th))
    from apps.auditlog.services import record_event
    record_event(scope.organization,actor,'catalog.anonymous_f05_prepared','catalog.instrumentversion',str(v.pk),metadata={'scope_id':str(scope.pk),'contract':CONTRACT})
    return v


def validate_version(v):
    if v.assessment_method!='self_report' or v.evidence_required or v.assessor_scoring or v.source_metadata.get('contract')!=CONTRACT:
        raise ValidationError('F05 รอบใหม่ต้องใช้รุ่น 2.0-anonymous ที่ตรวจคำแปลและเผยแพร่แล้ว / Prepare and publish the anonymous annual F05 version.')
    qs={q.question_id:q for q in v.questions.filter(active=True,audience='respondent').prefetch_related('options')}
    if set(qs)!=set(QUESTIONS) or v.group_codes!=GROUPS:raise ValidationError('ชุดคำถาม F05 ไม่ตรงรุ่นคำนวณ / Unsupported F05 contract.')
    for qid,q in qs.items():
        expected={'yes':(None,'answered'),'no':(None,'answered')} if QUESTIONS[qid][0]=='single_choice' else {}
        if (q.answer_type!=QUESTIONS[qid][0] or q.group_codes!=GROUPS or q.visibility_rule!={'op':'in_group'}
            or {o.code:(o.score,o.answer_status) for o in q.options.all()}!=expected):raise ValidationError('รูปแบบคำถาม F05 ไม่ตรงรุ่น / F05 question contract mismatch.')
    bindings=list(v.bindings.select_related('indicator','formula').prefetch_related('questions'))
    if {b.indicator.code for b in bindings}!=set(MAP):raise ValidationError('ตัวชี้วัด F05 ไม่ครบ / F05 indicators are incomplete.')
    for b in bindings:
        key,qids,_=MAP[b.indicator.code]
        if (b.formula.key!=key or b.formula.version!=VERSION or b.formula.parameters!=PARAMETERS or b.dimensions or b.group_rules!={'group_codes':GROUPS}
            or {q.question_id for q in b.questions.all()}!=set(qids) or b.source_metadata!={'contract':CONTRACT,'source_question_ids':qids}):raise ValidationError('สูตร F05 ไม่ตรงรุ่น / F05 formula contract mismatch.')


def replay(payload):
    if payload.get('contract')!=CONTRACT:raise CalculationInputError('Unknown anonymous annual contract.')
    spec=payload['spec'];code=payload['indicator'];key,qids,_=MAP[code]
    if spec!={'formula_key':key,'question_ids':qids,'instrument_version':VERSION,'formula_version':VERSION,'category':''}:raise CalculationInputError('Invalid annual formula snapshot.')
    rows=payload['rows'];eligible=payload['eligible_count'];ids=[r['unit_id'] for r in rows]
    if type(eligible) is not int or eligible<0 or len(ids)!=len(set(ids)) or len(ids)>eligible:raise CalculationInputError('Invalid anonymous population count.')
    def compute(items,unit):
        values=[]
        for row in rows:
            answers=[row['answers'].get(q,{}) for q in items]
            if any(a.get('status')!='answered' for a in answers):continue
            raw=[a.get('value') for a in answers]
            if unit=='hours_per_person':
                try:n=Decimal(raw[0]) if isinstance(raw[0],str) else Decimal('NaN')
                except InvalidOperation:raise CalculationInputError('Invalid hours.')
                if not n.is_finite() or not 0<=n<=8784 or n.as_tuple().exponent < -2:raise CalculationInputError('Invalid hours.')
                values.append(n)
            else:
                if any(v not in {'yes','no'} for v in raw):raise CalculationInputError('Invalid annual answer.')
                values.append(Decimal(any(v=='yes' for v in raw)))
        n=sum(values,Decimal(0));d=len(values)
        with localcontext() as ctx:
            ctx.prec=50
            value=n/Decimal(d)*(100 if unit=='percent' else 1) if d else None
        counts={'valid_n':d,'eligible':eligible,'submitted':len(rows),'missing':len(rows)-d,'not_responded':eligible-len(rows)}
        if unit=='percent':counts['passed']=int(n)
        return {'status':'computed' if d else 'no_valid_data','value':str(value) if value is not None else None,'numerator':str(n),'denominator':str(d),'unit':unit,'counts':counts,'breakdown':{}}
    result=compute(qids,'hours_per_person' if code=='7.3-44' else 'percent')
    if code=='7.3-47':result['breakdown']={cat:compute([qid],'percent') for cat,qid in zip(['T47S','T47H','T47E'],qids)}
    return result
