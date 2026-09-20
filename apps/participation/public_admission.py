"""Self-selected, aggregate-only anonymous intake. No invitation distribution."""
import re
import secrets
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from apps.rounds.models import CollectionRound, RoundInstrument
from apps.surveys import services as surveys
from apps.surveys.models import AnonymousResponse, Invitation
from . import services as proofs
from .models import PublicCollection, PublicSession, AccessPool, ReceiptPolicy
from .public_catalog import VERSION, GROUPS, LEVELS, YEARS, validate_context

SECRET = re.compile(r'^NXP1-[0-9a-f]{64}$')


def enabled():
    proofs.require_enabled()
    if not getattr(settings, 'NEXORA_PUBLIC_ASSESSMENTS_ENABLED', False):
        raise proofs.ReceiptError('public_entry_unavailable', 404)


def context_for(public, year=''):
    return validate_context(public.binding.survey_profile.group_code, public.level, public.programme, year)


@transaction.atomic
def configure(actor, binding_id, *, level='', programme=''):
    """Only fresh draft rounds. Existing invitations and answers keep their contract."""
    enabled()
    binding = RoundInstrument.objects.select_related('collection_round__scope', 'survey_profile',
                                                    'instrument_version__instrument').get(pk=binding_id)
    r = CollectionRound.objects.select_for_update().get(pk=binding.collection_round_id)
    surveys.require_manager(actor, binding)
    if (r.status != 'draft' or binding.survey_profile.intake_method != 'public' or Invitation.objects.filter(binding=binding).exists()
            or AccessPool.objects.filter(binding=binding).exists()
            or AnonymousResponse.objects.filter(binding=binding).exists()):
        raise proofs.ReceiptError('new_public_draft_required', 422)
    group = binding.survey_profile.group_code
    try:
        validate_context(group, level, programme, YEARS[level][0] if group in LEVELS and level in YEARS else '')
    except ValueError as exc:
        raise ValidationError(str(exc)) from None
    if binding.instrument_version.instrument.code not in {'F01', 'F02', 'F03', 'F04', 'F05', 'F06'}:
        raise proofs.ReceiptError('unsupported_instrument', 422)
    public = PublicCollection.objects.create(binding=binding, level=level, programme=programme)
    proofs._admin_event(actor, r.scope, 'public.configured', 'rounds.binding', binding.pk)
    return public


def validate_population(binding, snapshot):
    """No roster may be retained as the eligibility source of public rounds."""
    if (not snapshot or snapshot.status != 'frozen' or not snapshot.source_id
            or snapshot.source.source_type != 'aggregate' or snapshot.members.exists()
            or set(snapshot.counts_by_group) != {binding.survey_profile.group_code}
            or snapshot.counts_by_group[binding.survey_profile.group_code] < 1):
        raise ValidationError('ใช้จำนวนอ้างอิงรวมที่ตรึงแล้ว โดยไม่มีรายชื่อผู้ตอบ / Use a frozen aggregate reference count without a respondent roster.')


@transaction.atomic
def set_published(actor, binding_id, value):
    enabled()
    if type(value) is not bool:
        raise proofs.ReceiptError('invalid_publication', 422)
    binding = RoundInstrument.objects.select_related('collection_round__scope', 'survey_profile',
                                                    'instrument_version__instrument').get(pk=binding_id)
    r = CollectionRound.objects.select_for_update().get(pk=binding.collection_round_id)
    binding.collection_round = r
    surveys.require_manager(actor, binding)
    public = PublicCollection.objects.select_for_update().get(binding=binding)
    if value:
        if r.status not in {'ready', 'open'} or r.close_at <= timezone.now():
            raise proofs.ReceiptError('round_unavailable')
        validate_population(binding, r.population_snapshot)
        policy = ReceiptPolicy.objects.get(binding=binding)
        proofs._policy_valid(policy)
        from apps.surveys.schema import respondent_schema
        from apps.surveys.validation import validate_schema
        validate_schema(binding.survey_profile)
        for locale in ('th', 'en'):
            respondent_schema(binding.survey_profile, {}, locale)
    public.published = value
    public.save(update_fields=['published'])
    if not value:
        PublicSession.objects.filter(binding=binding, spent=False).delete()
    proofs._admin_event(actor, r.scope, 'public.published' if value else 'public.withdrawn', 'rounds.binding', binding.pk)
    return public


def available(public):
    enabled()
    binding = public.binding
    if not public.published or public.contract_version != VERSION:
        raise surveys.SurveyConflict('ยังไม่เปิดแบบประเมินนี้ / Assessment unavailable.')
    try:
        policy = ReceiptPolicy.objects.get(binding=binding)
    except ReceiptPolicy.DoesNotExist:
        raise surveys.SurveyConflict('ยังไม่เปิดแบบประเมินนี้ / Assessment unavailable.') from None
    proofs._policy_valid(policy)
    validate_population(binding, binding.collection_round.population_snapshot)
    surveys._open(binding)
    if binding.survey_profile.annual_target_id:
        # An all-leader campaign cannot quietly become a subset of convenient
        # targets when another target is unpublished, closed or not configured.
        siblings = leadership_collections(binding, all_groups=True)
        now = timezone.now()
        if any(not row.published or not row.binding.collection_round.accepting_at(now) for row in siblings):
            raise surveys.SurveyConflict('ชุดประเมินผู้บริหารยังเปิดไม่ครบ / The complete leadership assessment set is not open yet.')
    return binding


