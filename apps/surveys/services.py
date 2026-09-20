import hashlib
import secrets
from datetime import timedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from apps.accounts.permissions import require_permission
from apps.auditlog.services import record_event
from apps.rounds.models import CollectionRound, PopulationMember, RoundInstrument
from .models import Invitation, AnonymousSession, AnonymousResponse, AccessThrottle
from .schema import normalize


class SurveyConflict(ValidationError):
    pass


def token_hash(secret):
    return hashlib.sha256(secret.encode('utf-8')).hexdigest()


@transaction.atomic
def throttle(key, *, limit=20, window_seconds=600):
    """Database-wide per keyed client bucket; no tokens, IPs or answers are logged."""
    now = timezone.now()
    row, _ = AccessThrottle.objects.get_or_create(key=key)
    row = AccessThrottle.objects.select_for_update().get(pk=row.pk)
    if row.window_start <= now-timedelta(seconds=window_seconds):
        row.attempts, row.window_start = 0, now
    row.attempts = min(row.attempts + 1, limit + 1)
    row.save()
    return row.attempts <= limit


def cleanup():
    now = timezone.now()
    AnonymousSession.objects.filter(expires_at__lte=now).delete()
    AccessThrottle.objects.filter(window_start__lt=now-timedelta(days=1)).delete()
    from django.conf import settings
    if getattr(settings, 'NEXORA_PUBLIC_ASSESSMENTS_ENABLED', False):
        from apps.participation.models import PublicSession
        PublicSession.objects.filter(spent=False, expires_at__lte=now).delete()


def require_manager(actor, binding):
    for permission in ('round.manage','population.manage'):
        require_permission(actor, permission, binding.collection_round.scope)


@transaction.atomic
def issue(actor, binding_id, member_id, *, revoke=False):
    binding = RoundInstrument.objects.select_related('instrument_version__instrument','collection_round__scope','survey_profile').get(pk=binding_id)
    r = CollectionRound.objects.select_for_update().get(pk=binding.collection_round_id)
    require_manager(actor,binding)
    if binding.survey_profile.intake_method == 'public':
        raise ValidationError('รอบนี้เข้าจากหน้าสาธารณะ ไม่ออกคำเชิญรายบุคคล / Use public entry; no individual invitations for this collection.')
    from apps.leadership.services import validate_binding
    validate_binding(binding, r.population_snapshot, accepting=True)
    if r.status not in {'ready','open'} or timezone.now() >= r.close_at:
        raise ValidationError('รอบต้องพร้อมหรือเปิดรับและยังไม่หมดเวลา / Round must be ready or open and within its closing date.')
    from apps.governance.policies import validate_current_round
    validate_current_round(r)
    p = binding.survey_profile
    member = PopulationMember.objects.get(pk=member_id,snapshot_id=r.population_snapshot_id,group__code=p.group_code)
    invitation = Invitation.objects.select_for_update().filter(binding=binding,member=member).first()
    if invitation and invitation.spent:
        raise SurveyConflict('สิทธิ์นี้ใช้ส่งคำตอบแล้ว / This invitation has already been used.')
    raw = secrets.token_urlsafe(32)
    if invitation is None:
        if revoke:
            raise ValidationError('No invitation to revoke.')
        invitation = Invitation(binding=binding,member=member)
    else:
        AnonymousSession.objects.filter(invitation=invitation).delete()
    invitation.token_hash, invitation.expires_at, invitation.revoked = token_hash(raw), r.close_at, revoke
    invitation.save()
    require_manager(actor,binding)
    record_event(r.organization,actor,'survey.invitation.revoked' if revoke else 'survey.invitation.issued',
        'surveys.invitation',str(invitation.pk),metadata={'scope_id':str(r.scope_id),'round_id':str(r.pk)})
    return None if revoke else raw


def _open(binding):
    from apps.governance.policies import validate_current_round
    validate_current_round(binding.collection_round)
    if not binding.collection_round.accepting_at():
        raise SurveyConflict('ขณะนี้รอบไม่เปิดรับคำตอบ / This round is not accepting responses.')
    from apps.leadership.services import validate_binding
    validate_binding(binding, binding.collection_round.population_snapshot, accepting=True)


