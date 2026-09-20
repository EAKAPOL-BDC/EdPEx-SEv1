from functools import wraps
from django import forms
from django.contrib import messages
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError,transaction
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone
from django.utils.crypto import salted_hmac
from apps.accounts.models import Role
from apps.accounts.permissions import require_permission
from apps.rounds.web import form_page
from apps.selfassessments.operator_web import page
from apps.surveys.web import public_page
from apps.surveys.services import throttle
from .models import AccessRequest,RegistrationPolicy,Notification
from . import access

class RequestForm(forms.Form):
    full_name=forms.CharField(label='ชื่อและนามสกุล / Full name',max_length=200)
    email=forms.EmailField(label='อีเมลที่คุณใช้งานได้ / Your email address',max_length=254)
    affiliation=forms.CharField(label='หน่วยงานหรือความเกี่ยวข้อง / Organization or affiliation',max_length=200)
    purpose=forms.CharField(label='ต้องการใช้ระบบเพื่ออะไร / Purpose of access',max_length=1000,widget=forms.Textarea(attrs={'rows':3}))
    privacy_ack=forms.BooleanField(label='ฉันอ่านคำชี้แจงการใช้ข้อมูลเพื่อจัดการบัญชีแล้ว / I have read the account privacy notice')

class CodeForm(forms.Form):
    code=forms.CharField(label='รหัสจากอีเมล / Code from your email',max_length=100,min_length=30,widget=forms.PasswordInput(attrs={'autocomplete':'off'}))
    confirm=forms.BooleanField(label='ยืนยันดำเนินการ / Confirm')

class ActivateForm(CodeForm):
    confirm=forms.BooleanField(label='ฉันอ่านคำชี้แจงการใช้ข้อมูลในอีเมลแล้ว และยืนยันเปิดบัญชี / I have read the emailed privacy notice and confirm activation')
    password1=forms.CharField(label='ตั้งรหัสผ่านใหม่ อย่างน้อย 15 ตัวอักษร / New password, at least 15 characters',max_length=128,widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}))
    password2=forms.CharField(label='พิมพ์รหัสผ่านใหม่อีกครั้ง / Repeat your password',max_length=128,widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}))
    def clean(self):
        d=super().clean()
        if d.get('password1')!=d.get('password2'):self.add_error('password2','รหัสผ่านไม่ตรงกัน / Passwords do not match.')
        return d

class DecisionForm(forms.Form):
    outcome=forms.ChoiceField(label='ผลพิจารณา / Decision',choices=[('approved','อนุมัติ / Approve'),('rejected','ไม่อนุมัติ / Reject')])
    role=forms.ModelChoiceField(label='บทบาทที่จะให้ / Role to grant',queryset=Role.objects.all(),required=False)
    active_until=forms.DateTimeField(label='สิทธิ์สิ้นสุดเมื่อใด (เว้นว่างหากไม่กำหนด) / Access expiry (optional)',required=False,widget=forms.DateTimeInput(attrs={'type':'datetime-local'},format='%Y-%m-%dT%H:%M'))
    mode=forms.ChoiceField(label='วิธีเปิดบัญชี / Activation method',choices=[('link','ลิงก์ตั้งรหัสผ่าน ใช้ครั้งเดียว (แนะนำ) / One-use link (recommended)'),('temporary','รหัสผ่านชั่วคราวทางอีเมล / Temporary activation password')],help_text='รหัสชั่วคราวหมดอายุใน 1 ชั่วโมง ต้องตั้งรหัสผ่านใหม่ก่อนเข้าระบบ อีเมลที่ถูกเข้าถึงอาจทำให้ผู้อื่นเปิดบัญชีแทนได้ / Email access can expose an activation secret.')
    reason=forms.CharField(label='เหตุผลพิจารณา / Decision reason',max_length=1000,widget=forms.Textarea(attrs={'rows':2}))

class AdminForm(RequestForm,DecisionForm):
    outcome=None

class PolicyForm(forms.ModelForm):
    class Meta:
        model=RegistrationPolicy
        fields=['enabled','privacy_notice','privacy_version','contact','retention_days']
        labels={'enabled':'เปิดแบบฟอร์มขอใช้งานออนไลน์ / Open registration','privacy_notice':'คำชี้แจงการใช้ข้อมูลบัญชี / Account privacy notice','privacy_version':'วันที่หรือรุ่นของคำชี้แจง / Notice version','contact':'ช่องทางติดต่อผู้ดูแลข้อมูล / Privacy contact','retention_days':'เก็บคำขอที่ยังไม่ยืนยันอีเมลหรือไม่อนุมัติกี่วัน / Retain unverified or rejected requests for days'}
        widgets={'privacy_notice':forms.Textarea(attrs={'rows':8})}
    def clean(self):
        d=super().clean()
        old=RegistrationPolicy.objects.filter(pk=self.instance.pk).first()
        if old and (d.get('privacy_notice')!=old.privacy_notice or d.get('contact')!=old.contact) and d.get('privacy_version')==old.privacy_version:
            self.add_error('privacy_version','เมื่อเปลี่ยนคำชี้แจงหรือช่องทางติดต่อ ให้ระบุรุ่นใหม่เพื่อเก็บประวัติ / Use a new notice version when its contents change.')
        return d

    def clean_retention_days(self):
        n=self.cleaned_data['retention_days']
        if not 7<=n<=3650:raise ValidationError('ระบุ 7–3650 วัน / Enter 7–3650 days.')
        return n


