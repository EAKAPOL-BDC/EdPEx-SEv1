"""Deterministic fictional years using the production intake/calculation services.

This does not impersonate real respondents, backdate audit timestamps, email
invitations, or create login accounts. All form copies and rounds are labelled.
"""
from datetime import date,timedelta
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.calculations.codec import digest
from apps.catalog.models import InstrumentVersion
from apps.catalog.services import clone_instrument_version,source_texts,publish_bundle,publish_instrument_version
from apps.catalog.management_services import prepare_translations,editor_token
from apps.catalog.indicator_wording import prepare as prepare_wording,REVISION as WORDING_REVISION
from apps.rounds.models import CollectionRound,ReportingPeriod,RespondentGroup
from apps.rounds.web_services import create_period,save_population,save_member
from apps.rounds.services import create_record,freeze_population,transition_round
from apps.surveys.operator import save_round
from apps.surveys import services,schema
from apps.surveys.calculations import calculate
from apps.calculations.review import request_review,decide_results
from .f05_quantitative import prepare as prepare_f05

PREFIX='[SIMULATION ONLY] '
NOTICE='ข้อมูลสมมุติสำหรับทดสอบระบบ ไม่ใช่ผลการดำเนินงานจริง / Fictional test data, not actual institutional performance.'

def can_simulate_review(actor,run,reason):
    from apps.accounts.permissions import can_access
    return run.collection_round.data_kind=='synthetic' and reason.startswith(PREFIX) and all(
        can_access(actor,p,run.collection_round.scope) for p in ('result.review','result.approve','calculation.validate'))

def prepare_forms(actor,scope,progress=lambda message: None):
    """Keep real drafts unpublished; auto-review only explicitly isolated copies."""
    progress('เตรียม F05 เชิงปริมาณฉบับปัจจุบัน')
    prepare_f05(actor,scope)
    bundles={};real={}
    for code in ['F01','F02','F03','F04','F05','F06']:
        progress(f'{code}: ตรวจแบบฟอร์มต้นทาง')
        versions=list(InstrumentVersion.objects.filter(instrument__scope=scope,instrument__code=code).order_by('-created_at','-pk'))
        candidates=[v for v in versions if not v.source_metadata.get('synthetic_only') and v.status!='retired']
        if code=='F05':candidates=[v for v in candidates if v.version=='2.1-quantitative']
        if not candidates:raise ValidationError('ไม่พบแบบฟอร์มปัจจุบัน / Missing current form: '+code)
        source=candidates[0]
        from apps.catalog.presentation import instrument_title
        if code!='F05' and (source.source_metadata.get('wording_revision')!=WORDING_REVISION or instrument_title(source.title_th)!=source.title_th):
            name='2.2-current';i=1
            while source.instrument.versions.filter(version=name).exists():i+=1;name=f'2.2-current-{i}'
            progress(f'{code}: สร้างฉบับคำชี้แจงปัจจุบัน')
            source=prepare_wording(actor,source,name,editor_token(actor,source))
        real[code]=str(source.pk)
        # Hash both source identity and texts so later edits yield a fresh copy.
        token=digest({'id':str(source.pk),'texts':source_texts(source)})[:8]
        name=(source.version[:20]+'-sim-'+token)
        v=source.instrument.versions.filter(version=name).first()
        if v and v.status=='published':
            bundles[code]=v.translation_bundles.get(status='published')
            progress(f'{code}: ใช้ฉบับจำลองที่ตรวจครบแล้ว');continue
        if v:raise ValidationError('มีแบบจำลองที่ยังไม่เสร็จ กรุณาตรวจแบบฟอร์ม / Incomplete simulation form: '+name)
        progress(f'{code}: คัดลอกแบบฟอร์มสำหรับข้อมูลสมมุติ')
        v=clone_instrument_version(actor,source,name)
        v.source_metadata={**v.source_metadata,'synthetic_only':True,'simulation_source':str(source.pk)}
        v.instructions_curated=True;v.save()
        progress(f'{code}: เตรียมคำแปลไทยและอังกฤษ')
        bundle=prepare_translations(actor,v.pk)
        from .simulation_review import review_simulation_bundle
        progress(f'{code}: ตรวจคำแปลของฉบับจำลอง')
        review_simulation_bundle(actor,bundle,progress)
        progress(f'{code}: ตรวจความครบถ้วนและเผยแพร่เฉพาะฉบับจำลอง')
        publish_bundle(actor,bundle);bundle.refresh_from_db();publish_instrument_version(actor,v)
        bundles[code]=bundle
        progress(f'{code}: เตรียมแบบฟอร์มเสร็จแล้ว')
    return bundles,real

