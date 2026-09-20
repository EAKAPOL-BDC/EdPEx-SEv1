import uuid
from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

class AccessRequest(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    scope=models.ForeignKey('accounts.AccessScope',on_delete=models.PROTECT)
    email=models.EmailField(max_length=254)
    full_name=models.CharField(max_length=200)
    affiliation=models.CharField(max_length=200)
    purpose=models.TextField(max_length=1000)
    privacy_version=models.CharField(max_length=80)
    privacy_notice_snapshot=models.TextField(blank=True,default='')
    privacy_contact_snapshot=models.CharField(max_length=300,blank=True,default='')
    created_at=models.DateTimeField(auto_now_add=True)
    admin_invited=models.BooleanField(default=False)
    verified_at=models.DateTimeField(null=True,blank=True)
    state=models.CharField(max_length=20,default='unverified',choices=[('unverified','รอยืนยันอีเมล'),('pending','รอผู้ดูแลพิจารณา'),('approved','อนุมัติแล้ว'),('rejected','ไม่อนุมัติ')])
    decided_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    decided_at=models.DateTimeField(null=True,blank=True)
    decision_reason=models.TextField(blank=True,max_length=1000)
    account=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    delivery_status=models.CharField(max_length=20,default='pending')
    class Meta:
        constraints=[models.UniqueConstraint(Lower('email'),'scope',name='access_request_scope_email')]

class AccessCode(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    request=models.ForeignKey(AccessRequest,on_delete=models.CASCADE,related_name='codes')
    purpose=models.CharField(max_length=12,choices=[('verify','verify'),('activate','activate')])
    digest=models.CharField(max_length=64,unique=True)
    expires_at=models.DateTimeField()
    used_at=models.DateTimeField(null=True,blank=True)

class Confirmation(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    route=models.CharField(max_length=500)
    digest=models.CharField(max_length=64)
    context_digest=models.CharField(max_length=64)
    expires_at=models.DateTimeField()
    used_at=models.DateTimeField(null=True,blank=True)

class Notification(models.Model):
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    text=models.CharField(max_length=500)
    created_at=models.DateTimeField(auto_now_add=True)
    read_at=models.DateTimeField(null=True,blank=True)

class RegistrationPolicy(models.Model):
    scope=models.OneToOneField('accounts.AccessScope',on_delete=models.PROTECT,primary_key=True)
    enabled=models.BooleanField(default=False)
    privacy_notice=models.TextField(max_length=8000)
    privacy_version=models.CharField(max_length=80)
    contact=models.CharField(max_length=300)
    retention_days=models.PositiveIntegerField(default=90)


class WorkspaceRefresh(models.Model):
    """One scoped, reviewed cleanup transaction. No response contents are retained."""
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    scope=models.ForeignKey('accounts.AccessScope',on_delete=models.PROTECT)
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    plan_hash=models.CharField(max_length=64)
    manifest=models.JSONField(default=dict)
    summary=models.JSONField(default=dict)
    revision=models.CharField(max_length=80)
    reason=models.TextField()
    database_transaction=models.BigIntegerField(null=True)
    status=models.CharField(max_length=12,default='running')
    created_at=models.DateTimeField(auto_now_add=True)
    completed_at=models.DateTimeField(null=True)
