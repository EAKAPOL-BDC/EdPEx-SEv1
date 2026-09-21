"""Create a synthetic F01 collection from a published, pinned test template."""
import uuid
from django import forms
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError
from django.http import Http404
from django.shortcuts import render, redirect
from django.utils import timezone
from apps.accounts.permissions import require_permission
from apps.rounds.models import CollectionRound
from apps.rounds.services import transition_round
from apps.surveys.operator import selected_for, save_round
from apps.surveys.services import require_manager
from apps.selfassessments.operator_web import page
from . import admission, services
from .models import ReceiptPolicy
from .operator import LocalizedForm, secure

SALT='nexora.collection.setup.v1'


def date_field(label):
    return forms.DateTimeField(label=label,widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M',attrs={'type':'datetime-local'}))


class SetupForm(LocalizedForm):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        from .setup_guidance import attach_guidance
        attach_guidance(self)

    code=forms.CharField(max_length=80,label='ชื่อรอบทดสอบใหม่ / New test collection name')
    context_th=forms.CharField(max_length=1200,label='บริบทภาษาไทย / Thai context')
    context_en=forms.CharField(max_length=1200,label='บริบทภาษาอังกฤษ / English context')
    open_at=date_field('เปิดรับคำตอบ / Opens')
    due_at=date_field('กำหนดส่ง / Due')
    close_at=date_field('ปิดรับคำตอบ / Closes')
    count=forms.IntegerField(min_value=1,max_value=100000,label='จำนวนสิทธิ์ทั้งหมด / Total invitation capacity')
    source_title=forms.CharField(max_length=500,label='ชื่อหลักฐานจำนวนรวม / Aggregate evidence title')
    source_reference=forms.CharField(max_length=3000,label='เลขอ้างอิงหลักฐานจำนวนรวม (ไม่ใส่รายชื่อ) / Aggregate evidence reference (no personal roster)')
    privacy_notice=forms.CharField(max_length=15000,label='คำชี้แจงการใช้ข้อมูลของรอบ / Collection data-use notice',widget=forms.Textarea(attrs={'rows':4}))
    label_th=forms.CharField(max_length=200,label='ชื่อกิจกรรมบนหลักฐานภาษาไทย / Thai receipt activity label')
    label_en=forms.CharField(max_length=200,label='ชื่อกิจกรรมบนหลักฐานภาษาอังกฤษ / English receipt activity label')
    expires_at=date_field('หลักฐานใช้สอบทานได้ถึง / Receipt verification expires')
    workload=forms.BooleanField(required=False,label='รองรับการตรวจภาระงานในอนาคต / Allow future workload verification')
    prize=forms.BooleanField(required=False,label='รองรับการตรวจสิทธิ์รางวัลหลังปิดรอบ / Allow reward verification after collection closes')
    setup_stamp=forms.CharField(max_length=1000,widget=forms.HiddenInput)
    confirm=forms.BooleanField(label='ตรวจข้อมูลแล้ว และยืนยันว่าเป็นรอบทดสอบด้วยข้อมูลสมมุติ / I reviewed the settings; this is a synthetic test collection')

    def clean(self):
        data=super().clean()
        start,due,end=(data.get(k) for k in ('open_at','due_at','close_at'))
        if start and due and end and not (start<=due<=end and start<end):
            self.add_error('close_at','เรียงวันเปิด ≤ กำหนดส่ง ≤ วันปิด และวันปิดต้องหลังวันเปิด / Use opens ≤ due ≤ closes, with closes later than opens.')
        if end and end<=timezone.now():self.add_error('close_at','วันปิดต้องอยู่ในอนาคต / Closing must be in the future.')
        expiry=data.get('expires_at')
        if expiry and end and expiry<=end:self.add_error('expires_at','หลักฐานต้องหมดอายุหลังวันปิดรอบ / Receipt expiry must follow collection close.')
        if not data.get('workload') and not data.get('prize'):
            self.add_error('workload','เลือกวัตถุประสงค์หลักฐานอย่างน้อยหนึ่งข้อ / Select at least one receipt purpose.')
        return data


def check_source(actor,binding):
    admission.enabled()
    require_manager(actor,binding)
    require_permission(actor,'source.manage',binding.collection_round.scope)
    if (binding.collection_round.data_kind!='synthetic' or binding.instrument_version.instrument.code!='F01'
        or binding.survey_profile.group_code!='C1' or binding.translation_bundle.status!='published'
        or binding.instrument_version.status!='published'
        or not ReceiptPolicy.objects.filter(binding=binding,realm='test').exists()):
        raise services.ReceiptError('synthetic_f01_template_required',404)


@transaction.atomic
def create_collection(actor,source,data):
    # Serialize same-template creation and replay checks; creation is all-or-nothing.
    CollectionRound.objects.select_for_update().get(pk=source.collection_round_id)
    source=selected_for(source.collection_round.scope,source.pk)
    check_source(actor,source)
    stamp=signing.loads(data['setup_stamp'],salt=SALT,max_age=3600)
    if stamp.get('actor')!=str(actor.pk) or stamp.get('source')!=str(source.pk):raise signing.BadSignature
    nonce=uuid.UUID(stamp['nonce'])
    activity='f01-setup-'+nonce.hex
    scope=source.collection_round.scope
    if ReceiptPolicy.objects.filter(binding__collection_round__scope=scope,activity_code=activity).exists():
        raise services.ReceiptError('setup_already_completed',409)
    values={k:data[k] for k in ('code','context_th','context_en','open_at','due_at','close_at','privacy_notice')}
    values.update(owner=actor,period=source.collection_round.period,bundle=source.translation_bundle,
                  group_code='C1',counting_unit='person',assessor_role='',study_options=source.survey_profile.study_options)
    binding=save_round(actor,scope,values,data_kind='synthetic')
    admission.prepare_population(actor,binding.pk,data['count'],source_title=data['source_title'],source_reference=data['source_reference'])
    services.configure_policy(actor,binding.pk,activity_code=activity,label_th=data['label_th'],label_en=data['label_en'],
                              expires_at=data['expires_at'],workload=data['workload'],prize=data['prize'],realm='test')
    admission.configure(actor,binding.pk,data['count'])
    transition_round(actor,binding.collection_round,'ready',reason='Configured synthetic aggregate-only collection via setup screen')
    return binding


@page(['GET','POST'])
def setup(request,scope,selected_id):
    source=selected_for(scope,selected_id)
    try:check_source(request.user,source)
    except services.ReceiptError:raise Http404 from None
    from datetime import timedelta
    now=timezone.localtime().replace(second=0,microsecond=0)
    initial={'open_at':now,'due_at':now+timedelta(days=7),'close_at':now+timedelta(days=8),
             'expires_at':now+timedelta(days=38),'count':5,
             'setup_stamp':signing.dumps({'actor':str(request.user.pk),'source':str(source.pk),'nonce':str(uuid.uuid4())},salt=SALT)}
    editing=getattr(request,'_confirmation_edit',False)
    values=request.POST.copy() if request.method=='POST' else None
    if editing:values['setup_stamp']=initial['setup_stamp']
    form=SetupForm(values,initial=initial)
    status=200
    if request.method=='POST' and not editing:
        status=422
        if form.is_valid():
            try:binding=create_collection(request.user,source,form.cleaned_data)
            except (signing.BadSignature,KeyError,ValueError):
                form.add_error(None,'หน้านี้หมดอายุหรือไม่ตรงกับบัญชี กรุณาเปิดใหม่ / This setup page expired or belongs to another account. Open it again.');status=409
            except services.ReceiptError as exc:
                form.add_error(None,'สร้างรอบไม่ได้ หรือคำขอนี้สร้างสำเร็จแล้ว ตรวจรายการรอบก่อนทำซ้ำ / Setup unavailable or already completed. Check the collection list before retrying.');status=exc.status
            except (ValidationError,IntegrityError):
                form.add_error(None,'ตรวจชื่อรอบไม่ให้ซ้ำ ข้อมูลปี แบบฟอร์ม และกำหนดเวลา / Check the unique collection name, reporting period, form and schedule.')
            else:return redirect('participation-manage',scope_id=scope.pk,selected_id=binding.pk)
    groups=[('01','ข้อมูลรอบและบริบท / Collection and context',['code','context_th','context_en']),
            ('02','ช่วงเวลาและจำนวนสิทธิ์ / Schedule and capacity',['open_at','due_at','close_at','count','source_title','source_reference']),
            ('03','ข้อมูลและหลักฐานการเข้าร่วม / Data use and participation proof',['privacy_notice','label_th','label_en','expires_at','workload','prize'])]
    return secure(render(request,'participation/setup.html',{'scope':scope,'selected':source,'form':form,
                         'groups':[(n,title,[form[k] for k in keys]) for n,title,keys in groups]},status=status))
