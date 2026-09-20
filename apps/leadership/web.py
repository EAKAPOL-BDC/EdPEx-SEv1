from datetime import timedelta
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from apps.accounts.permissions import can_access
from apps.catalog.management_web import errors
from apps.rounds.web import form_page
from apps.rounds.web_forms import ActionForm
from apps.selfassessments.operator_web import page
from .models import Person, Programme, Position, AnnualPlan, AnnualTarget, Eligibility, fiscal_window
from . import forms, services

MASTER={'people':(Person,forms.PersonForm,'บุคลากร / People'),'programmes':(Programme,forms.ProgrammeForm,'หลักสูตร / Programmes'),
        'positions':(Position,forms.PositionForm,'ตำแหน่ง / Positions')}


def scoped_plan(scope,pk):
    return get_object_or_404(AnnualPlan,pk=pk,scope=scope)


@page(['GET','POST'])
def overview(request,scope):
    services.authorize(request.user,scope)
    now=timezone.localdate()
    form=forms.YearForm(request.POST if request.method=='POST' else None,initial={'fiscal_year':now.year+543+(now.month>=10)})
    if request.method=='POST' and form.is_valid():
        try: plan=services.create_plan(request.user,scope,form.cleaned_data['fiscal_year'])
        except (ValidationError,IntegrityError) as exc:errors(form,exc)
        else:return redirect('f04-plan',scope_id=scope.pk,plan_id=plan.pk)
    return render(request,'leadership/overview.html',{'scope':scope,'form':form,'plans':AnnualPlan.objects.filter(scope=scope).annotate(target_count=Count('targets')).order_by('-fiscal_year'),
        'can_roster':can_access(request.user,'population.manage',scope)},status=422 if form.errors else 200)


@page(['GET','POST'])
def master(request,scope,kind,pk=None):
    from django.http import Http404
    if kind not in MASTER:raise Http404
    model,formclass,title=MASTER[kind]
    services.authorize(request.user,scope,roster=kind=='people')
    item=get_object_or_404(model,pk=pk,scope=scope) if pk else None
    initial={k:getattr(item,k) for k in services.EDIT_FIELDS[model]} if item else {}
    form=formclass(request.POST if request.method=='POST' else None,scope=scope,initial=initial)
    if item:
        form.fields['code'].disabled=True;form.fields['reason'].required=True
    if request.method=='POST' and form.is_valid():
        try:services.save_record(request.user,scope,model,{k:form.cleaned_data[k] for k in services.EDIT_FIELDS[model]},pk=pk,reason=form.cleaned_data['reason'])
        except (ValidationError,IntegrityError) as exc:errors(form,exc)
        else:return redirect('f04-master',scope_id=scope.pk,kind=kind)
    return render(request,'leadership/master.html',{'scope':scope,'form':form,'title':title,'kind':kind,'items':model.objects.filter(scope=scope).order_by('code'),'editing':item},status=422 if form.errors else 200)


