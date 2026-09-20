"""Transactional proof issuance and scoped verification, independent of answers.

This is a staged bearer-token implementation, not blind issuance. Operators with
access to infrastructure/timing may still correlate events; see the rollout doc.
"""
import hashlib
import re
import secrets
import uuid
from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from apps.accounts.permissions import require_permission
from apps.auditlog.services import record_event
from apps.rounds.models import CollectionRound, RoundInstrument
from apps.surveys import services as surveys
from apps.surveys.schema import normalize
from .models import ReceiptPolicy, ParticipationReceipt, VerifierClient, VerifierGrant, ReceiptRedemption

TOKEN_RE = re.compile(r'^NXR1-[0-9a-f]{64}$')
CLIENT_RE = re.compile(r'^NXC1-[0-9a-f]{64}$')
TICKET_SALT = 'nexora.participation.candidate.v1'
PURPOSES = {'workload', 'prize'}


class ReceiptError(Exception):
    def __init__(self, code, status=409, missing=()):
        super().__init__(code)
        self.code, self.status, self.missing = code, status, tuple(missing)


def digest(value):
    return hashlib.sha256(value.encode('ascii')).hexdigest()


def _admin_event(actor, scope, action, object_type, object_id):
    # Administrative changes only; never attach respondent submissions or tokens.
    record_event(scope.organization, actor, 'participation.'+action, object_type,
                 str(object_id), metadata={'scope_id': str(scope.pk)})


def require_enabled():
    if not getattr(settings, 'NEXORA_PARTICIPATION_ENABLED', False):
        raise ReceiptError('unavailable', 404)


def _realm(realm):
    if realm not in {'test', 'live'}:
        raise ReceiptError('invalid_realm', 422)
    if realm == 'live' and not getattr(settings, 'NEXORA_PARTICIPATION_ALLOW_LIVE', False):
        raise ReceiptError('live_issuance_disabled', 403)


def _token_hash(token):
    if not isinstance(token, str) or not TOKEN_RE.fullmatch(token):
        raise ReceiptError('invalid_receipt', 422)
    return digest(token)


def _policy_valid(policy):
    from .lan_preview import enabled as lan_preview_enabled
    if lan_preview_enabled() and (policy.realm != 'test' or policy.binding.collection_round.data_kind != 'synthetic'):
        raise ReceiptError('synthetic_test_only', 403)
    _realm(policy.realm)
    if not policy.enabled:
        raise ReceiptError('policy_disabled')
    if policy.expires_at <= timezone.now():
        raise ReceiptError('expired')


@transaction.atomic
def configure_policy(actor, binding_id, *, activity_code, label_th, label_en,
                     expires_at, workload=False, prize=False, realm='test'):
    require_enabled()
    _realm(realm)
    binding = RoundInstrument.objects.select_related('collection_round__scope', 'instrument_version__instrument').get(pk=binding_id)
    r = CollectionRound.objects.select_for_update().get(pk=binding.collection_round_id)
    surveys.require_manager(actor, binding)
    if binding.instrument_version.instrument.code not in {'F01', 'F02', 'F03', 'F04', 'F05', 'F06'}:
        raise ReceiptError('unsupported_instrument', 422)
    if not hasattr(binding, 'survey_profile'):
        raise ReceiptError('survey_profile_required', 422)
    if r.status not in {'draft', 'ready', 'open'} or r.close_at <= timezone.now():
        raise ReceiptError('round_unavailable')
    if realm == 'live' and r.data_kind != 'real':
        raise ReceiptError('synthetic_cannot_be_live', 422)
    if expires_at <= r.close_at or not label_th.strip() or not label_en.strip():
        raise ReceiptError('invalid_policy', 422)
    if ReceiptPolicy.objects.filter(binding=binding).exists():
        raise ReceiptError('policy_already_configured')
    policy = ReceiptPolicy(binding=binding, activity_code=activity_code, label_th=label_th,
                           label_en=label_en, expires_at=expires_at, workload=workload, prize=prize, realm=realm)
    policy.full_clean()
    policy.save()
    _admin_event(actor, r.scope, 'policy.created', 'participation.policy', policy.pk)
    return policy


