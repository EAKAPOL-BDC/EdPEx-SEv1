"""Unassigned one-use bearer invitations. No per-person eligibility claims.

Raw passes are returned once to an authorized distributor. Never record the
recipient, delivery address or a pass-to-person assignment in this system.
"""
import re
import secrets
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from apps.rounds.models import CollectionRound, RoundInstrument
from apps.surveys import services as surveys
from apps.surveys.models import AnonymousResponse, Invitation
from apps.surveys.schema import normalize
from .models import AccessPool, AccessPass, AccessSession, ReceiptPolicy
from . import services as proofs

PASS_RE=re.compile(r'^NXA1-[0-9a-f]{64}$')
SESSION_RE=re.compile(r'^NXS1-[0-9a-f]{64}$')


def enabled():
    proofs.require_enabled()
    if not getattr(settings,'NEXORA_UNLINKED_ACCESS_ENABLED',False):
        raise proofs.ReceiptError('unlinked_access_disabled',404)


def available(binding):
    enabled()
    try:
        pool=AccessPool.objects.get(binding=binding,enabled=True)
        policy=ReceiptPolicy.objects.get(binding=binding)
    except (AccessPool.DoesNotExist,ReceiptPolicy.DoesNotExist):
        raise surveys.SurveyConflict('คำเชิญไม่พร้อมใช้ / Invitation unavailable.') from None
    proofs._policy_valid(policy)
    if policy.realm!='test' or binding.instrument_version.instrument.code!='F01' or binding.survey_profile.group_code!='C1':
        raise surveys.SurveyConflict('ช่องทางนี้เปิดสำหรับ F01 C1 รอบทดสอบ / Test F01 C1 entry only.')
    return pool


@transaction.atomic
def configure(actor,binding_id,capacity):
    enabled()
    binding=RoundInstrument.objects.select_related('collection_round__scope','collection_round__population_snapshot','instrument_version__instrument').get(pk=binding_id)
    r=CollectionRound.objects.select_for_update().get(pk=binding.collection_round_id)
    surveys.require_manager(actor,binding)
    if r.status not in {'draft','ready','open'} or r.close_at<=timezone.now():
        raise proofs.ReceiptError('round_unavailable')
    policy=ReceiptPolicy.objects.get(binding=binding,realm='test')
    proofs._policy_valid(policy)
    group=binding.survey_profile.group_code
    snapshot=r.population_snapshot if r.population_snapshot_id else r.population_snapshots.filter(status='frozen').order_by('-version').first()
    limit=snapshot.counts_by_group.get(group,0) if snapshot else 0
    if (binding.instrument_version.instrument.code!='F01' or group!='C1' or type(capacity) is not int
        or not 1<=capacity<=limit or capacity<Invitation.objects.filter(binding=binding).count()):
        raise proofs.ReceiptError('invalid_capacity_or_form',422)
    pool=AccessPool.objects.create(binding=binding,capacity=capacity)
    proofs._admin_event(actor,r.scope,'access.configured','rounds.binding',binding.pk)
    return pool


@transaction.atomic
def prepare_population(actor,binding_id,count,*,source_title,source_reference):
    """A frozen aggregate denominator, without creating PopulationMember rows."""
    enabled()
    from apps.rounds.models import DataSource, PopulationSnapshot, RespondentGroup
    from apps.rounds.services import create_record, freeze_population
    binding=RoundInstrument.objects.select_related('collection_round__scope','instrument_version__instrument').get(pk=binding_id)
    r=CollectionRound.objects.select_for_update().get(pk=binding.collection_round_id)
    surveys.require_manager(actor,binding)
    if r.status!='draft' or r.population_snapshots.exists() or binding.instrument_version.instrument.code!='F01' or binding.survey_profile.group_code!='C1':
        raise proofs.ReceiptError('new_f01_draft_required',422)
    if type(count) is not int or not 1<=count<=100000 or not source_title.strip() or not source_reference.strip():
        raise proofs.ReceiptError('invalid_population',422)
    if not RespondentGroup.objects.filter(scope=r.scope,code='C1').exists():
        create_record(actor,RespondentGroup,scope=r.scope,code='C1',label='นิสิตระดับปริญญาตรี')
    source=create_record(actor,DataSource,scope=r.scope,title=source_title,location=source_reference,
                         source_type='aggregate',original_method='Approved aggregate count; no individual roster')
    snapshot=create_record(actor,PopulationSnapshot,collection_round=r,definition='Aggregate eligible count for unassigned bearer invitations',
                           counting_unit='person',counts_by_group={'C1':count},captured_at=timezone.now(),source=source)
    return freeze_population(actor,snapshot)