@page(['GET','POST'])
def plan(request,scope,plan_id):
    services.authorize(request.user,scope)
    plan=scoped_plan(scope,plan_id)
    targets=plan.targets.select_related('person','position__programme').prefetch_related('survey_profiles__binding__collection_round').annotate(eligible_count=Count('eligibility')).order_by('position__code','start_date','created_at')
    error = ''
    if request.method == 'POST':
        from .public_collections import control_plan
        from apps.participation.services import ReceiptError
        try:
            if request.POST.get('confirm') != 'on':
                raise ValidationError('ตรวจรายการและยืนยัน / Review and confirm.')
            control_plan(request.user, scope, plan.pk, request.POST.get('action'), request.POST.get('reason',''))
        except (ValidationError, IntegrityError, ReceiptError) as exc:
            error = ' '.join(exc.messages) if isinstance(exc, ValidationError) else 'ยังดำเนินการไม่ได้ ไม่มีรายการใดถูกเปลี่ยน / No collections changed. Check readiness.'
        else:
            return redirect('f04-plan', scope_id=scope.pk, plan_id=plan.pk)
    from apps.participation.collection_presentation import collection_state, aggregate_state
    bindings = []
    for target in targets:
        for profile in target.survey_profiles.all():
            profile.ui_state = collection_state(profile.binding)
            if profile.intake_method == 'public':
                bindings.append(profile.binding)
    state = aggregate_state(bindings)
    q=request.GET.get('q','').strip()[:100]
    if q:targets=targets.filter(Q(person__name_th__icontains=q)|Q(person__code__icontains=q)|Q(title_th__icontains=q)|Q(position__programme__name_th__icontains=q)|Q(snapshot__person_th__icontains=q)|Q(snapshot__programme_th__icontains=q))
    for t in targets:
        for p in t.survey_profiles.all():
            p.ui_state = collection_state(p.binding)
    return render(request,'leadership/plan.html',{'scope':scope,'plan':plan,'targets':targets,'query':q,'error':error,'state':state,'collection_count':len(bindings),'can_launch': bool(bindings) and all(b.collection_round.status in {'ready','open'} and b.collection_round.close_at > timezone.now() for b in bindings) and state['key'] not in {'open','scheduled'},'can_close':any(b.collection_round.status=='open' for b in bindings),
        'person_count':plan.targets.filter(status__in=['draft','ready']).values('person_id').distinct().count(),
        'active_count':plan.targets.filter(status__in=['draft','ready']).count(),
        'public_enabled':getattr(settings, 'NEXORA_PUBLIC_ASSESSMENTS_ENABLED', False)}, status=422 if error else 200)


@page(['GET','POST'])
def target_edit(request,scope,plan_id,pk=None):
    services.authorize(request.user,scope)
    plan=scoped_plan(scope,plan_id)
    item=get_object_or_404(AnnualTarget,pk=pk,plan=plan,status='draft') if pk else None
    start,end=fiscal_window(plan.fiscal_year)
    initial={k:getattr(item,k) for k in services.EDIT_FIELDS[AnnualTarget]-{'plan'}} if item else {'start_date':start,'last_date':end-timedelta(days=1),'appointment_kind':'substantive'}
    if item:initial['last_date']=item.last_date
    form=forms.TargetForm(request.POST if request.method=='POST' else None,scope=scope,initial=initial)
    if item:form.fields['reason'].required=True
    if request.method=='POST' and form.is_valid():
        data={k:form.cleaned_data[k] for k in services.EDIT_FIELDS[AnnualTarget]-{'plan'}};data['plan']=plan
        try:item=services.save_record(request.user,scope,AnnualTarget,data,pk=pk,reason=form.cleaned_data['reason'])
        except (ValidationError,IntegrityError) as exc:errors(form,exc)
        else:return redirect('f04-target',scope_id=scope.pk,pk=item.pk)
    return form_page(request,scope,form,'ผู้ถูกประเมินและช่วงดำรงตำแหน่ง / Evaluatee and appointment segment',plan=plan,
        notice='หนึ่งคน หนึ่งตำแหน่ง/หลักสูตร หนึ่งช่วงในปีงบประมาณ ใช้ชื่อและวันที่จริงของช่วงนั้น / One person, position/programme and fiscal-year segment.')


@page(['GET','POST'])
def target(request,scope,pk):
    services.authorize(request.user,scope)
    t=get_object_or_404(AnnualTarget.objects.select_related('person','position__programme','plan'),pk=pk,scope=scope)
    can_roster=can_access(request.user,'population.manage',scope)
    public_enabled=getattr(settings, 'NEXORA_PUBLIC_ASSESSMENTS_ENABLED', False)
    form=forms.EligibilityForm(request.POST if request.method=='POST' else None,scope=scope,target=t) if can_roster and t.status=='draft' and not public_enabled else None
    if request.method=='POST':
        services.authorize(request.user,scope,roster=True)
        if public_enabled:
            messages.error(request,'F04 สาธารณะใช้ ST1 และ ST2 โดยไม่เพิ่มรายชื่อผู้ตอบ / Public F04 includes ST1 and ST2 without a respondent roster.')
            return redirect('f04-target',scope_id=scope.pk,pk=pk)
        if form and form.is_valid():
            try:
                with transaction.atomic():
                    for person in form.cleaned_data['people']:
                        services.save_record(request.user,scope,Eligibility,{'target':t,'person':person,'group_code':form.cleaned_data['group_code'],'relationship':form.cleaned_data['relationship']})
            except (ValidationError,IntegrityError) as exc:errors(form,exc)
            else:return redirect('f04-target',scope_id=scope.pk,pk=pk)
    return render(request,'leadership/target.html',{'scope':scope,'target':t,'plan':t.plan,'form':form,'can_roster':can_roster,
        'public_enabled':public_enabled,
        'eligible':t.eligibility.select_related('person').order_by('group_code','person__code') if can_roster else [],
        'eligible_count':t.eligibility.count(),'profiles':t.survey_profiles.select_related('binding__collection_round')},status=422 if form and form.errors else 200)


