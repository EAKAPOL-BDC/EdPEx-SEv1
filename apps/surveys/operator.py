import uuid
from django import forms
from django.contrib import messages
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core import signing
from django.db import transaction, IntegrityError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone
from apps.accounts.permissions import require_permission,can_access
from apps.catalog.management_web import errors
from apps.rounds.presentation import collection_listing
from apps.rounds.models import CollectionRound,RoundInstrument,PopulationMember
from apps.rounds.services import create_record,transition_round,update_record
from apps.rounds.web import form_page
from apps.rounds.web_forms import ActionForm
from apps.selfassessments.operator_web import page,require_any,run_metadata,RESULT_ACTIONS
from apps.calculations.models import CalculationRun
from .models import SurveyProfile,Invitation
from .forms import SurveyRoundForm
from . import services,calculations
from .validation import validate_schema
from .calculation_presentation import calculation_guidance
from apps.accounts.workflow import collection_links

PROFILE_FIELDS=('group_code','counting_unit','context_th','context_en','assessor_role','study_options')


@transaction.atomic
def save_round(actor,scope,data,selected=None,*,data_kind='real'):
    require_permission(actor,'round.manage',scope)
    values={k:data[k] for k in ('code','owner','open_at','due_at','close_at','privacy_notice')}
    if selected:
        r=CollectionRound.objects.select_for_update().get(pk=selected.collection_round_id,scope=scope)
        if r.status!='draft':raise ValidationError('แก้ไขได้เฉพาะรอบร่าง / Only draft rounds can be edited.')
        # Avoid silently changing group/unit after a population was created.
        p=selected.survey_profile
        if r.population_snapshots.exists() and any(data[k]!=getattr(p,k) for k in ('group_code','counting_unit')):
            raise ValidationError('มีทะเบียนผู้ตอบแล้ว สร้างรอบใหม่เมื่อต้องเปลี่ยนกลุ่ม / Create a new round to change a group with an existing roster.')
        update_record(actor,r,reason=data['reason'],schedule_confirmed=True,**values)
    else:
        b=data['bundle']
        if b.status!='published' or b.instrument_version.status!='published' or b.instrument_version.instrument.scope_id!=scope.pk or b.instrument_version.instrument.code not in {'F01','F02','F03','F04','F05','F06'}:
            raise ValidationError('เลือกแบบสำรวจที่เผยแพร่แล้ว / Select a published survey.')
        if b.instrument_version.source_metadata.get('synthetic_only') and data_kind!='synthetic':
            raise ValidationError('แบบฟอร์มจำลองใช้เก็บข้อมูลจริงไม่ได้ / Simulation-only form.')
        r=create_record(actor,CollectionRound,scope=scope,period=data['period'],data_kind=data_kind,**values)
        selected=create_record(actor,RoundInstrument,collection_round=r,instrument_version=b.instrument_version,translation_bundle=b,context='survey-'+uuid.uuid4().hex)
        p=SurveyProfile(binding=selected)
    if p.annual_target_id and any(data[k]!=getattr(p,k) for k in PROFILE_FIELDS):
        raise ValidationError('บริบทมาจากทะเบียน F04 ที่ตรึงแล้ว แก้ได้เฉพาะวันรับคำตอบ ผู้รับผิดชอบและคำชี้แจง / The registered F04 context is frozen.')
    for k in PROFILE_FIELDS:setattr(p,k,data[k])
    p.save()
    validate_schema(p)
    require_permission(actor,'round.manage',scope)
    return selected


def selected_for(scope,selected_id):
    return get_object_or_404(RoundInstrument.objects.select_related('collection_round__scope','collection_round__period','survey_profile','instrument_version__instrument','translation_bundle'),pk=selected_id,collection_round__scope=scope,survey_profile__isnull=False)