@transaction.atomic
def exchange(raw):
    if isinstance(raw,str) and raw.startswith('NXA1-'):
        from apps.participation.admission import exchange as exchange_pass
        return exchange_pass(raw)
    if not isinstance(raw,str) or not 30 <= len(raw) <= 100:
        raise SurveyConflict('รหัสใช้ไม่ได้หรือหมดอายุ / Code unavailable or expired.')
    initial = Invitation.objects.filter(token_hash=token_hash(raw)).first()
    if initial is None:
        raise SurveyConflict('รหัสใช้ไม่ได้หรือหมดอายุ / Code unavailable or expired.')
    CollectionRound.objects.select_for_update().get(pk=initial.binding.collection_round_id)
    invitation = Invitation.objects.select_for_update().select_related('binding__collection_round').get(pk=initial.pk)
    _open(invitation.binding)
    if invitation.token_hash != token_hash(raw) or invitation.spent or invitation.revoked or invitation.expires_at <= timezone.now():
        raise SurveyConflict('รหัสใช้ไม่ได้หรือหมดอายุ / Code unavailable or expired.')
    # Re-entering a valid code rotates the session secret while retaining unexpired draft.
    old = AnonymousSession.objects.filter(invitation=invitation).first()
    draft = {}  # Never store answers beside the identified invitation.
    revision = old.revision if old and old.expires_at > timezone.now() else 0
    AnonymousSession.objects.filter(invitation=invitation).delete()
    secret = secrets.token_urlsafe(32)
    expiry = min(invitation.expires_at, timezone.now()+timedelta(hours=24))
    AnonymousSession.objects.create(invitation=invitation,secret_hash=token_hash(secret),expires_at=expiry,draft=draft,revision=revision)
    return secret


def read_session(secret):
    if isinstance(secret,str) and secret.startswith('NXP1-'):
        from apps.participation.public_admission import read_session as public_session
        return public_session(secret)
    if isinstance(secret,str) and secret.startswith('NXS1-'):
        from apps.participation.admission import read_session as read_pass_session
        return read_pass_session(secret)
    if not isinstance(secret,str) or len(secret)>100:
        raise SurveyConflict('กรุณาเข้าด้วยรหัสคำเชิญ / Enter your invitation code.')
    session = AnonymousSession.objects.select_related('invitation__binding__collection_round','invitation__binding__survey_profile',
        'invitation__binding__instrument_version__instrument','invitation__binding__translation_bundle').filter(secret_hash=token_hash(secret)).first()
    if not session or session.expires_at <= timezone.now() or session.invitation.spent or session.invitation.revoked:
        raise SurveyConflict('ช่วงตอบหมดอายุ กรุณาเข้าด้วยรหัสอีกครั้ง / Session expired; enter the code again.')
    _open(session.invitation.binding)
    return session


@transaction.atomic
def save(secret, payload, revision, *, submit=False):
    session = read_session(secret)
    binding = session.invitation.binding
    # Same order as close/revoke/reissue: round -> invitation -> session.
    r = CollectionRound.objects.select_for_update().get(pk=binding.collection_round_id)
    invitation = Invitation.objects.select_for_update().get(pk=session.invitation_id)
    session = AnonymousSession.objects.select_for_update().filter(pk=session.pk,secret_hash=token_hash(secret)).first()
    if session is None or invitation.spent or invitation.revoked or session.expires_at <= timezone.now() or not r.accepting_at():
        raise SurveyConflict('รอบปิดหรือสิทธิ์ถูกใช้แล้ว / Round closed or invitation already used.')
    if type(revision) is not int or revision != session.revision:
        raise SurveyConflict('มีฉบับร่างใหม่แล้ว เปิดหน้าอีกครั้ง / A newer draft exists. Reload the page.')
    answers, completion = normalize(binding.survey_profile,payload,submitting=submit)
    if submit:
        # No pointer between these stores. Both writes commit, or neither does.
        invitation.spent = True
        invitation.save(update_fields=['spent'])
        response = AnonymousResponse.objects.create(binding=binding,group_code=binding.survey_profile.group_code,answers=answers,completion=completion)
        session.delete()
        return str(response.pk), completion
    # Preview only: the server renders answers in this response, without retaining a draft.
    return session.revision
