"""Bearer participation proofs. Never link these records to an answer or person.

Policy is shared by a collection, not a respondent. Precise issuance timestamps,
invitation IDs, respondent identities and raw tokens are intentionally absent.
This boundary reduces linkage; shared infrastructure is NOT cryptographic anonymity.
"""
import uuid
from django.conf import settings
from django.db import models
from django.db.models import Q


class AssessmentBatch(models.Model):
    """Administrative parent only; answers/proofs remain in separate collections."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope = models.ForeignKey('accounts.AccessScope', on_delete=models.PROTECT)
    title = models.CharField(max_length=80)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class AssessmentBatchItem(models.Model):
    batch = models.ForeignKey(AssessmentBatch, on_delete=models.PROTECT, related_name='items')
    binding = models.OneToOneField('rounds.RoundInstrument', on_delete=models.PROTECT, related_name='batch_item')


class PublicCollection(models.Model):
    """Explicit publication contract for a NEW aggregate-only collection."""
    binding = models.OneToOneField('rounds.RoundInstrument', primary_key=True, on_delete=models.PROTECT,
                                  related_name='public_collection')
    contract_version = models.CharField(max_length=24, default='2026-09-19')
    level = models.CharField(max_length=16, blank=True)
    programme = models.CharField(max_length=40, blank=True)
    published = models.BooleanField(default=False)

    class Meta:
        default_permissions = ()


class PublicSession(models.Model):
    """One anonymous submission slot, never linked to a response or receipt.

    Clear transient context, hash and expiry on submission; retain only a spent
    slot per collection for the deferred response-balance constraint.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    binding = models.ForeignKey('rounds.RoundInstrument', on_delete=models.PROTECT)
    secret_hash = models.CharField(max_length=64, unique=True, null=True, editable=False)
    expires_at = models.DateTimeField(null=True)
    year = models.CharField(max_length=8, blank=True)
    spent = models.BooleanField(default=False)

    @property
    def invitation(self):
        # Adapter for the common proof service; this is NOT a personal invitation.
        return self

    @property
    def revision(self):
        return 0

    class Meta:
        default_permissions = ()


class AccessPool(models.Model):
    """Collection-level capacity only; no recipient roster or assignment map."""
    binding = models.OneToOneField('rounds.RoundInstrument', primary_key=True, on_delete=models.PROTECT)
    capacity = models.PositiveIntegerField()
    enabled = models.BooleanField(default=True)

    class Meta:
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=Q(capacity__gte=1), name='participation_pool_capacity')]


class AccessPass(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    binding = models.ForeignKey('rounds.RoundInstrument', on_delete=models.PROTECT)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField()
    spent = models.BooleanField(default=False)
    revoked = models.BooleanField(default=False)

    class Meta:
        default_permissions = ()


class AccessSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invitation = models.OneToOneField(AccessPass, on_delete=models.CASCADE)
    secret_hash = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField()
    revision = models.PositiveIntegerField(default=0)

    class Meta:
        default_permissions = ()


class ReceiptPolicy(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    binding = models.OneToOneField('rounds.RoundInstrument', on_delete=models.PROTECT)
    activity_code = models.SlugField(max_length=80)
    label_th = models.CharField(max_length=200)
    label_en = models.CharField(max_length=200)
    version = models.PositiveIntegerField(default=1)
    realm = models.CharField(max_length=8, choices=[('test', 'Test'), ('live', 'Live')], default='test')
    expires_at = models.DateTimeField()
    workload = models.BooleanField(default=False)
    prize = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True)

    class Meta:
        default_permissions = ()
        constraints = [
            models.CheckConstraint(condition=Q(realm__in=['test', 'live']), name='participation_policy_realm'),
            models.CheckConstraint(condition=Q(workload=True) | Q(prize=True), name='participation_policy_purpose'),
            models.CheckConstraint(condition=Q(version__gte=1), name='participation_policy_version'),
        ]


class ParticipationReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    policy = models.ForeignKey(ReceiptPolicy, on_delete=models.PROTECT, related_name='receipts')
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    revoked = models.BooleanField(default=False)

    class Meta:
        default_permissions = ()


class VerifierClient(models.Model):
    """A service account for one scope, never an individual respondent account."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope = models.ForeignKey('accounts.AccessScope', on_delete=models.PROTECT)
    name = models.SlugField(max_length=80)
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    realm = models.CharField(max_length=8, choices=[('test', 'Test'), ('live', 'Live')], default='test')
    active = models.BooleanField(default=True)
    expires_at = models.DateTimeField()

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=['scope', 'name'], name='participation_client_name'),
            models.CheckConstraint(condition=Q(realm__in=['test', 'live']), name='participation_client_realm'),
        ]


class VerifierGrant(models.Model):
    client = models.ForeignKey(VerifierClient, on_delete=models.PROTECT)
    policy = models.ForeignKey(ReceiptPolicy, on_delete=models.PROTECT)
    purpose = models.CharField(max_length=12, choices=[('workload', 'Workload'), ('prize', 'Prize')])
    can_redeem = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=['client', 'policy', 'purpose'], name='participation_client_grant'),
            models.CheckConstraint(condition=Q(purpose__in=['workload', 'prize']), name='participation_grant_purpose'),
        ]


class ReceiptRedemption(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    receipt = models.ForeignKey(ParticipationReceipt, on_delete=models.PROTECT, related_name='redemptions')
    client = models.ForeignKey(VerifierClient, on_delete=models.PROTECT)
    purpose = models.CharField(max_length=12, choices=[('workload', 'Workload'), ('prize', 'Prize')])
    # Hash only: a consumer must not accidentally persist an employee ID as its key.
    idempotency_hash = models.CharField(max_length=64, editable=False)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=['receipt', 'purpose'], name='participation_once_per_purpose'),
            models.UniqueConstraint(fields=['client', 'idempotency_hash'], name='participation_idempotency'),
            models.CheckConstraint(condition=Q(purpose__in=['workload', 'prize']), name='participation_redemption_purpose'),
        ]