def leadership_collections(binding, *, all_groups=False, require_complete=True):
    target = binding.survey_profile.annual_target
    if target is None:
        return [binding.public_collection]
    from apps.leadership.models import AnnualTarget
    if require_complete and AnnualTarget.objects.filter(plan=target.plan, status='draft').exists():
        raise ValidationError('ยังตรวจทะเบียนผู้บริหารไม่ครบ / The leadership register still has draft targets.')
    expected = set(AnnualTarget.objects.filter(plan=target.plan, status='ready').values_list('pk', flat=True))
    if not require_complete:
        expected = set(AnnualTarget.objects.filter(plan=target.plan).values_list('pk', flat=True))
    rows = list(PublicCollection.objects.filter(binding__survey_profile__annual_target_id__in=expected,
        binding__survey_profile__group_code__in=['ST1', 'ST2']).select_related(
            'binding__collection_round', 'binding__survey_profile').order_by('binding_id'))
    pairs = {(row.binding.survey_profile.annual_target_id, row.binding.survey_profile.group_code) for row in rows}
    if require_complete and (not expected or pairs != {(target_id, group) for target_id in expected for group in ('ST1', 'ST2')}):
        raise ValidationError('เตรียมรอบสาธารณะครบทุกผู้บริหารทุกตำแหน่งทั้ง ST1 และ ST2 ก่อน / Prepare every leader and position for both ST1 and ST2 first.')
    return rows if all_groups else [row for row in rows if row.binding.survey_profile.group_code == binding.survey_profile.group_code]


@sensitive_variables()
@transaction.atomic
def start(binding_id, context, existing_secret=''):
    enabled()
    public = PublicCollection.objects.select_related('binding__collection_round', 'binding__survey_profile',
                                                     'binding__instrument_version__instrument').get(binding_id=binding_id)
    CollectionRound.objects.select_for_update().get(pk=public.binding.collection_round_id)
    public.refresh_from_db()
    binding = available(public)
    # Expired unspent slots carry only transient context; do not retain them.
    PublicSession.objects.filter(binding=binding, spent=False, expires_at__lte=timezone.now()).delete()
    try:
        if not isinstance(context, dict) or set(context) != {'group', 'level', 'programme', 'year'}:
            raise ValueError
        expected = context_for(public, context['year'])
        if context != expected:
            raise ValueError
    except (ValueError, TypeError):
        raise proofs.ReceiptError('invalid_public_context', 422) from None
    # Repeated Start on the same form preserves the transient session.
    if isinstance(existing_secret, str) and SECRET.fullmatch(existing_secret):
        previous = PublicSession.objects.filter(secret_hash=proofs.digest(existing_secret), spent=False,
            binding=binding, year=context['year'], expires_at__gt=timezone.now()).first()
        if previous:
            return existing_secret
    secret = 'NXP1-'+secrets.token_hex(32)
    PublicSession.objects.create(binding=binding, secret_hash=proofs.digest(secret), year=context['year'],
                                 expires_at=min(binding.collection_round.close_at, timezone.now()+timedelta(hours=24)))
    return secret


@sensitive_variables()
def read_session(secret):
    enabled()
    if not isinstance(secret, str) or not SECRET.fullmatch(secret):
        raise surveys.SurveyConflict('กรุณาเลือกแบบประเมินอีกครั้ง / Select an assessment again.')
    session = PublicSession.objects.select_related('binding__collection_round', 'binding__survey_profile',
        'binding__instrument_version__instrument', 'binding__translation_bundle', 'binding__public_collection').filter(
            secret_hash=proofs.digest(secret), spent=False, expires_at__gt=timezone.now()).first()
    if not session:
        raise surveys.SurveyConflict('ช่วงตอบหมดอายุหรือส่งสำเร็จแล้ว / Session expired or already submitted.')
    available(session.binding.public_collection)
    if session.year:
        session.binding.survey_profile._public_year = 'public-year-'+session.year
    return session


@sensitive_variables()
@transaction.atomic
def save(secret, payload, revision):
    session = read_session(secret)
    binding = session.binding
    CollectionRound.objects.select_for_update().get(pk=binding.collection_round_id)
    locked = PublicSession.objects.select_for_update().get(pk=session.pk)
    if locked.spent or locked.secret_hash != proofs.digest(secret) or locked.expires_at <= timezone.now():
        raise surveys.SurveyConflict('ส่งคำตอบไปแล้วหรือช่วงตอบหมดอายุ / Already submitted or session expired.')
    if type(revision) is not int or revision != 0:
        raise surveys.SurveyConflict('Session changed.')
    # Recheck publication after obtaining the collection lock.
    binding.public_collection.refresh_from_db()
    available(binding.public_collection)
    answers, completion = surveys.normalize(binding.survey_profile, payload, submitting=True)
    locked.spent, locked.secret_hash, locked.expires_at, locked.year = True, None, None, ''
    locked.save(update_fields=['spent', 'secret_hash', 'expires_at', 'year'])
    response = AnonymousResponse.objects.create(binding=binding, group_code=binding.survey_profile.group_code,
                                                answers=answers, completion=completion)
    return str(response.pk), completion