def period_for(actor,scope,year,basis):
    if basis=='fiscal':
        from apps.leadership.models import AnnualPlan
        plan=AnnualPlan.objects.filter(scope=scope,fiscal_year=year).select_related('period').first()
        if plan:return plan.period
    periods=ReportingPeriod.objects.filter(calendar__scope=scope,calendar__calendar_type=basis,
        reporting_year_be=year,parent__isnull=True,approved=True).order_by('-created_at')
    if basis=='fiscal':periods=periods.filter(start_date=date(year-544,10,1),end_date=date(year-543,10,1))
    existing=periods.first()
    if existing:return existing
    start,end=(date(year-544,10,1),date(year-543,9,30)) if basis=='fiscal' else (date(year-543,6,1),date(year-542,5,31))
    return create_period(actor,scope,dict(code=f'{"ปีการศึกษา" if basis=="academic" else "ปีงบประมาณ"} {year}',calendar_type=basis,
        reporting_year_be=year,start_date=start,last_date=end,reason='Annual preparation; academic June–May dates are provisional and must be reviewed before real collection.'))

def example_answers(profile,index,year):
    code=profile.binding.instrument_version.instrument.code
    qs=schema.questions(profile);answers={}
    for qid,q in qs.items():
        if code!='F06' and not schema.visible(profile,q,answers):continue
        fixed=schema.fixed(profile,q)
        if fixed is not None:continue
        opts=[o for o in schema.options(profile,q) if o.answer_status=='answered']
        if code=='F05':
            value=str(index*(4 if profile.group_code=='ST2' else 6)+(year-2565)*2 if index else 0) if qid=='F05-Y01' else ('yes' if index>=5 else 'no')
        elif q.answer_type=='integer_scale':
            scores=sorted({int(o.score) for o in opts if o.score is not None})
            value=scores[min(len(scores)-1,max(0,len(scores)-3+(index+year+sum(map(ord,profile.group_code)))%3))]
        elif q.answer_type in {'single_choice','multi_choice'}:
            choices=[o for o in opts if o.code not in {'U','none','month_year'}] or opts
            if not choices:raise ValidationError('No simulation option: '+qid)
            value=choices[(index+year)%len(choices)].code
            if qid=='F04-P03':value='sufficient'
            if q.answer_type=='multi_choice':value=[value]
        elif q.answer_type=='text':value='ข้อความสมมุติ: เสนอให้สื่อสารขั้นตอนงานให้ชัดเจน'
        else:continue
        answers[qid]={'status':'answered','value':value}
    # F06 includes an explicit non-applicable scenario, with a generic reason.
    if code=='F06' and index==0:
        for qid in qs:
            if qid.startswith(('F06-M','F06-T')):answers[qid]={'status':'not_applicable','reason':'สถานการณ์ทดสอบ: ไม่อยู่ในหน้าที่สมมุติ'}
    return answers

def populate(actor,binding,year,progress=lambda message: None):
    r=binding.collection_round
    progress(f'{r.code}: เตรียมผู้มีสิทธิ์สมมุติ')
    if r.status=='draft':
        now=timezone.now();p=binding.survey_profile
        pop=save_population(actor,r,dict(definition=NOTICE,count=12,captured_at=now,source_title='ทะเบียนสมมุติ',source_location='Generated in this workspace; no external source'))
        group=RespondentGroup.objects.get(scope=r.scope,code=p.group_code)
        for i in range(12):save_member(actor,r,dict(eligible_unit_key=f'SIM-{year}-{p.group_code}-{i:02}',group=group))
        freeze_population(actor,pop);r=transition_round(actor,r,'ready')
    r=transition_round(actor,r,'open');binding.collection_round=r
    # Ten completed responses and two nonrespondents: reports can exercise
    # denominators, zero hours and the five-person disclosure threshold.
    for i,member in enumerate(r.population_snapshot.members.order_by('eligible_unit_key')):
        raw=services.issue(actor,binding.pk,member.pk)
        if i>=10:continue
        session=services.exchange(raw)
        services.save(session,example_answers(binding.survey_profile,i,year),revision=0,submit=True)
        if i in (4,9):progress(f'{r.code}: บันทึกคำตอบสมมุติ {i+1}/10 คน')
    transition_round(actor,r,'closed',reason=NOTICE)