@page(['GET'])
def overview(request,scope):
    require_any(request.user,scope,('round.manage',*RESULT_ACTIONS))
    selected=RoundInstrument.objects.filter(collection_round__scope=scope,survey_profile__isnull=False).select_related('collection_round','instrument_version__instrument','survey_profile').order_by('-created_at')
    batches = []
    if getattr(settings, 'NEXORA_PUBLIC_ASSESSMENTS_ENABLED', False) and can_access(request.user, 'round.manage', scope) and can_access(request.user, 'population.manage', scope):
        from apps.participation.models import AssessmentBatch
        batches = AssessmentBatch.objects.filter(scope=scope).prefetch_related('items__binding__collection_round__period','items__binding__survey_profile','items__binding__public_collection','items__binding__instrument_version__instrument').order_by('-created_at')
        selected = selected.filter(batch_item__isnull=True)
    if getattr(settings, 'NEXORA_PUBLIC_ASSESSMENTS_ENABLED', False) and can_access(request.user, 'round.manage', scope) and can_access(request.user, 'population.manage', scope):
        from apps.participation.collection_presentation import aggregate_state, collection_state
        from django.urls import reverse
        entries = []
        for batch in batches:
            bindings = [item.binding for item in batch.items.all()]
            if not bindings: continue
            first = bindings[0]
            entries.append({'title':batch.title,'state':aggregate_state(bindings),'code':first.instrument_version.instrument.code,
                'year':first.collection_round.period.reporting_year_be,'kind':first.collection_round.data_kind,
                'created':batch.created_at,'count':len(bindings),'groups':sorted({b.survey_profile.group_code for b in bindings}),
                'url':reverse('assessment-batch-manage',args=[scope.pk,batch.pk]),'id':str(batch.pk)[:8]})
        for binding in selected:
            r=binding.collection_round
            entries.append({'title':r.code,'state':collection_state(binding),'code':binding.instrument_version.instrument.code,
                'year':r.period.reporting_year_be,'kind':r.data_kind,'created':r.created_at,'count':1,'groups':[binding.survey_profile.group_code],
                'url':reverse('survey-collection',args=[scope.pk,binding.pk]),'id':str(binding.pk)[:8]})
        query=request.GET.get('q','').strip()[:100];status=request.GET.get('status','');year=request.GET.get('year','');kind=request.GET.get('kind','')
        entries=[e for e in entries if (not query or query.casefold() in e['title'].casefold() or query.casefold() in e['id']) and (not status or status==e['state']['key']) and (not year or str(e['year'])==year) and (not kind or kind==e['kind'])]
        entries.sort(key=lambda e:e['created'],reverse=True)
        page_obj=Paginator(entries,18).get_page(request.GET.get('page'))
        filters=request.GET.copy();filters.pop('page',None)
        return render(request,'participation/collection_list.html',{'scope':scope,'entries':page_obj,'total':len(entries),'query':query,'status':status,'year':year,'kind':kind,'filters':filters.urlencode(),
            'status_choices':[('open','เปิดรับอยู่ / Open'),('scheduled','รอวันเปิด / Scheduled'),('ready','ยังไม่เปิดสาธารณะ / Not public yet'),('closed','ปิดรับแล้ว / Closed'),('draft','ฉบับร่าง / Draft'),('mixed','สถานะต่างกัน / Mixed')]})
    listing=collection_listing(request,selected,bindings=True)
    menu_actions={a for a in ('round.manage','population.manage','source.manage',*RESULT_ACTIONS) if can_access(request.user,a,scope)}
    for item in listing['page']:
        item.workflow=collection_links(request.user,item,menu_actions)
    return render(request,'surveys/list.html',{'scope':scope,'listing':listing,'items':listing['page'],'batches':batches,'can_manage':can_access(request.user,'round.manage',scope)})


@page(['GET','POST'])
def create(request,scope):
    require_permission(request.user,'round.manage',scope)
    if getattr(settings, 'NEXORA_PUBLIC_ASSESSMENTS_ENABLED', False):
        from apps.participation.batches import setup
        return setup(request, scope_id=scope.pk)
    form=SurveyRoundForm(request.POST if request.method=='POST' else None,scope=scope,initial={'owner':request.user,'period':request.GET.get('period')})
    if request.method=='POST' and form.is_valid():
        try:selected=save_round(request.user,scope,form.cleaned_data)
        except (ValidationError,IntegrityError) as exc:errors(form,exc)
        else:return redirect('round-detail',scope_id=scope.pk,round_id=selected.collection_round_id)
    return form_page(request,scope,form,'สร้างรอบแบบสำรวจ F01–F06 / Create anonymous survey round', f04_registry=True, notice='แยกรอบตามบริบท กลุ่ม และหน่วยนับ เพื่อไม่รวมบุคคลกับองค์กร / One context, group and counting unit per round.',can_period=can_access(request.user,'calendar.manage',scope),period_return_to='survey')


