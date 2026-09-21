"""F05 quantitative annual contract. Versioned separately to preserve earlier replay."""
from decimal import Decimal,InvalidOperation,localcontext
from django.core.exceptions import ValidationError
from django.db import transaction
from apps.accounts.permissions import require_permission
from apps.catalog.models import (Instrument,InstrumentVersion,Question,QuestionOption,InstrumentContent,
 FormulaVersion,Indicator,IndicatorBinding,BindingQuestion,TranslationBundle,ContentTranslation,source_hash)
from apps.calculations.types import FormulaSpec,CalculationInputError
from apps.calculations.codec import digest

CONTRACT='f05-quantitative-annual-v2'
VERSION='2.1-quantitative'
GROUPS=['ST1','ST2']
QUESTIONS={
 'F05-Y01':('decimal','ในปีงบประมาณที่ระบุ คุณได้รับการอบรมรวมทั้งหมดกี่ชั่วโมง (ไม่ได้อบรมให้กรอก 0)','How many total training hours did you attend in the stated fiscal year? Enter 0 if none; count each training hour only once.'),
 'F05-Y02':('single_choice','ในปีงบประมาณที่ระบุ คุณได้รับการอบรมด้านเทคโนโลยีสมัยใหม่หรือไม่','In the stated fiscal year, did you attend training in modern technology?'),
 'F05-Y03':('single_choice','ในปีงบประมาณที่ระบุ คุณได้รับการอบรมด้านดิจิทัลหรือไม่','In the stated fiscal year, did you attend digital skills training?'),
 'F05-Y04':('single_choice','ในปีงบประมาณที่ระบุ คุณได้รับการอบรมด้านความปลอดภัยหรือไม่','In the stated fiscal year, did you attend safety training?'),
 'F05-Y05':('single_choice','ในปีงบประมาณที่ระบุ คุณได้รับการอบรมด้านอาชีวอนามัยหรือไม่','In the stated fiscal year, did you attend occupational health training?'),
 'F05-Y06':('single_choice','ในปีงบประมาณที่ระบุ คุณได้รับการอบรมด้านพลังงานหรือไม่','In the stated fiscal year, did you attend energy training?'),
 'F05-Y07':('single_choice','ในปีงบประมาณที่ระบุ คุณได้รับการอบรมด้านประกันคุณภาพหรือไม่','In the stated fiscal year, did you attend quality assurance training?'),
 'F05-Y08':('single_choice','ในปีงบประมาณที่ระบุ คุณได้เข้าร่วมศึกษาดูงานหน่วยงานภายนอกหรือไม่','In the stated fiscal year, did you participate in an external study visit?'),
}
MAP={
 '7.3-44':('TRAINING_HOURS',['F05-Y01'],'ชั่วโมงอบรมเฉลี่ยต่อผู้ตอบแบบสอบถาม'),
 '7.3-45':('TRAINING_PEOPLE',['F05-Y02'],'ร้อยละผู้ตอบที่รายงานว่าอบรมด้านเทคโนโลยีสมัยใหม่'),
 '7.3-46':('TRAINING_PEOPLE',['F05-Y03'],'ร้อยละผู้ตอบที่รายงานว่าอบรมด้านดิจิทัล'),
 '7.3-47':('SAFETY_ANY',['F05-Y04','F05-Y05','F05-Y06'],'ร้อยละผู้ตอบที่รายงานว่าอบรมด้านความปลอดภัย อาชีวอนามัย หรือพลังงานอย่างน้อยหนึ่งด้าน'),
 '7.3-48':('TRAINING_PEOPLE',['F05-Y07'],'ร้อยละผู้ตอบที่รายงานว่าอบรมด้านประกันคุณภาพ'),
 '7.3-49':('STUDY_VISIT',['F05-Y08'],'ร้อยละผู้ตอบที่รายงานว่าเข้าศึกษาดูงานภายนอก'),
}
PARAMETERS={'contract':CONTRACT,'denominator':'submitted_respondents','evidence_verified':False}
INSTRUCTION='แบบสอบถามนี้เก็บข้อมูลเชิงปริมาณของคุณในปีงบประมาณที่ระบุเพียงครั้งเดียว มี 8 ข้อ: ชั่วโมงอบรมรวม และการได้รับการอบรมหรือศึกษาดูงานแต่ละด้าน ตอบให้ครบก่อนส่ง หากไม่ได้อบรมให้กรอก 0 ชั่วโมงและเลือกไม่ได้เข้าร่วม นับชั่วโมงอบรมทุกเรื่องรวมกัน โดยนับแต่ละชั่วโมงครั้งเดียว แม้กิจกรรมนั้นครอบคลุมหลายด้าน ไม่ต้องกรอกชื่อ รหัสบุคลากร รายละเอียดกิจกรรม สถานที่ ผู้จัด หน่วยงาน หรือแนบหลักฐาน ชั่วโมงเฉลี่ยเท่ากับชั่วโมงรวมของผู้ส่งแบบสอบถามทุกคน หารด้วยจำนวนผู้ส่งทั้งหมด รวมผู้ที่กรอก 0 ชั่วโมงด้วย ผู้ที่ยังไม่ส่งจะไม่ถูกนับเป็น 0 ผลเป็นข้อมูลที่ผู้ตอบรายงานเอง'
INSTRUCTION_EN='Submit one quantitative summary for the stated fiscal year. Complete all eight items: total training hours and whether you attended each type of training or study visit. Enter 0 hours if you had no training. Include training on all topics and count each hour only once even if it covers multiple categories. Do not provide your name, staff ID, activity details, venue, organizer, organization or evidence. Average hours equal the total hours reported by all respondents divided by the number of respondents, including those reporting 0. Nonrespondents are not counted as zero. Results are self-reported.'


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
        qs[qid]=Question.objects.create(version=v,question_id=qid,text_th=th,answer_type=kind,group_codes=GROUPS,visibility_rule={'op':'in_group'},answer_statuses=['answered'],source_metadata={'contract':CONTRACT})
        texts[qid+'.text']=(th,en)
        if kind=='single_choice':
            for pos,(code,th,en) in enumerate([('yes','ได้เข้าร่วม','Yes'),('no','ไม่ได้เข้าร่วม','No')]):
                QuestionOption.objects.create(question=qs[qid],code=code,label_th=th,position=pos,answer_status='answered')
                texts[qid+'.option.'+code]=(th,en)
    for code,(key,qids,label) in MAP.items():
        indicator=Indicator.objects.get(scope=scope,code=code)
        formula,_=FormulaVersion.objects.get_or_create(scope=scope,key=key,version=VERSION,defaults={'definition_th':'ข้อมูลรายงานตนเองแบบไม่ระบุตัวตน: ตัวหารคือผู้ส่งแบบสอบถามครบทั้ง 8 ข้อทุกคน รวมผู้ที่กรอก 0 ชั่วโมง ไม่รวมผู้ที่ยังไม่ส่ง และแสดงจำนวนผู้ตอบเทียบผู้มีสิทธิ์', 'parameters':PARAMETERS,'source_hash':digest(PARAMETERS)})
        binding=IndicatorBinding.objects.create(version=v,indicator=indicator,formula=formula,group_rules={'group_codes':GROUPS},source_metadata={'contract':CONTRACT,'source_question_ids':qids},indicator_snapshot={'code':code,'display_name_th':label,'unit':indicator.unit,'method':'anonymous_self_report','denominator':'submitted_respondents'})
        for qid in qids:BindingQuestion.objects.create(binding=binding,question=qs[qid])
    bundle=TranslationBundle.objects.create(instrument_version=v,bundle_version=VERSION+'-draft')
    for key,(th,en) in texts.items():
        for locale,text in [('th',th),('en',en)]:ContentTranslation.objects.create(bundle=bundle,content_key=key,locale=locale,text=text,status='needs_review',source_hash=source_hash(th))
    from apps.auditlog.services import record_event
    record_event(scope.organization,actor,'catalog.anonymous_f05_prepared','catalog.instrumentversion',str(v.pk),metadata={'scope_id':str(scope.pk),'contract':CONTRACT})
    return v