def leadership_bindings(actor,scope,year,bundle,window,progress=lambda message: None):
    from apps.leadership.models import Person,Programme,Position,AnnualTarget,Eligibility
    from apps.leadership.services import create_plan,save_record,freeze_target,generate_collections
    plan=create_plan(actor,scope,year);result=[]
    def master(model,code,**values):
        obj=model.objects.filter(scope=scope,code=code).first()
        return obj or save_record(actor,scope,model,dict(code=code,**values))
    # Distinct, clearly fictional masters are not login accounts.
    assessors=[master(Person,f'SIM-ASSESSOR-{i:02}',name_th=f'ผู้เกี่ยวข้องสมมุติ {i+1}',name_en=f'Fictional related person {i+1}') for i in range(12)]
    positions=[('DE','คณบดี',None),('VD1','รองคณบดีฝ่ายวิชาการ',None),('VD2','รองคณบดีฝ่ายบริหาร',None),
               ('AS1','ผู้ช่วยคณบดีฝ่ายพัฒนานิสิต',None),('AS2','ผู้ช่วยคณบดีฝ่ายคุณภาพ',None),
               ('PC1','ประธานหลักสูตร',1),('PC2','ประธานหลักสูตร',2)]
    for idx,(key,title,programme_no) in enumerate(positions):
        progress(f'ปี {year} F04: เตรียม {key} {title}')
        programme=master(Programme,f'SIM-PROGRAMME-{programme_no}',name_th=f'หลักสูตรสมมุติ {programme_no}',name_en=f'Fictional programme {programme_no}') if programme_no else None
        role=key[:2];position=master(Position,'SIM-'+key,role=role,title_th=title+' (สมมุติ)',title_en='Fictional '+key,programme=programme)
        segments=[(plan.period.start_date,date(year-543,4,1)),(date(year-543,4,1),plan.period.end_date)] if key=='VD1' else [(plan.period.start_date,plan.period.end_date)]
        for j,(start,end) in enumerate(segments):
            person=master(Person,f'SIM-HOLDER-{year}-{key}-{j}',name_th=f'ผู้ดำรงตำแหน่งสมมุติ {key} คนที่ {j+1}',name_en=f'Fictional {key} holder {j+1}')
            target=AnnualTarget.objects.filter(scope=scope,plan=plan,position=position,person=person,start_date=start,end_date=end).first()
            if not target:
                target=save_record(actor,scope,AnnualTarget,dict(plan=plan,person=person,position=position,title_th=position.title_th,title_en=position.title_en,
                    responsibility_th='หน้าที่สมมุติเพื่อทดสอบแยกผู้ถูกประเมินและช่วงดำรงตำแหน่ง',responsibility_en='Fictional duties for testing separate appointment segments',
                    start_date=start,end_date=end,source_reference='SIMULATION: no actual appointment',eligibility_basis='รายชื่อผู้เกี่ยวข้องสมมุติของตำแหน่ง/หลักสูตรนี้เท่านั้น'))
                for assessor in assessors:
                    save_record(actor,scope,Eligibility,dict(target=target,person=assessor,group_code='ST1' if programme_no or idx%2==0 else 'ST2',relationship='ผู้เกี่ยวข้องสมมุติในงานหรือหลักสูตรที่ประเมิน'))
                target=freeze_target(actor,scope,target.pk,NOTICE)
            result.extend(generate_collections(actor,scope,[str(target.pk)],dict(bundle=bundle,owner=actor,privacy_notice=NOTICE,**window),data_kind='synthetic'))
    return result