@page(['GET','POST'])
def action(request,scope,pk,action,eligible_id=None):
    services.authorize(request.user,scope)
    t=get_object_or_404(AnnualTarget,pk=pk,scope=scope)
    if action=='freeze' and getattr(settings, 'NEXORA_PUBLIC_ASSESSMENTS_ENABLED', False):
        return redirect('f04-action',scope_id=scope.pk,pk=pk,action='freeze-public')
    titles={'freeze':'ตรึงผู้ถูกประเมินและรายชื่อผู้เกี่ยวข้อง / Freeze target and related-person roster','split':'เปลี่ยนคนหรือชื่อตำแหน่งระหว่างปี / Split an appointment segment',
        'freeze-public':'ตรึงผู้บริหารสำหรับบุคลากรทุกคน / Freeze leader for all-staff public assessment',
        'exempt':'ยกเว้นรายการร่างพร้อมเหตุผล / Exempt draft target','remove':'ลบผู้ตอบจากรายการร่าง / Remove draft eligibility'}
    if action not in titles:
        from django.http import Http404
        raise Http404
    form=forms.SplitForm(request.POST if request.method=='POST' else None,scope=scope,
        initial={'new_person':t.person,'title_th':t.title_th,'title_en':t.title_en}) if action=='split' else ActionForm(request.POST if request.method=='POST' else None)
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        try:
            if action=='freeze':services.freeze_target(request.user,scope,pk,d['reason'])
            elif action=='freeze-public':services.freeze_target(request.user,scope,pk,d['reason'],public_all_staff=True)
            elif action=='split':services.split_target(request.user,scope,pk,d['change_date'],d['new_person'],d['title_th'],d['title_en'],d['reason'])
            elif action=='exempt':services.exempt_target(request.user,scope,pk,d['reason'])
            else:
                row=get_object_or_404(Eligibility,pk=eligible_id,target=t)
                services.remove_eligibility(request.user,scope,row.pk,d['reason'])
        except (ValidationError,IntegrityError) as exc:errors(form,exc)
        else:return redirect('f04-plan' if action=='split' else 'f04-target',scope_id=scope.pk,**({'plan_id':t.plan_id} if action=='split' else {'pk':t.pk}))
    notice=('การแบ่งช่วงจะปิดรอบที่เปิดอยู่ เก็บคำตอบเดิมไว้ในประวัติ และสร้างสองรายการร่าง ต้องตรวจคำสั่ง ภารกิจ และผู้เกี่ยวข้องก่อนตรึงใหม่ ไม่มีการย้ายคะแนน / Splitting closes open rounds, retains historic answers and creates two drafts for review; scores are not transferred.' if action=='split' else 'ตรวจวันที่ คำสั่ง ภารกิจ และผู้เกี่ยวข้องของช่วงนี้ก่อนยืนยัน / Check dates, appointment reference, responsibilities and related people.')
    if action=='freeze-public':
        notice='ผู้ถูกประเมินคือผู้บริหารในรายการนี้เท่านั้น ผู้ตอบคือทั้ง ST1 และ ST2 ทุกคน ไม่ต้องเพิ่มรายชื่อผู้ตอบ / This record identifies one evaluatee. Both ST1 and ST2 assess every leader without a respondent roster.'
    return form_page(request,scope,form,titles[action],plan=t.plan,target=t,notice=notice)


