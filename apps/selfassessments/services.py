"""Owner-only revision writes and database-backed source selection."""
from dataclasses import asdict

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.permissions import can_access, require_permission
from apps.auditlog.services import record_event
from apps.calculations.codec import digest
from apps.calculations.revisions import ResponseContext, ResponseRevision
from apps.calculations.services import IdempotencyConflict, SeriesInput, _record_calculation
from apps.calculations.types import Answer, AnswerRow
from apps.rounds.models import CollectionRound, PopulationMember, RespondentGroup, RoundInstrument
from .models import SelfAssessmentAssignment, SelfAssessmentRevision
from .validation import assignment_questions, normalize_answers


def _assignment(assignment_id):
    return SelfAssessmentAssignment.objects.select_related('round_instrument__collection_round__scope',
        'round_instrument__instrument_version__instrument', 'member__group').get(pk=assignment_id)


def _audit(actor, assignment, action, object_id, **metadata):
    r = assignment.round_instrument.collection_round
    record_event(r.organization, actor, action, 'selfassessments.revision', object_id,
                 metadata={'scope_id': str(r.scope_id), 'round_id': str(r.pk), **metadata})


@transaction.atomic
def assign_self_assessment(actor, *, round_instrument_id, member_id, user_id, duties, expected_levels, applicable_question_ids):
    raise ValidationError('ส่วนนี้เป็นประวัติการเก็บรายบุคคล ให้ใช้เมนูเก็บข้อมูลไม่ระบุตัวตน F01–F06 สำหรับรอบใหม่ / This identified workflow is historical; use anonymous collection.')
    if type(user_id) is not int or not isinstance(applicable_question_ids, list) or any(not isinstance(q, str) for q in applicable_question_ids):
        raise ValidationError('Use a user ID and a list of applicable question IDs.')
    selected = RoundInstrument.objects.select_related('collection_round__scope').get(pk=round_instrument_id)
    r = CollectionRound.objects.select_for_update().get(pk=selected.collection_round_id)
    require_permission(actor, 'selfassessment.assign', r.scope)
    selected.collection_round = r
    assignment = SelfAssessmentAssignment.objects.create(round_instrument=selected,
        member=PopulationMember.objects.get(pk=member_id), user_id=user_id, assigned_by=actor,
        duties=duties, expected_levels=expected_levels, applicable_question_ids=sorted(applicable_question_ids))
    require_permission(actor, 'selfassessment.assign', r.scope)
    _audit(actor, assignment, 'selfassessment.assigned', assignment.pk)
    return str(assignment.pk)


def list_own_assignments(actor):
    return [a for a in SelfAssessmentAssignment.objects.filter(user=actor).select_related(
        'round_instrument__collection_round__scope', 'round_instrument__instrument_version', 'member__group')
        if can_access(actor, 'self.read', a.round_instrument.collection_round.scope, owner=a.user_id)]


def read_own_assignment(actor, *, assignment_id, locale='th'):
    assignment = _assignment(assignment_id)
    r = assignment.round_instrument.collection_round
    require_permission(actor, 'self.read', r.scope, owner=assignment.user_id)
    selected = assignment.round_instrument
    translations = {t.content_key: t.text for t in selected.translation_bundle.translations.filter(locale=locale)}
    questions = []
    for qid, q in assignment_questions(assignment).items():
        if qid not in assignment.applicable_question_ids:
            continue
        questions.append({'id': qid, 'type': q.answer_type, 'text': translations.get(qid+'.text', q.text_th),
            'options': [{'code': o.code, 'label': translations.get(f'{qid}.option.{o.code}', o.label_th),
                         'value': int(o.score) if o.score is not None else o.code} for o in q.options.all()],
            'expected_level': assignment.expected_levels.get(qid),
            'allow_na': qid.startswith(('F06-M', 'F06-T')) or any(o.code == 'NA' for o in q.options.all())})
    latest = assignment.revisions.order_by('-revision').first()
    instruction_keys = selected.instrument_version.contents.filter(active=True, audience='respondent', kind='instruction').values_list('content_key', flat=True)
    instructions = [translations[key] for key in instruction_keys if key in translations]
    return {'assignment_id': str(assignment.pk), 'instrument_version': selected.instrument_version.version,
            'round': r.code, 'group': assignment.member.group.code, 'duties': assignment.duties,
            'method': 'self_report', 'questions': questions, 'instructions': instructions,
            'editable': False,
            'revision': latest.revision if latest else 0, 'status': latest.status if latest else 'not_started',
            'completeness': latest.completeness if latest else 'partial', 'answers': latest.answers if latest else {}}