@page(['GET','POST'])
def collection(request,scope,selected_id):
    require_any(request.user,scope,('round.manage',*RESULT_ACTIONS))
    selected=selected_for(scope,selected_id); r=selected.collection_round
    manage=can_access(request.user,'round.manage',scope)
    population=manage and can_access(request.user,'population.manage',scope)
    from apps.participation.models import AccessPool
    unlinked=(getattr(settings,'NEXORA_PARTICIPATION_ENABLED',False) and getattr(settings,'NEXORA_UNLINKED_ACCESS_ENABLED',False)
              and AccessPool.objects.filter(binding=selected).exists())
    workflow=collection_links(request.user,selected)
    if selected.survey_profile.intake_method == 'public':
        if request.method != 'GET':
            from django.http import HttpResponse
            return HttpResponse('ใช้หน้าจัดการประเมินสาธารณะ / Use public assessment management.', status=409)
        if population:
            return redirect('public-assessment-manage', scope_id=scope.pk, selected_id=selected.pk)
    if workflow.get('results') and request.method=='GET':
        return redirect(workflow['primary'])
    form=ActionForm(request.POST if request.method=='POST' else None)
    edit_form=None
    if manage and r.status=='draft':
        initial={k:getattr(r,k) for k in ('code','period','owner','open_at','due_at','close_at','privacy_notice')}
        initial.update(bundle=selected.translation_bundle,**{k:getattr(selected.survey_profile,k) for k in PROFILE_FIELDS})
        edit_form=SurveyRoundForm(request.POST if request.POST.get('action')=='edit' else None,scope=scope,editing=True,initial=initial)
    if edit_form and selected.survey_profile.annual_target_id:
        for key in PROFILE_FIELDS:
            edit_form.fields[key].disabled=True
    if request.method=='POST':
        require_permission(request.user,'round.manage',scope)
        action=request.POST.get('action')
        try:
            if workflow.get('results'):
                raise ValidationError('กรุณาใช้ศูนย์คำเชิญและควบคุมรอบเพื่อดำเนินการ / Use the invitation centre and its collection controls.')
            if action=='edit' and edit_form and edit_form.is_valid():
                save_round(request.user,scope,edit_form.cleaned_data,selected)
            elif action in {'open','closed'} and form.is_valid():
                transition_round(request.user,r,action,reason=form.cleaned_data['reason'])
            else:raise ValidationError('ตรวจแบบฟอร์มและการยืนยัน / Check the form and confirmation.')
        except (ValidationError,IntegrityError) as exc:errors(edit_form if action=='edit' and edit_form else form,exc)
        else:
            messages.success(request,'บันทึกแล้ว / Saved.')
            return redirect('survey-collection',scope_id=scope.pk,selected_id=selected.pk)
    members=PopulationMember.objects.filter(snapshot_id=r.population_snapshot_id).select_related('group').order_by('eligible_unit_key') if population and r.population_snapshot_id else PopulationMember.objects.none()
    roster=Paginator(members,30).get_page(request.GET.get('page'))
    invitations={i.member_id:i for i in Invitation.objects.filter(binding=selected,member__in=roster.object_list)}
    rows=[{'member':m,'invitation':invitations.get(m.pk)} for m in roster]
    runs=CalculationRun.objects.filter(stored_source__round_instrument=selected).order_by('-created_at')[:20]
    if getattr(settings, 'NEXORA_PUBLIC_ASSESSMENTS_ENABLED', False) and selected.survey_profile.intake_method != 'public':
        return render(request, 'participation/batch_source.html', {'scope': scope, 'selected': selected, 'round': r,
            'edit_form': edit_form, 'manage': manage, 'workflow': workflow}, status=422 if request.method == 'POST' else 200)
    return render(request,'surveys/collection.html',{'scope':scope,'selected':selected,'round':r,'rows':rows,'roster':roster,'form':form,'edit_form':edit_form,
        'manage':manage,'population':population,'unlinked':unlinked,'workflow':collection_links(request.user,selected),'can_invite':population and r.status in {'ready','open'},
        'can_calculate':can_access(request.user,'calculation.run',scope) and r.status=='closed',
        'spent':Invitation.objects.filter(binding=selected,spent=True).count(), 'total':members.count() if population else None,
        'runs':[run_metadata(run) for run in runs]},status=422 if request.method=='POST' else 200)