def validate_version(v):
    if v.assessment_method!='self_report' or v.evidence_required or v.assessor_scoring or v.source_metadata.get('contract')!=CONTRACT:
        raise ValidationError('F05 เชิงปริมาณต้องใช้รุ่น 2.1-quantitative ที่ตรวจคำแปลและเผยแพร่แล้ว / Prepare and publish the anonymous annual F05 version.')
    qs={q.question_id:q for q in v.questions.filter(active=True,audience='respondent').prefetch_related('options')}
    if set(qs)!=set(QUESTIONS) or v.group_codes!=GROUPS:raise ValidationError('ชุดคำถาม F05 ไม่ตรงรุ่นคำนวณ / Unsupported F05 contract.')
    for qid,q in qs.items():
        expected={'yes':(None,'answered'),'no':(None,'answered')} if QUESTIONS[qid][0]=='single_choice' else {}
        if (q.answer_type!=QUESTIONS[qid][0] or q.answer_statuses!=['answered'] or q.group_codes!=GROUPS or q.visibility_rule!={'op':'in_group'}
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
            if any(a.get('status')!='answered' for a in answers):raise CalculationInputError('Quantitative F05 requires every answer; missing must not change the denominator.')
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
        return {'status':'computed' if d else 'no_valid_data','value':str(value) if value is not None else None,'numerator':str(n),'denominator':str(len(rows)),'unit':unit,'counts':counts,'breakdown':{}}
    result=compute(qids,'hours_per_person' if code=='7.3-44' else 'percent')
    if code=='7.3-47':result['breakdown']={cat:compute([qid],'percent') for cat,qid in zip(['T47S','T47H','T47E'],qids)}
    return result
