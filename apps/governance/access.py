"""Verified-email requests, explicit scoped approval and one-use activation.

Only token digests persist. Email secrets exist transiently and are never logged.
No account may log in before setting its final password through activation.
"""
import secrets
from datetime import timedelta
from urllib.parse import urlsplit
from django.conf import settings
from django.contrib.auth import get_user_model,password_validation
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare,salted_hmac
from apps.accounts.models import AccessScope,Membership
from apps.accounts.permissions import require_permission
from apps.accounts.services import assign_role
from apps.auditlog.services import record_event
from .models import AccessRequest,AccessCode,Notification,RegistrationPolicy


def hashed(raw):return salted_hmac('nexora-access-code',raw,algorithm='sha256').hexdigest()

def origin():
    value=getattr(settings,'NEXORA_PUBLIC_ORIGIN','').rstrip('/')
    parsed=urlsplit(value)
    if not value or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path or not parsed.netloc:
        raise ValidationError('ผู้ดูแลต้องตั้ง URL หลักของระบบก่อนส่งอีเมล / Configure the public origin first.')
    if parsed.scheme!='https' and not (not settings.PRODUCTION and parsed.scheme=='http' and parsed.hostname in {'localhost','127.0.0.1'}):
        raise ValidationError('ลิงก์เปิดบัญชีต้องใช้ HTTPS / Account links require HTTPS.')
    return value

def notify_admins(scope,text):
    from apps.accounts.permissions import can_access
    for user in get_user_model().objects.filter(is_active=True,membership__organization=scope.organization,membership__is_active=True).distinct():
        if can_access(user,'role.manage',scope):Notification.objects.create(user=user,text=text)

def audit(actor,request,event,reason=''):
    record_event(request.scope.organization,actor,'access.'+event,'governance.accessrequest',str(request.pk),reason=reason,metadata={'scope_id':str(request.scope_id),'state':request.state})

def _email(request,subject,body,track=True):
    # Execute after commit. Failure is a visible delivery state, never an approval rollback.
    pk=request.pk;recipient=request.email
    def deliver():
        try:
            count=send_mail(subject,body,settings.DEFAULT_FROM_EMAIL,[recipient],fail_silently=False)
            status='sent' if count==1 else 'failed'
        except Exception:status='failed'
        if track:AccessRequest.objects.filter(pk=pk).update(delivery_status=status)
    transaction.on_commit(deliver)

def send_code(request,purpose,mode='link'):
    base=origin();now=timezone.now()
    AccessCode.objects.filter(request=request,purpose=purpose,used_at__isnull=True).update(used_at=now)
    raw=secrets.token_urlsafe(32)
    expiry=now+timedelta(hours=1 if purpose=='activate' else 24)
    AccessCode.objects.create(request=request,purpose=purpose,digest=hashed(raw),expires_at=expiry)
    kind='activate' if purpose=='activate' else 'verify'
    url=f'{base}/account/{kind}/'
    if purpose=='verify':
        body=f'โปรดยืนยันอีเมลเพื่อส่งคำขอใช้ NEXORA ให้ผู้ดูแลพิจารณา\n{url}#code={raw}\nลิงก์ใช้ได้ครั้งเดียวภายใน 24 ชั่วโมง การยืนยันนี้ยังไม่ให้สิทธิ์เข้าระบบ\nVerify your email. This does not approve access.'
    elif mode=='temporary':
        body=f'ผู้ดูแลอนุมัติบัญชี NEXORA แล้ว\nUsername: {request.account.username}\nรหัสผ่านชั่วคราวสำหรับเปิดบัญชี: {raw}\nเปิด {url} แล้วกรอกรหัสนี้และตั้งรหัสผ่านใหม่\nรหัสใช้ได้ครั้งเดียวภายใน 1 ชั่วโมง และใช้เข้าสู่หน้าทำงานโดยตรงไม่ได้\nOne-use activation password; set your own password before signing in.'
    else:
        body=f'ผู้ดูแลอนุมัติบัญชี NEXORA แล้ว\nUsername: {request.account.username}\nตั้งรหัสผ่านและเปิดบัญชี: {url}#code={raw}\nลิงก์ใช้ได้ครั้งเดียวภายใน 1 ชั่วโมง\nSet your password before signing in. This link expires in one hour.'
    body += '\n\nคำชี้แจงการใช้ข้อมูลบัญชี รุ่น '+request.privacy_version+'\n'+request.privacy_notice_snapshot+'\nติดต่อ: '+request.privacy_contact_snapshot
    request.delivery_status='pending';request.save(update_fields=['delivery_status'])
    _email(request,'NEXORA: ยืนยันอีเมล' if purpose=='verify' else 'NEXORA: เปิดใช้งานบัญชี',body)