def limited(request):
    if request.method!='POST':return False
    client=salted_hmac('access-public',request.META.get('REMOTE_ADDR','unknown')).hexdigest()
    if not throttle(client,limit=20):return True
    if request.POST.get('email'):
        return not throttle(salted_hmac('access-email',request.POST['email'].strip().lower()).hexdigest(),limit=3,window_seconds=3600)
    return False

@public_page
def register(request,scope_id=None):
    if scope_id is None:
        return render(request,'governance/register_list.html',{'policies':RegistrationPolicy.objects.filter(enabled=True).select_related('scope__organization')})
    policy=get_object_or_404(RegistrationPolicy,scope_id=scope_id,enabled=True)
    form=RequestForm(request.POST if request.method=='POST' else None)
    if limited(request):return render(request,'governance/public.html',{'title':'กรุณารอแล้วลองใหม่ / Please wait before trying again','message':'มีการส่งคำขอหลายครั้ง กรุณารออย่างน้อย 10 นาที / Too many attempts.'},status=429)
    if request.method=='POST' and form.is_valid():
        try:access.request_access(policy.scope,form.cleaned_data)
        except (ValidationError,IntegrityError):form.add_error(None,'ยังรับคำขอไม่ได้ กรุณาติดต่อผู้ดูแล / Unable to accept the request; contact the administrator.')
        else:return render(request,'governance/public.html',{'title':'รับคำขอแล้ว / Request received','message':'หากข้อมูลนี้ใช้สมัครได้ ระบบจะส่งอีเมลให้ยืนยัน จากนั้นผู้ดูแลจะพิจารณาสิทธิ์ ตรวจกล่องจดหมายและจดหมายขยะด้วย / If eligible, you will receive an email to verify before an administrator reviews access.'})
    return render(request,'governance/public.html',{'title':'ขอใช้งาน NEXORA / Request access','form':form,'policy':policy},status=422 if form.errors else 200)

@public_page
def code(request,kind):
    form=(ActivateForm if kind=='activate' else CodeForm)(request.POST if request.method=='POST' else None)
    if limited(request):return render(request,'governance/public.html',{'title':'ลองหลายครั้งแล้ว / Too many attempts','message':'กรุณารอ 10 นาที / Wait 10 minutes.'},status=429)
    if request.method=='POST' and form.is_valid():
        try:
            if kind=='activate':access.activate(form.cleaned_data['code'],form.cleaned_data['password1'])
            else:access.verify(form.cleaned_data['code'])
        except ValidationError as exc:form.add_error(None,exc)
        else:return render(request,'governance/public.html',{'title':'ดำเนินการสำเร็จ / Completed','message':'เปิดบัญชีแล้ว เข้าสู่ระบบด้วย Username ในอีเมลและรหัสผ่านที่ตั้งใหม่ / Sign in using your username and new password.' if kind=='activate' else 'ยืนยันอีเมลแล้ว รอผู้ดูแลพิจารณาสิทธิ์ / Email verified. Await administrator approval.'})
    return render(request,'governance/public.html',{'title':'ตั้งรหัสผ่านและเปิดบัญชี / Set password and activate' if kind=='activate' else 'ยืนยันอีเมล / Verify email','form':form,'token_page':True},status=422 if form.errors else 200)

@page(['GET','POST'])
@transaction.atomic
def policy(request,scope):
    require_permission(request.user,'role.manage',scope)
    item=RegistrationPolicy.objects.filter(scope=scope).first() or RegistrationPolicy(scope=scope)
    form=PolicyForm(request.POST if request.method=='POST' else None,instance=item)
    if request.method=='POST' and form.is_valid():
        item=form.save()
        from apps.auditlog.services import record_event
        record_event(scope.organization,request.user,'access.policy_changed','governance.registrationpolicy',str(scope.pk),metadata={'scope_id':str(scope.pk),'enabled':item.enabled,'privacy_version':item.privacy_version})
        return redirect('access-requests',scope_id=scope.pk)
    return form_page(request,scope,form,'ตั้งค่าการสมัครใช้งาน / Registration settings',notice='ระบุวัตถุประสงค์ ข้อมูลที่ใช้ ฐานการใช้ข้อมูล ผู้เข้าถึง ระยะเก็บ สิทธิของเจ้าของข้อมูล และช่องทางติดต่อให้ตรงการใช้งานจริง / Complete your account privacy notice before enabling registration.')