def seed_workspace(actor,scope,progress=lambda message: None):
    from .refresh import authorize
    authorize(actor,scope)
    progress('เริ่มเตรียมแบบฟอร์มปัจจุบันและฉบับจำลอง')
    bundles,real=prepare_forms(actor,scope,progress)
    now=timezone.now();window=dict(open_at=now-timedelta(hours=1),due_at=now+timedelta(days=1),close_at=now+timedelta(days=2))
    bindings=[];periods={}
    for year in [2565,2566,2567]:
        progress(f'เริ่มสร้างคำตอบสมมุติปี {year}')
        periods[year]={b:period_for(actor,scope,year,b) for b in ['academic','fiscal']}
        for code in ['F01','F02','F03','F05','F06']:
            version=bundles[code].instrument_version
            for group in version.group_codes:
                data=dict(code=f'SIM-{year}-{code}-{group}',bundle=bundles[code],period=periods[year]['academic' if code=='F01' else 'fiscal'],owner=actor,
                    privacy_notice=NOTICE,group_code=group,counting_unit='organization_representative' if code=='F02' and group.startswith('P') else 'person',
                    context_th=f'ข้อมูลสมมุติ {code} ปี {year}',context_en=f'Fictional {code} year {year}',assessor_role='',study_options=['option_1','option_2','option_3','option_4','option_5'] if code=='F01' and group!='C3.1' else [],**window)
                progress(f'{data["code"]}: สร้างรอบ')
                binding=save_round(actor,scope,data,data_kind='synthetic');populate(actor,binding,year,progress);bindings.append(binding)
        for group in ['ST1','ST2']:
            data=dict(code=f'SIM-{year}-F04-BO-{group}',bundle=bundles['F04'],period=periods[year]['fiscal'],owner=actor,privacy_notice=NOTICE,group_code=group,counting_unit='person',context_th=f'คณะกรรมการสมมุติ ปี {year}',context_en=f'Fictional board {year}',assessor_role='BO',study_options=[],**window)
            progress(f'{data["code"]}: สร้างรอบ')
            binding=save_round(actor,scope,data,data_kind='synthetic');populate(actor,binding,year,progress);bindings.append(binding)
        for binding in leadership_bindings(actor,scope,year,bundles['F04'],window,progress):populate(actor,binding,year,progress);bindings.append(binding)
    # The cutoff is one genuine instant after all synthetic submissions, enabling
    # compatible same-year group comparisons without fabricated audit timestamps.
    cutoff=timezone.now();result_count=0
    progress(f'Calculating {len(bindings)} result sets')
    for binding in bindings:
        progress(f'คำนวณและตรวจผล {result_count+1}/{len(bindings)}: {binding.collection_round.code}')
        result=calculate(actor,binding.pk,cutoff,'SIM-'+str(binding.pk))
        run_id=result['run_id']
        request=request_review(actor,run_id=run_id,reason=PREFIX+'Generated test results')
        decide_results(actor,run_id=run_id,outcome='approved',reason=PREFIX+'Automated simulation, not an institutional approval',reviewed_token=request['review_token'])
        result_count+=1
        if result_count%10==0:progress(f'Calculated {result_count}/{len(bindings)}')
    progress('เตรียมปี 2568: รอบร่าง ไม่มีคำตอบหรือผลคำนวณ')
    periods[2568]={b:period_for(actor,scope,2568,b) for b in ['academic','fiscal']}
    pending=0
    from apps.rounds.models import RoundInstrument
    from apps.surveys.models import SurveyProfile
    from apps.surveys.validation import validate_schema
    for code in ['F01','F02','F03','F05','F06']:
        version=InstrumentVersion.objects.get(pk=real[code])
        bundle=version.translation_bundles.order_by('-created_at').first()
        for group in version.group_codes:
            r=create_record(actor,CollectionRound,scope=scope,period=periods[2568]['academic' if code=='F01' else 'fiscal'],
                code=f'2568-{code}-{group}-รอเก็บข้อมูล',owner=actor,schedule_confirmed=False,
                privacy_notice='รอผู้ดูแลกำหนดวันรับคำตอบ คำชี้แจง และผู้มีสิทธิ์ / Awaiting administrator setup.',**window)
            binding=create_record(actor,RoundInstrument,collection_round=r,instrument_version=version,translation_bundle=bundle,context=f'2568-{code}')
            profile=SurveyProfile(binding=binding,group_code=group,counting_unit='organization_representative' if code=='F02' and group.startswith('P') else 'person',context_th=f'{code} ปี 2568 (รอกำหนดบริบท)',context_en=f'{code} year 2568 (context to be configured)',
                study_options=['option_1','option_2','option_3','option_4','option_5'] if code=='F01' and group!='C3.1' else [])
            profile.save();validate_schema(profile);pending+=1
    from apps.leadership.services import create_plan
    create_plan(actor,scope,2568)  # No invented real evaluatees or eligible people.
    return {'synthetic_years':[2565,2566,2567],'synthetic_rounds':len(bindings),'synthetic_responses':len(bindings)*10,
        'result_sets':result_count,'pending_year':2568,'pending_rounds':pending,'f04_pending_register':2568,'real_form_versions':real,
        'academic_dates_note':'June–May example when no existing academic year; administrator must review before real collection.'}