@page(['GET','POST'])
def invite(request,scope,selected_id,member_id):
    selected=selected_for(scope,selected_id);services.require_manager(request.user,selected)
    member=get_object_or_404(PopulationMember,pk=member_id,snapshot_id=selected.collection_round.population_snapshot_id)
    form=ActionForm(request.POST if request.method=='POST' else None)
    if request.method=='POST' and form.is_valid():
        try:
            action=request.POST.get('action')
            if action not in {'issue','revoke'}:raise ValidationError('Invalid invitation action.')
            raw=services.issue(request.user,selected.pk,member.pk,revoke=action=='revoke')
        except (ValidationError,IntegrityError) as exc:errors(form,exc)
        else:
            response=render(request,'surveys/invitation.html',{'scope':scope,'selected':selected,'member':member,'code':raw,'done':True})
            response['Referrer-Policy']='no-referrer'
            return response
    return render(request,'surveys/invitation.html',{'scope':scope,'selected':selected,'member':member,'form':form},status=422 if form.is_bound and form.errors else 200)


@page(['GET','POST'])
def calculate(request,scope,selected_id):
    selected=selected_for(scope,selected_id);require_permission(request.user,'calculation.run',scope)
    guidance=calculation_guidance(selected)
    form=ActionForm(request.POST if request.method=='POST' else None)
    form.fields['reason'].widget=forms.Textarea(attrs={'rows':3,'aria-describedby':'calculation-reason-help'})
    preview=None;token='';preview_cutoff=None
    if request.method=='POST' and form.is_valid():
        try:
            if not guidance['ready']:
                raise ValidationError('ยังคำนวณไม่ได้ กรุณาตรวจรายการความพร้อม / Calculation unavailable. Resolve the readiness checks.')
            token=request.POST.get('preview','')
            if token:
                data=signing.loads(token,salt='survey-calculation',max_age=1800)
                if data['actor']!=str(request.user.pk) or data['selected']!=str(selected.pk):raise ValidationError('Preview belongs to another operator/round.')
                from datetime import datetime
                cutoff=datetime.fromisoformat(data['cutoff'])
                fresh=calculations.calculate(request.user,selected.pk,cutoff,data['key'],True)
                if fresh['input_hash']!=data['hash']:raise ValidationError('Source changed. Preview again.')
                receipt=calculations.calculate(request.user,selected.pk,cutoff,data['key'])
                return redirect('operator-run',scope_id=scope.pk,run_id=receipt['run_id'])
            cutoff=timezone.now();key=str(uuid.uuid4())
            preview=calculations.calculate(request.user,selected.pk,cutoff,key,True)
            preview_cutoff=cutoff
            token=signing.dumps({'actor':str(request.user.pk),'selected':str(selected.pk),'cutoff':cutoff.isoformat(),'key':key,'hash':preview['input_hash']},salt='survey-calculation')
        except signing.BadSignature:
            errors(form,ValidationError('ตัวอย่างผลหมดอายุหรือใช้ไม่ได้ กรุณาตรวจความพร้อมใหม่ / This preview expired or is invalid. Preview the calculation again.'))
            token=''
        except ValidationError as exc:
            errors(form,exc);token=''
    return render(request,'surveys/calculate.html',{'scope':scope,'selected':selected,'form':form,'preview':preview,'token':token,'preview_cutoff':preview_cutoff,**guidance},status=422 if form.is_bound and form.errors else 200)