@transaction.atomic
def create_client(actor, scope, *, name, expires_at, realm='test'):
    require_enabled()
    require_permission(actor, 'round.manage', scope)
    _realm(realm)
    if expires_at <= timezone.now():
        raise ReceiptError('invalid_expiry', 422)
    token = 'NXC1-' + secrets.token_hex(32)
    client = VerifierClient(scope=scope, name=name, key_hash=digest(token), realm=realm, expires_at=expires_at)
    client.full_clean()
    client.save()
    _admin_event(actor, scope, 'client.created', 'participation.client', client.pk)
    return client, token  # Show once to the authorized operator; never log.


@transaction.atomic
def grant_client(actor, client_id, policy_id, purpose, *, can_redeem=False):
    require_enabled()
    client = VerifierClient.objects.select_for_update().select_related('scope').get(pk=client_id)
    policy = ReceiptPolicy.objects.select_for_update().select_related('binding__collection_round').get(pk=policy_id)
    require_permission(actor, 'round.manage', client.scope)
    require_permission(actor, 'round.manage', policy.binding.collection_round.scope)
    if client.scope_id != policy.binding.collection_round.scope_id or client.realm != policy.realm:
        raise ReceiptError('scope_or_realm_mismatch', 403)
    if purpose not in PURPOSES or not getattr(policy, purpose):
        raise ReceiptError('purpose_unavailable', 422)
    grant, _ = VerifierGrant.objects.update_or_create(client=client, policy=policy, purpose=purpose,
                                                     defaults={'active': True, 'can_redeem': can_redeem})
    _admin_event(actor, client.scope, 'grant.changed', 'participation.grant', grant.pk)
    return grant


@transaction.atomic
def disable_client(actor, client_id):
    client = VerifierClient.objects.select_for_update().select_related('scope').get(pk=client_id)
    require_permission(actor, 'round.manage', client.scope)
    client.active = False
    client.save(update_fields=['active'])
    _admin_event(actor, client.scope, 'client.disabled', 'participation.client', client.pk)


@sensitive_variables()
@transaction.atomic
def rotate_client_key(actor, client_id):
    client = VerifierClient.objects.select_for_update().select_related('scope').get(pk=client_id)
    require_permission(actor, 'round.manage', client.scope)
    token = 'NXC1-' + secrets.token_hex(32)
    client.key_hash = digest(token)
    client.save(update_fields=['key_hash'])
    _admin_event(actor, client.scope, 'client.key_rotated', 'participation.client', client.pk)
    return token


@transaction.atomic
def revoke_receipt(actor, policy_id, token):
    policy = ReceiptPolicy.objects.select_for_update().select_related('binding__collection_round__scope').get(pk=policy_id)
    require_permission(actor, 'round.manage', policy.binding.collection_round.scope)
    receipt = ParticipationReceipt.objects.select_for_update().get(policy=policy, token_hash=_token_hash(token))
    receipt.revoked = True
    receipt.save(update_fields=['revoked'])
    # Log the affected collection, not a link from the administrator to a bearer.
    _admin_event(actor, policy.binding.collection_round.scope, 'receipt.revoked', 'participation.policy', policy.pk)


@sensitive_variables()
def prepare(session_secret):
    """Pre-deliver an unpredictable candidate so a lost submit response is recoverable.

    The ticket authorizes a candidate, not completion. Neither ticket nor token is
    stored beside the identified invitation. Nothing redeemable exists yet.
    """
    require_enabled()
    session = surveys.read_session(session_secret)
    try:
        policy = ReceiptPolicy.objects.get(binding=session.invitation.binding)
    except ReceiptPolicy.DoesNotExist:
        raise ReceiptError('policy_unavailable', 404) from None
    _policy_valid(policy)
    token = 'NXR1-' + secrets.token_hex(32)
    ticket = signing.dumps({'policy': str(policy.pk), 'token': token}, salt=TICKET_SALT)
    return {'receipt_token': token, 'issuance_ticket': ticket, 'realm': policy.realm,
            'status': 'prepared', 'ticket_expires_in': 7200}