@sensitive_variables()
@transaction.atomic
def mint(actor,binding_id,count,*,expected_total=None):
    enabled()
    binding=RoundInstrument.objects.select_related('collection_round__scope','instrument_version__instrument').get(pk=binding_id)
    r=CollectionRound.objects.select_for_update().get(pk=binding.collection_round_id)
    surveys.require_manager(actor,binding)
    pool=available(binding)
    if r.status not in {'ready','open'} or r.close_at<=timezone.now():
        raise proofs.ReceiptError('round_unavailable')
    total=AccessPass.objects.filter(binding=binding).count()+Invitation.objects.filter(binding=binding).count()
    # Checked under the collection lock: a replay or stale operator tab cannot
    # mint another batch. Raw invitation tokens are still returned only once.
    if expected_total is not None and (type(expected_total) is not int or total!=expected_total):
        raise proofs.ReceiptError('batch_state_changed',409)
    if type(count) is not int or not 1<=count<=100 or total+count>pool.capacity:
        raise proofs.ReceiptError('capacity_exceeded',422)
    tokens=['NXA1-'+secrets.token_hex(32) for _ in range(count)]
    AccessPass.objects.bulk_create([AccessPass(binding=binding,token_hash=proofs.digest(raw),expires_at=r.close_at) for raw in tokens])
    # Collection-only administrative event: no pass IDs, hashes, tokens or recipients.
    proofs._admin_event(actor,r.scope,'access.batch_created','rounds.binding',binding.pk)
    secrets.SystemRandom().shuffle(tokens)
    return tokens


@transaction.atomic
def set_enabled(actor,binding_id,value):
    if type(value) is not bool:raise proofs.ReceiptError('invalid_enabled',422)
    binding=RoundInstrument.objects.select_related('collection_round__scope').get(pk=binding_id)
    CollectionRound.objects.select_for_update().get(pk=binding.collection_round_id)
    surveys.require_manager(actor,binding)
    pool=AccessPool.objects.select_for_update().get(binding=binding)
    pool.enabled=value;pool.save(update_fields=['enabled'])
    if not value:AccessSession.objects.filter(invitation__binding=binding).delete()
    proofs._admin_event(actor,binding.collection_round.scope,'access.enabled' if value else 'access.disabled','rounds.binding',binding.pk)


@sensitive_variables()
@transaction.atomic
def exchange(raw):
    enabled()
    if not isinstance(raw,str) or not PASS_RE.fullmatch(raw):raise surveys.SurveyConflict('รหัสไม่พร้อมใช้ / Code unavailable.')
    initial=AccessPass.objects.filter(token_hash=proofs.digest(raw)).first()
    if not initial:raise surveys.SurveyConflict('รหัสไม่พร้อมใช้ / Code unavailable.')
    CollectionRound.objects.select_for_update().get(pk=initial.binding.collection_round_id)
    invitation=AccessPass.objects.select_for_update().select_related('binding__collection_round','binding__instrument_version__instrument').get(pk=initial.pk)
    available(invitation.binding);surveys._open(invitation.binding)
    if invitation.spent or invitation.revoked or invitation.expires_at<=timezone.now():
        raise surveys.SurveyConflict('รหัสไม่พร้อมใช้ / Code unavailable.')
    # Reopening a bearer link rotates the transient session. No answers are retained.
    AccessSession.objects.filter(invitation=invitation).delete()
    secret='NXS1-'+secrets.token_hex(32)
    AccessSession.objects.create(invitation=invitation,secret_hash=proofs.digest(secret),expires_at=min(invitation.expires_at,timezone.now()+timedelta(hours=24)))
    return secret


@sensitive_variables()
def read_session(secret):
    enabled()
    if not isinstance(secret,str) or not SESSION_RE.fullmatch(secret):raise surveys.SurveyConflict('กรุณาเข้าด้วยคำเชิญ / Enter your invitation.')
    session=AccessSession.objects.select_related('invitation__binding__collection_round','invitation__binding__survey_profile','invitation__binding__instrument_version__instrument','invitation__binding__translation_bundle').filter(secret_hash=proofs.digest(secret)).first()
    if not session or session.expires_at<=timezone.now() or session.invitation.spent or session.invitation.revoked:
        raise surveys.SurveyConflict('ช่วงตอบหมดอายุหรือรหัสใช้แล้ว / Session expired or invitation used.')
    available(session.invitation.binding);surveys._open(session.invitation.binding)
    return session


@sensitive_variables()
@transaction.atomic
def save(secret,payload,revision):
    session=read_session(secret);binding=session.invitation.binding
    r=CollectionRound.objects.select_for_update().get(pk=binding.collection_round_id)
    invitation=AccessPass.objects.select_for_update().get(pk=session.invitation_id)
    session=AccessSession.objects.select_for_update().filter(pk=session.pk,secret_hash=proofs.digest(secret)).first()
    available(binding)
    if not session or invitation.spent or invitation.revoked or session.expires_at<=timezone.now() or not r.accepting_at():
        raise surveys.SurveyConflict('รหัสหรือรอบไม่พร้อมใช้ / Invitation or round unavailable.')
    if type(revision) is not int or revision!=session.revision:raise surveys.SurveyConflict('Session changed.')
    answers,completion=normalize(binding.survey_profile,payload,submitting=True)
    invitation.spent=True;invitation.save(update_fields=['spent'])
    response=AnonymousResponse.objects.create(binding=binding,group_code=binding.survey_profile.group_code,answers=answers,completion=completion)
    session.delete()
    return str(response.pk),completion