@transaction.atomic
def request_access(scope,data):
    policy=RegistrationPolicy.objects.get(scope=scope,enabled=True)
    AccessScope.objects.select_for_update().get(pk=scope.pk)
    email=data['email'].strip().lower()
    current=AccessRequest.objects.filter(scope=scope,email__iexact=email).first()
    if current:
        if current.state=='unverified':send_code(current,'verify')
        else:_email(current,'NEXORA: ได้รับการติดต่อแล้ว','ระบบได้รับการติดต่อเกี่ยวกับการขอใช้งานแล้ว หากต้องการความช่วยเหลือ โปรดติดต่อผู้ดูแลตามคำชี้แจงการสมัคร / We received your access enquiry. Contact your administrator for help.',track=False)
        return None  # Uniform public result; no account/request enumeration.
    item=AccessRequest(scope=scope,email=email,full_name=data['full_name'],affiliation=data['affiliation'],purpose=data['purpose'],privacy_version=policy.privacy_version,privacy_notice_snapshot=policy.privacy_notice,privacy_contact_snapshot=policy.contact)
    item.full_clean();item.save();send_code(item,'verify')
    return item

@transaction.atomic
def verify(raw):
    try:initial=AccessCode.objects.get(digest=hashed(raw),purpose='verify')
    except AccessCode.DoesNotExist:raise ValidationError('รหัสใช้ไม่ได้หรือหมดอายุ / Invalid or expired code.')
    item=AccessRequest.objects.select_for_update().get(pk=initial.request_id)
    code=AccessCode.objects.select_for_update().get(pk=initial.pk)
    if code.used_at or code.expires_at<=timezone.now() or item.state!='unverified':raise ValidationError('รหัสใช้ไม่ได้หรือหมดอายุ / Invalid or expired code.')
    item.verified_at=code.used_at=timezone.now();item.state='pending';item.save();code.save(update_fields=['used_at'])
    notify_admins(item.scope,'มีคำขอใช้งานที่ยืนยันอีเมลแล้ว กรุณาเปิดรายการคำขอในพื้นที่ทำงาน / A verified access request is waiting for review.')
    return item

@transaction.atomic
def decide(actor,scope,pk,*,outcome,reason,role=None,active_until=None,mode='link'):
    require_permission(actor,'role.manage',scope)
    from apps.accounts.models import Organization
    Organization.objects.select_for_update().get(pk=scope.organization_id)
    item=AccessRequest.objects.select_for_update().get(pk=pk,scope=scope)
    if item.state!='pending' or (not item.verified_at and not item.admin_invited):raise ValidationError('ต้องยืนยันอีเมลและอยู่ระหว่างรอพิจารณา / A verified pending request is required.')
    if not reason.strip() or outcome not in {'approved','rejected'}:raise ValidationError('เลือกผลพิจารณาและระบุเหตุผล / Choose an outcome and reason.')
    if outcome=='approved':
        origin()
        if role is None:raise ValidationError('เลือกบทบาทก่อนอนุมัติ / Select a role.')
        from django.db import connection
        if connection.vendor=='postgresql':
            with connection.cursor() as cursor:cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",['nexora-account:'+item.email.lower()])
        if get_user_model().objects.filter(email__iexact=item.email).exists():raise ValidationError('อีเมลนี้มีบัญชีอยู่แล้ว ให้จัดการสิทธิ์ผ่านเมนูสมาชิกเดิม / Manage the existing account instead.')
        account=get_user_model()(username='nx_'+secrets.token_hex(6),email=item.email,first_name=item.full_name[:150],is_active=False)
        account.set_unusable_password();account.save()
        membership=Membership.objects.create(user=account,organization=scope.organization)
        assign_role(actor=actor,scope=scope,membership=membership,role=role,active_until=active_until)
        item.account=account
    item.state=outcome;item.decision_reason=reason;item.decided_by=actor;item.decided_at=timezone.now();item.save()
    audit(actor,item,'decided',reason)
    if outcome=='approved':send_code(item,'activate',mode)
    else:_email(item,'NEXORA: ผลพิจารณาคำขอใช้งาน','คำขอใช้ NEXORA ไม่ได้รับอนุมัติ กรุณาติดต่อผู้ดูแลตามช่องทางในประกาศความเป็นส่วนตัว / Your request was not approved. Contact your administrator for details.')
    return item