@sensitive_variables()
@transaction.atomic
def submit(session_secret, payload, revision, issuance_ticket):
    """One commit for response, invitation spend and independent proof; no shared ID."""
    require_enabled()
    if not isinstance(issuance_ticket, str) or len(issuance_ticket) > 1500:
        raise ReceiptError('invalid_ticket', 422)
    try:
        candidate = signing.loads(issuance_ticket, salt=TICKET_SALT, max_age=7200)
        if set(candidate) != {'policy', 'token'}:
            raise ValueError
        policy_id = uuid.UUID(candidate['policy'])
        token_hash = _token_hash(candidate['token'])
    except (signing.BadSignature, ValueError, TypeError, KeyError, ReceiptError):
        raise ReceiptError('invalid_ticket', 422) from None
    session = surveys.read_session(session_secret)
    binding = session.invitation.binding
    # Preserve legacy lock order: round before invitation/session. Policies also
    # serialize issuance against disabling/revoking a collection's proofs.
    CollectionRound.objects.select_for_update().get(pk=binding.collection_round_id)
    try:
        policy = ReceiptPolicy.objects.select_for_update().get(pk=policy_id, binding=binding)
    except ReceiptPolicy.DoesNotExist:
        raise ReceiptError('ticket_context_mismatch', 409) from None
    _policy_valid(policy)
    if ParticipationReceipt.objects.filter(token_hash=token_hash).exists():
        raise ReceiptError('candidate_already_used')
    normalized, _ = normalize(binding.survey_profile, payload, submitting=True)
    missing = [qid for qid, value in normalized.items()
               if value['status'] in {'skipped', 'missing'} and not qid.split('-')[1].startswith('O')]
    if missing:
        raise ReceiptError('required_answers_missing', 422, missing)
    # This returns an internal answer UUID; deliberately discard it. Explicit
    # unable-to-assess is a valid participation answer, not a positive score.
    if session_secret.startswith('NXP1-'):
        from .public_admission import save as save_public
        save_public(session_secret, payload, revision)
    elif session_secret.startswith('NXS1-'):
        from .admission import save as save_unlinked
        save_unlinked(session_secret, payload, revision)
    else:
        surveys.save(session_secret, payload, revision, submit=True)
    receipt = ParticipationReceipt.objects.create(policy=policy, token_hash=token_hash)
    return {'status': 'issued', **_public_details(receipt, policy)}


def _public_details(receipt, policy):
    r = policy.binding.collection_round
    return {'policy_id': str(policy.pk), 'activity_code': policy.activity_code,
            'label_th': policy.label_th, 'label_en': policy.label_en,
            'instrument': policy.binding.instrument_version.instrument.code,
            'reporting_year_be': r.period.reporting_year_be,
            'policy_version': policy.version, 'realm': policy.realm,
            'expires_at': policy.expires_at.isoformat()}


@sensitive_variables()
def holder_status(token):
    """Recovery after a lost acknowledgement. Possession does not identify a person."""
    require_enabled()
    token_hash = _token_hash(token)
    receipt = ParticipationReceipt.objects.select_related(
        'policy__binding__collection_round__period', 'policy__binding__instrument_version__instrument').filter(token_hash=token_hash).first()
    if receipt is None:
        # Includes pending/uncommitted and rolled-back attempts; never implies
        # the original submission has failed or that it is safe to submit again.
        return {'status': 'not_confirmed'}
    policy = receipt.policy
    _realm(policy.realm)
    state = 'revoked' if receipt.revoked else 'unavailable' if not policy.enabled else 'expired' if policy.expires_at <= timezone.now() else 'issued'
    return {'status': state, **_public_details(receipt, policy)}


@sensitive_variables()
def authenticate(raw_key):
    require_enabled()
    if not isinstance(raw_key, str) or not CLIENT_RE.fullmatch(raw_key):
        raise ReceiptError('unauthorized', 401)
    client = VerifierClient.objects.filter(key_hash=digest(raw_key), active=True, expires_at__gt=timezone.now()).first()
    if client is None:
        raise ReceiptError('unauthorized', 401)
    _realm(client.realm)
    return client


