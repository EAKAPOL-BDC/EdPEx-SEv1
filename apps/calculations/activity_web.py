from apps.catalog.group_registry import group_display
import uuid
from datetime import datetime
from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from apps.accounts.permissions import require_permission,can_access
from apps.rounds.presentation import collection_listing
from apps.rounds.models import RoundInstrument,PopulationMember
from apps.rounds.web_forms import RoundForm
from apps.rounds.web_services import save_round
from apps.selfassessments.operator_web import page
from .models import ActivityRecord
from . import activities

CATEGORIES=[('T45','เทคโนโลยีสมัยใหม่'),('T46','ดิจิทัล'),('T47S','ความปลอดภัย'),('T47H','อาชีวอนามัย'),('T47E','พลังงาน'),('T48','ประกันคุณภาพ')]

class EntryForm(forms.Form):
    member=forms.ModelChoiceField(label='บุคลากรจากทะเบียน / Staff member',queryset=PopulationMember.objects.none())
    activity_code=forms.CharField(label='รหัสกิจกรรม / Activity code',max_length=100)
    session_code=forms.CharField(label='ครั้งหรือช่วง / Session code',max_length=100)
    title=forms.CharField(label='ชื่อกิจกรรม / Activity title',max_length=300)
    organizer=forms.CharField(label='หน่วยงานผู้จัด / Organizer',max_length=300,required=False)
    location=forms.CharField(label='สถานที่หรือช่องทาง / Location or channel',max_length=300,required=False)
    knowledge=forms.CharField(label='ความรู้หรือทักษะที่ได้รับ / Learning gained',max_length=2000,required=False,widget=forms.Textarea(attrs={'rows':2}))
    application=forms.CharField(label='งานที่จะนำไปใช้ / Intended application',max_length=2000,required=False,widget=forms.Textarea(attrs={'rows':2}))
    followup=forms.CharField(label='ผลติดตามการนำไปใช้ 30–90 วัน และหลักฐานถ้ามี / Application follow-up and evidence after 30–90 days',max_length=3000,required=False,widget=forms.Textarea(attrs={'rows':3}))
    starts_at=forms.DateTimeField(label='เริ่มกิจกรรม / Starts',widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M',attrs={'type':'datetime-local'}))
    ends_at=forms.DateTimeField(label='จบกิจกรรม / Ends',widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M',attrs={'type':'datetime-local'}))
    training_hours=forms.DecimalField(label='ชั่วโมงอบรมจริง / Training hours',min_value=0,max_digits=8,decimal_places=2)
    visit_hours=forms.DecimalField(label='ชั่วโมงดูงานจริง / Visit hours',min_value=0,max_digits=8,decimal_places=2,initial=0)
    external_visit=forms.BooleanField(label='ศึกษาดูงานภายนอก / External study visit',required=False)
    categories=forms.MultipleChoiceField(label='หมวดที่เกี่ยวข้อง / Categories',choices=CATEGORIES,widget=forms.CheckboxSelectMultiple,required=False)
    evidence_reference=forms.CharField(label='เลขที่หรือที่เก็บหลักฐาน / Evidence reference',max_length=2000,required=False,widget=forms.Textarea(attrs={'rows':2}))
    status=forms.ChoiceField(label='บันทึกเป็น / Save as',choices=[('draft','ร่าง / Draft'),('submitted','ส่งตรวจ / Submit')])
    reason=forms.CharField(label='เหตุผลการบันทึกหรือแก้ไข / Reason',max_length=2000,widget=forms.Textarea(attrs={'rows':2}))
    expected_revision=forms.IntegerField(widget=forms.HiddenInput,initial=0)
    def __init__(self,*args,selected,record=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['member'].queryset=PopulationMember.objects.filter(snapshot_id=selected.collection_round.population_snapshot_id,group__code__in=['ST1','ST2'])
        self.fields['member'].label_from_instance=lambda m:m.eligible_unit_key+' · '+group_display(m.group.code, m.group.label)
        if record:
            for key in ['member','activity_code','session_code']:self.fields[key].disabled=True

class ReviewForm(forms.Form):
    outcome=forms.ChoiceField(label='ผลตรวจ / Outcome',choices=[('accepted','ตรวจรับ / Accept'),('revision_requested','ขอแก้ไข / Return'),('rejected','ไม่รับ / Reject')])
    evidence_confirmed=forms.BooleanField(label='ตรวจหลักฐานและชั่วโมงแล้ว / Evidence and hours verified',required=False)
    reason=forms.CharField(label='เหตุผลผลตรวจ / Review reason',max_length=2000,widget=forms.Textarea(attrs={'rows':2}))
    exception_reason=forms.CharField(label='คำชี้แจงกรณีเวลาซ้อนหรือชั่วโมงสูง / Overlap or unusual hours explanation',max_length=2000,required=False,widget=forms.Textarea(attrs={'rows':2}))
    expected_revision=forms.IntegerField(widget=forms.HiddenInput)


def selected_in(scope,pk):
    return get_object_or_404(RoundInstrument.objects.select_related('collection_round__scope__organization','collection_round__period','instrument_version__instrument'),pk=pk,collection_round__scope=scope,instrument_version__instrument__code='F05')

@page(['GET'])
def overview(request,scope):
    require_permission(request.user,'source.manage',scope)
    selected=RoundInstrument.objects.filter(collection_round__scope=scope,instrument_version__instrument__code='F05',survey_profile__isnull=True).select_related('collection_round','instrument_version')
    listing=collection_listing(request,selected,bindings=True)
    return render(request,'calculations/activity_list.html',dict(scope=scope,selected=listing['page'],listing=listing,can_setup=can_access(request.user,'round.manage',scope)))

@page(['GET','POST'])
def create(request,scope):
    require_permission(request.user,'round.manage',scope)
    return redirect('survey-new',scope_id=scope.pk)
    form=RoundForm(request.POST or None,scope=scope,instrument_code='F05',initial={'owner':request.user.pk})
    if request.method=='POST' and form.is_valid():
        try:r=save_round(request.user,scope,form.cleaned_data,instrument_code='F05')
        except (ValidationError,IntegrityError):form.add_error(None,'ตรวจชื่อรอบ เวลา ช่วงรายงาน และแบบฟอร์ม / Check round settings.')
        else:return redirect('round-detail',scope_id=scope.pk,round_id=r.pk)
    return render(request,'portal/manage_form.html',dict(scope=scope,form=form,title='สร้างรอบ F05 / Create F05 round'))

@page(['GET','POST'])
def collection(request,scope,selected_id):
    require_permission(request.user,'source.manage',scope)
    selected=selected_in(scope,selected_id)
    if request.method=='POST':
        require_permission(request.user,'calculation.run',scope)
        if request.POST.get('confirm')!='yes':
            messages.error(request,'กรุณายืนยันก่อนคำนวณ / Confirm before calculating.')
            return redirect('activity-collection',scope_id=scope.pk,selected_id=selected.pk)
        try:
            receipt=activities.calculate(request.user,selected.pk,timezone.now(),str(uuid.uuid4()))
        except ValidationError:
            messages.error(request,'ยังคำนวณไม่ได้ ตรวจว่าปิดรอบแล้วและข้อมูลครบ / Close the round and check sources before calculation.')
        else:return redirect('operator-run',scope_id=scope.pk,run_id=receipt['run_id'])
    records=[]
    for record in selected.activity_records.select_related('member').prefetch_related('revisions').order_by('activity_code','session_code'):
        latest=max(record.revisions.all(),key=lambda v:v.number,default=None)
        records.append({'record':record,'latest':latest})
    return render(request,'calculations/activity_collection.html',dict(scope=scope,selected=selected,records=records,
        can_manage=can_access(request.user,'round.manage',scope),
        can_entry=False,
        can_calculate=selected.collection_round.status in {'closed','review','approved'} and can_access(request.user,'calculation.run',scope),runs=selected.stored_calculations.select_related('run').order_by('-created_at')))

@page(['GET','POST'])
def entry(request,scope,selected_id,record_id=None):
    require_permission(request.user,'source.manage',scope)
    selected=selected_in(scope,selected_id)
    record=get_object_or_404(ActivityRecord,pk=record_id,round_instrument=selected) if record_id else None
    latest=record.revisions.order_by('-number').first() if record else None
    initial=dict(latest.payload,member=record.member_id,activity_code=record.activity_code,session_code=record.session_code,expected_revision=latest.number,status='draft') if latest else {}
    if latest:
        for key in ['starts_at','ends_at']: initial[key]=timezone.localtime(datetime.fromisoformat(initial[key]))
    reviewing=request.method=='POST' and request.POST.get('action')=='review'
    form=EntryForm(request.POST if request.method=='POST' and not reviewing else None,selected=selected,record=record,initial=initial)
    review=ReviewForm(request.POST if reviewing else None,initial={'expected_revision':latest.number if latest else 0})
    for field in form.fields.values():field.disabled=True
    if request.method=='POST':
        target=review if reviewing else form
        if target.is_valid():
            try:
                data=target.cleaned_data
                if reviewing:
                    if not record:raise ValidationError('No entry')
                    activities.review_entry(request.user,record.pk,**data)
                else:
                    payload={k:data[k] for k in ['title','external_visit','categories','evidence_reference','organizer','location','knowledge','application','followup']}
                    payload.update({k:data[k].isoformat() for k in ['starts_at','ends_at']})
                    payload.update({k:str(data[k]) for k in ['training_hours','visit_hours']})
                    activities.save_entry(request.user,selected.pk,**{k:data[k] for k in ['member','activity_code','session_code','status','reason','expected_revision']},payload=payload,record_id=record_id)
            except ValidationError as exc:target.add_error(None,exc)
            except IntegrityError:target.add_error(None,'รหัสกิจกรรม ครั้ง และบุคลากรซ้ำ / Duplicate activity/session/person.')
            else:return redirect('activity-collection',scope_id=scope.pk,selected_id=selected.pk)
    return render(request,'calculations/activity_entry.html',dict(scope=scope,selected=selected,form=form,review_form=review,
        can_review=False,
        history=record.revisions.order_by('-number') if record else [],record=record))