@transaction.atomic
def save_revision(actor, *, assignment_id, expected_revision, status, answers, idempotency_key):
    raise ValidationError('ส่วนนี้เป็นประวัติการเก็บรายบุคคล ให้ใช้เมนูเก็บข้อมูลไม่ระบุตัวตน F01–F06 สำหรับรอบใหม่ / This identified workflow is historical; use anonymous collection.')
    assignment = _assignment(assignment_id)
    r = CollectionRound.objects.select_for_update().get(pk=assignment.round_instrument.collection_round_id)
    assignment.round_instrument.collection_round = r
    require_permission(actor, 'self.write', r.scope, owner=assignment.user_id)
    if type(expected_revision) is not int or expected_revision < 0 or status not in {'draft', 'submitted'}:
        raise ValidationError('Invalid revision or submission state.')
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 160:
        raise ValidationError('Provide a bounded request key.')
    normalized, completeness = normalize_answers(assignment, answers)
    checksum = digest({'revision': expected_revision, 'status': status, 'answers': normalized})
    previous = assignment.revisions.filter(idempotency_key=idempotency_key).first()
    if previous:
        if previous.request_hash != checksum:
            raise IdempotencyConflict('This key was already used with different answers.')
        return {'revision': previous.revision, 'status': previous.status, 'completeness': previous.completeness, 'reused': True}
    if not r.accepting_at():
        raise ValidationError('The collection window is closed.')
    latest = assignment.revisions.order_by('-revision').first()
    if expected_revision != (latest.revision if latest else 0):
        raise IdempotencyConflict('A newer revision exists. Reload your saved answers.')
    revision = SelfAssessmentRevision.objects.create(assignment=assignment, revision=expected_revision+1,
        status=status, answers=normalized, completeness=completeness, idempotency_key=idempotency_key, request_hash=checksum)
    require_permission(actor, 'self.write', r.scope, owner=assignment.user_id)
    _audit(actor, assignment, 'selfassessment.'+status, revision.pk, revision=revision.revision, status=completeness)
    return {'revision': revision.revision, 'status': status, 'completeness': completeness, 'reused': False}


def stored_series(selected, cutoff):
    """Internal only: select every stored submission; caller cannot supply raw rows."""
    r = selected.collection_round
    if selected.instrument_version.instrument.code != 'F06':
        raise ValidationError('This source adapter supports identified F06 self-reports only.')
    if not r.population_snapshot_id:
        raise ValidationError('A frozen population is required.')
    context = ResponseContext(str(r.scope_id), str(r.pk), 'F06', selected.instrument_version.version, selected.context)
    by_group = {}
    for revision in SelfAssessmentRevision.objects.filter(assignment__round_instrument=selected, status='submitted',
            recorded_at__lte=cutoff).select_related('assignment__member__group').order_by('recorded_at', 'revision', 'pk'):
        a = revision.assignment
        row = AnswerRow(a.member.eligible_unit_key, {qid: Answer(v['status'], v.get('value'), v.get('reason', '')) for qid, v in revision.answers.items()})
        by_group.setdefault(a.member.group_id, []).append(ResponseRevision(str(revision.pk), context, row,
            revision.revision, 'submitted', revision.recorded_at, revision.recorded_at))
    groups = list(RespondentGroup.objects.filter(scope=r.scope, code__in=r.population_snapshot.counts_by_group))
    inputs = []
    for binding in selected.instrument_version.bindings.order_by('indicator__code'):
        for group in groups:
            if group.code not in binding.group_rules.get('group_codes', []):
                continue
            for dimension in binding.dimensions or [None]:
                inputs.append(SeriesInput(selected.pk, binding.pk, group.pk, dimension,
                    responses=tuple(by_group.get(group.pk, ()))))
    if not inputs:
        raise ValidationError('No applicable result series is configured.')
    return inputs


@transaction.atomic
def calculate_self_assessments(actor, *, round_instrument_id, cutoff, idempotency_key, dry_run=False):
    from apps.calculations.models import StoredSourceSelection
    selected = RoundInstrument.objects.select_related('instrument_version__instrument', 'collection_round').get(pk=round_instrument_id)
    r = CollectionRound.objects.select_for_update(of=('self',)).select_related('scope', 'population_snapshot').get(pk=selected.collection_round_id)
    require_permission(actor, 'calculation.run', r.scope)
    selected.collection_round = r
    receipt = _record_calculation(actor, round_id=r.pk, inputs=stored_series(selected, cutoff), cutoff=cutoff,
        idempotency_key=idempotency_key, dry_run=dry_run, permissions=('calculation.run',))
    if not dry_run:
        StoredSourceSelection.objects.get_or_create(run_id=receipt.run_id,
            defaults={'round_instrument': selected, 'source_kind': 'f06_revisions'})
    require_permission(actor, 'calculation.run', r.scope)
    return asdict(receipt)