def _authorize(client, policy, purpose, *, redeem=False):
    if not client.active or client.expires_at <= timezone.now():
        raise ReceiptError('unauthorized', 401)
    if client.scope_id != policy.binding.collection_round.scope_id or client.realm != policy.realm or purpose not in PURPOSES:
        raise ReceiptError('forbidden', 403)
    _realm(client.realm)
    grant = VerifierGrant.objects.filter(client=client, policy=policy, purpose=purpose, active=True).first()
    if not grant or (redeem and not grant.can_redeem):
        raise ReceiptError('forbidden', 403)
    if not getattr(policy, purpose):
        raise ReceiptError('purpose_unavailable')


def _eligibility(receipt, policy, purpose):
    if receipt.revoked:
        return 'revoked'
    if not policy.enabled:
        return 'unavailable'
    if policy.expires_at <= timezone.now():
        return 'expired'
    # Prizes only after formal close AND the published closing time. No draw or
    # staff-hour award is performed by this service.
    r = policy.binding.collection_round
    if purpose == 'prize' and (r.status != 'closed' or timezone.now() < r.close_at):
        return 'not_open'
    if ReceiptRedemption.objects.filter(receipt=receipt, purpose=purpose).exists():
        return 'already_redeemed'
    return 'valid'


@sensitive_variables()
@transaction.atomic
def verify(raw_key, policy_id, purpose, token):
    # Read-only with respect to receipts/redemptions. Re-check credentials rather
    # than trusting a client object supplied by a caller.
    client = authenticate(raw_key)
    try:
        policy = ReceiptPolicy.objects.select_related('binding__collection_round__period', 'binding__instrument_version__instrument').get(pk=policy_id)
    except (ReceiptPolicy.DoesNotExist, ValidationError, ValueError):
        raise ReceiptError('forbidden', 403) from None
    _authorize(client, policy, purpose)
    receipt = ParticipationReceipt.objects.filter(policy=policy, token_hash=_token_hash(token)).first()
    if receipt is None:
        return {'status': 'invalid'}
    return {'status': _eligibility(receipt, policy, purpose), **_public_details(receipt, policy)}


@sensitive_variables()
@transaction.atomic
def redeem(raw_key, policy_id, purpose, token, idempotency_key):
    client = authenticate(raw_key)
    # Consumer-generated random UUID, never employee number or free text.
    try:
        parsed = uuid.UUID(idempotency_key)
        if parsed.version != 4 or str(parsed) != idempotency_key:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ReceiptError('invalid_idempotency_key', 422) from None
    idem_hash = digest(idempotency_key)
    # Serializing per client makes conflicting keys atomic even across receipts.
    client = VerifierClient.objects.select_for_update().get(pk=client.pk)
    if client.key_hash != digest(raw_key):
        raise ReceiptError('unauthorized', 401)
    try:
        policy = ReceiptPolicy.objects.select_for_update().select_related(
            'binding__collection_round__period', 'binding__instrument_version__instrument').get(pk=policy_id)
    except (ReceiptPolicy.DoesNotExist, ValidationError, ValueError):
        raise ReceiptError('forbidden', 403) from None
    _authorize(client, policy, purpose, redeem=True)
    receipt = ParticipationReceipt.objects.select_for_update().filter(policy=policy, token_hash=_token_hash(token)).first()
    if receipt is None:
        raise ReceiptError('invalid_receipt')
    previous = ReceiptRedemption.objects.filter(client=client, idempotency_hash=idem_hash).first()
    if previous:
        if previous.receipt_id != receipt.pk or previous.purpose != purpose:
            raise ReceiptError('idempotency_conflict')
        # Return the original result even after expiry/revocation. This is a
        # reconciliation response, NOT a new eligibility decision.
        return {'status': 'redeemed', 'replayed': True, 'redemption_reference': str(previous.pk),
                'current_status': _eligibility(receipt, policy, purpose), **_public_details(receipt, policy)}
    state = _eligibility(receipt, policy, purpose)
    if state != 'valid':
        raise ReceiptError(state)
    record = ReceiptRedemption.objects.create(receipt=receipt, client=client, purpose=purpose, idempotency_hash=idem_hash)
    return {'status': 'redeemed', 'replayed': False, 'redemption_reference': str(record.pk),
            'current_status': 'already_redeemed', **_public_details(receipt, policy)}