@page(['GET'])
def requests(request,scope):
    require_permission(request.user,'role.manage',scope)
    return render(request,'governance/requests.html',{'scope':scope,'items':Paginator(AccessRequest.objects.filter(scope=scope).exclude(state='unverified').select_related('account').order_by('-created_at'),30).get_page(request.GET.get('page')),'policy':RegistrationPolicy.objects.filter(scope=scope).first()})

@page(['GET','POST'])
def decision(request,scope,pk):
    require_permission(request.user,'role.manage',scope)
    item=get_object_or_404(AccessRequest,pk=pk,scope=scope)
    form=DecisionForm(request.POST if request.method=='POST' else None)
    if request.method=='POST' and form.is_valid():
        try:
            if request.POST.get('action')=='withdraw':access.withdraw(request.user,scope,pk,form.cleaned_data['reason'])
            elif request.POST.get('action')=='resend':access.resend(request.user,scope,pk,form.cleaned_data['mode'])
            else:access.decide(request.user,scope,pk,**form.cleaned_data)
        except (ValidationError,IntegrityError) as exc:form.add_error(None,exc)
        else:return redirect('access-requests',scope_id=scope.pk)
    return render(request,'governance/decision.html',{'scope':scope,'item':item,'form':form})

@page(['GET','POST'])
def admin_create(request,scope):
    require_permission(request.user,'role.manage',scope)
    form=AdminForm(request.POST if request.method=='POST' else None)
    if request.method=='POST' and form.is_valid():
        try:access.admin_create(request.user,scope,form.cleaned_data)
        except (ValidationError,IntegrityError) as exc:form.add_error(None,exc)
        else:return redirect('access-requests',scope_id=scope.pk)
    return form_page(request,scope,form,'เพิ่มบัญชีและส่งคำเชิญเปิดใช้งาน / Create account and send activation',notice='ตรวจอีเมลและบทบาท บัญชีจะยังเข้าไม่ได้จนกว่าผู้รับอีเมลตั้งรหัสผ่านใหม่ / Access begins only after email activation.')

@page(['GET','POST'])
def notifications(request,scope):
    if request.method=='POST':Notification.objects.filter(user=request.user,read_at__isnull=True).update(read_at=timezone.now())
    return render(request,'governance/notifications.html',{'scope':scope,'items':Notification.objects.filter(user=request.user).order_by('-created_at')[:100]})


@page(['GET','POST'])
def prepare_f05(request,scope):
    from apps.rounds.web_forms import ActionForm
    from .f05_quantitative import prepare
    require_permission(request.user,'catalog.edit',scope)
    form=ActionForm(request.POST if request.method=='POST' else None)
    if request.method=='POST' and form.is_valid():
        try:v=prepare(request.user,scope)
        except (ValidationError,IntegrityError) as exc:form.add_error(None,exc)
        else:return redirect('portal-catalog-detail',scope_id=scope.pk,version_id=v.pk)
    return form_page(request,scope,form,'เตรียม F05 เชิงปริมาณรายปี / Prepare annual quantitative F05',notice='สร้างฉบับร่าง 2.1-quantitative มี 8 ข้อ ไม่มีข้อเขียนหรือหลักฐาน คิดชั่วโมงเฉลี่ยจากผู้ส่งแบบสอบถามทุกคน รวมผู้ที่กรอก 0 ต้องตรวจคำแปลและเผยแพร่ก่อนเปิดรอบ / Prepare the eight-item quantitative form, review translations and publish before collection.')


@page(['GET'])
def annual_policy(request,scope):
    from apps.rounds.models import CollectionRound
    from .policies import BASES,LABELS,validate_current_round
    require_permission(request.user,'round.manage',scope)
    issues=[]
    for r in CollectionRound.objects.filter(scope=scope,status__in=['draft','ready','open']).select_related('period__calendar'):
        try:
            validate_current_round(r)
            if not r.schedule_confirmed:raise ValidationError("ยังไม่ได้ยืนยันวันรับคำตอบ / Collection window not confirmed.")
        except ValidationError as exc:issues.append({'round':r,'message':' '.join(exc.messages)})
    return render(request,'governance/annual_policy.html',{'scope':scope,'bases':[(c,LABELS[t]) for c,t in BASES.items()],'issues':issues})