@page(['GET','POST'])
def generate(request,scope,plan_id):
    services.authorize(request.user,scope,roster=True)
    plan=scoped_plan(scope,plan_id)
    if getattr(settings, 'NEXORA_PUBLIC_ASSESSMENTS_ENABLED', False):
        from .public_collections import StaffCollectionForm, create_staff_collections
        form=StaffCollectionForm(request.POST if request.method=='POST' else None,scope=scope)
        if request.method=='POST' and form.is_valid():
            try:
                rows=create_staff_collections(request.user,scope,plan.pk,form.cleaned_data)
            except (ValidationError,IntegrityError) as exc:errors(form,exc)
            else:
                messages.success(request,f'เตรียมครบ ST1 และ ST2 รวม {len(rows)} รอบ โดยเก็บรอบที่มีอยู่ไว้ ยังไม่เปิดหรือเผยแพร่อัตโนมัติ / Both staff groups prepared; existing rounds retained, no automatic opening or publication.')
                return redirect('f04-plan',scope_id=scope.pk,plan_id=plan.pk)
        sections = [('01','ชื่อรอบและแบบประเมิน / Collection and form',['code','bundle']), ('02','บุคลากรผู้ตอบทั้งสองกลุ่ม / Both staff audiences',['group_codes','count_st1','count_st2']), ('03','ช่วงเวลาและแหล่งอ้างอิง / Schedule and reference',['open_at','due_at','close_at','source_title','source_reference']), ('04','คำชี้แจงและหลักฐาน / Notice and proof',['privacy_notice','label_th','label_en','expires_at','workload','prize'])]
        return render(request,'leadership/public_generate.html',{'scope':scope,'plan':plan,'form':form,'sections':[(n,t,[form[k] for k in keys]) for n,t,keys in sections]},status=422 if form.errors else 200)
    form=forms.CollectionForm(request.POST if request.method=='POST' else None,scope=scope,plan=plan,initial={'owner':request.user})
    if request.method=='POST' and form.is_valid():
        try:rows=services.generate_collections(request.user,scope,[str(t.pk) for t in form.cleaned_data['targets']],form.cleaned_data)
        except (ValidationError,IntegrityError) as exc:errors(form,exc)
        else:
            messages.success(request,f'เตรียมรอบพร้อมแล้ว {len(rows)} รอบ เปิดแต่ละรอบเพื่อออกคำเชิญ / Collections ready; open each to issue invitations.')
            return redirect('f04-plan',scope_id=scope.pk,plan_id=plan.pk)
    return form_page(request,scope,form,'สร้างรอบ F04 ตามผู้เกี่ยวข้อง / Create F04 collections',plan=plan,
        notice='สร้างหนึ่งรอบต่อผู้ถูกประเมิน-ช่วงเวลา-กลุ่มที่มีรายชื่อจริง กดซ้ำจะคืนรอบเดิม ตรวจจำนวนกลุ่มในหน้ารายการก่อนสร้าง / One collection per target segment and eligible group. Repeated requests reuse existing collections.')


@page(['GET','POST'])
def copy(request,scope,plan_id):
    services.authorize(request.user,scope,roster=True)
    plan=scoped_plan(scope,plan_id)
    form=forms.CopyForm(request.POST if request.method=='POST' else None,scope=scope,plan=plan)
    if request.method=='POST' and form.is_valid():
        try:services.copy_previous(request.user,scope,plan.pk,form.cleaned_data['source'].pk)
        except (ValidationError,IntegrityError) as exc:errors(form,exc)
        else:return redirect('f04-plan',scope_id=scope.pk,plan_id=plan.pk)
    return form_page(request,scope,form,'คัดลอกปีก่อนเป็นร่าง / Copy previous year as drafts',plan=plan,
        notice='นำคนล่าสุดของแต่ละตำแหน่งและรายชื่อผู้เกี่ยวข้องมาให้ตรวจใหม่ ต้องยืนยันวันดำรงตำแหน่ง ภารกิจและรายชื่อจริงของปีใหม่ก่อนตรึง / Recheck actual appointments, dates, responsibilities and related people for the new year.')