@transaction.atomic
def admin_create(actor,scope,data):
    require_permission(actor,'role.manage',scope)
    AccessScope.objects.select_for_update().get(pk=scope.pk)
    policy=RegistrationPolicy.objects.filter(scope=scope).first()
    if not policy or not policy.privacy_notice.strip():raise ValidationError('จัดทำคำชี้แจงข้อมูลส่วนบุคคลก่อนเพิ่มบัญชี / Configure the account privacy notice first.')
    item=AccessRequest(scope=scope,email=data['email'].lower().strip(),full_name=data['full_name'],affiliation=data['affiliation'],purpose=data['purpose'],privacy_version=policy.privacy_version,privacy_notice_snapshot=policy.privacy_notice,privacy_contact_snapshot=policy.contact,state='pending',admin_invited=True)
    # The administrator's invitation is trusted, but activation still proves email control.
    item.full_clean();item.save()
    return decide(actor,scope,item.pk,outcome='approved',reason=data['reason'],role=data['role'],active_until=data.get('active_until'),mode=data['mode'])

@transaction.atomic
def activate(raw,password):
    try:initial=AccessCode.objects.get(digest=hashed(raw),purpose='activate')
    except AccessCode.DoesNotExist:raise ValidationError('รหัสใช้ไม่ได้หรือหมดอายุ / Invalid or expired code.')
    item=AccessRequest.objects.select_for_update().get(pk=initial.request_id)
    code=AccessCode.objects.select_for_update().get(pk=initial.pk)
    if code.used_at or code.expires_at<=timezone.now() or item.state!='approved' or not item.account_id or item.account.is_active:
        raise ValidationError('รหัสใช้ไม่ได้หรือหมดอายุ / Invalid or expired code.')
    user=get_user_model().objects.select_for_update().get(pk=item.account_id)
    password_validation.validate_password(password,user)
    user.set_password(password);user.is_active=True;user.save(update_fields=['password','is_active'])
    if not item.verified_at:item.verified_at=timezone.now();item.save(update_fields=['verified_at'])
    code.used_at=timezone.now();code.save(update_fields=['used_at'])
    audit(user,item,'activated')
    _email(item,'NEXORA: เปิดบัญชีแล้ว',f'บัญชี {user.username} เปิดใช้งานแล้ว หากคุณไม่ได้ดำเนินการ ให้ติดต่อผู้ดูแล / Your account is active. Contact your administrator if this was not you.')
    return user

@transaction.atomic
def resend(actor,scope,pk,mode):
    require_permission(actor,'role.manage',scope)
    item=AccessRequest.objects.select_for_update().get(pk=pk,scope=scope,state='approved')
    if item.account.is_active:raise ValidationError('บัญชีเปิดใช้แล้ว ไม่ออกคำเชิญใหม่ / This account is already active.')
    send_code(item,'activate',mode);audit(actor,item,'activation_reissued','Previous activation code invalidated.')


@transaction.atomic
def withdraw(actor,scope,pk,reason):
    require_permission(actor,'role.manage',scope)
    item=AccessRequest.objects.select_for_update().get(pk=pk,scope=scope)
    if item.state!='approved' or not item.account_id or item.account.is_active or not reason.strip():
        raise ValidationError('ยกเลิกได้เฉพาะบัญชีที่ยังไม่เปิดใช้ และต้องระบุเหตุผล / Only pending activations can be withdrawn.')
    item.state='rejected';item.decision_reason=reason;item.decided_by=actor;item.decided_at=timezone.now();item.save()
    AccessCode.objects.filter(request=item,used_at__isnull=True).update(used_at=timezone.now())
    audit(actor,item,'activation_withdrawn',reason)
    _email(item,'NEXORA: ยกเลิกคำเชิญเปิดบัญชี','ผู้ดูแลยกเลิกคำเชิญเปิดบัญชีนี้แล้ว ติดต่อผู้ดูแลหากต้องการใช้ระบบ / Your activation invitation has been withdrawn.')
