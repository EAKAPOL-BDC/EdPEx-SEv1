"""Closed F06 input schema: applicability and expected levels are frozen before open."""
from django.core.exceptions import ValidationError

CONTEXT_IDS = frozenset(f'F06-P{i:02}' for i in range(1, 6))
DIMENSION_PREFIXES = ('F06-M', 'F06-T')


def assignment_questions(assignment, *, validate_configuration=False):
    version = assignment.round_instrument.instrument_version
    group = assignment.member.group.code
    questions = {q.question_id: q for q in version.questions.prefetch_related('options').filter(active=True)
                 if group in q.group_codes and q.question_id not in CONTEXT_IDS}
    if not questions or any(not qid.startswith('F06-') or q.answer_type not in {'integer_scale', 'single_choice', 'text'}
                            for qid, q in questions.items()):
        raise ValidationError('Unsupported F06 question schema.')
    if validate_configuration:
        applicable = assignment.applicable_question_ids
        levels = assignment.expected_levels
        if (not isinstance(applicable, list) or any(not isinstance(q, str) for q in applicable)
                or len(applicable) != len(set(applicable)) or not set(applicable) <= questions.keys()):
            raise ValidationError('Applicable questions must be unique IDs in this group.')
        mandatory = {qid for qid in questions if not qid.startswith(DIMENSION_PREFIXES)}
        if not mandatory <= set(applicable):
            raise ValidationError('Only role-specific M/T dimensions can be omitted by assignment.')
        scored = {qid for qid, q in questions.items() if q.answer_type == 'integer_scale'}
        if not isinstance(levels, dict) or set(levels) != scored or any(type(v) is not int or not 1 <= v <= 5 for v in levels.values()):
            raise ValidationError('Freeze an expected level from 1 to 5 for every score question.')
    return questions


def normalize_answers(assignment, payload):
    questions = assignment_questions(assignment)
    if not isinstance(payload, dict) or not set(payload) <= questions.keys():
        raise ValidationError('Unknown question, other-group question, or server-owned context field.')
    normalized, complete = {}, True
    applicable = set(assignment.applicable_question_ids)
    for qid, question in questions.items():
        value = payload.get(qid, {'status': 'missing'})
        if not isinstance(value, dict) or set(value) - {'status', 'value', 'reason', 'example', 'development_plan'}:
            raise ValidationError('Unsupported answer field. F06 does not accept evidence or assessor data.')
        status = value.get('status')
        if status not in {'answered', 'missing', 'skipped', 'not_applicable', 'unable_to_assess', 'not_shown'}:
            raise ValidationError('Unsupported answer status.')
        if qid not in applicable:
            if status not in {'missing', 'not_shown'} or set(value) - {'status'}:
                raise ValidationError('Question is outside the assigned duties.')
            normalized[qid] = {'status': 'not_shown'}
            continue
        if status == 'not_shown':
            raise ValidationError('Visibility is determined by the server.')
        answer = {'status': status}
        raw = value.get('value')
        if status == 'answered':
            if question.answer_type == 'integer_scale':
                scores = {int(o.score) for o in question.options.all() if o.score is not None and o.answer_status == 'answered'}
                if type(raw) is not int or raw not in scores or not 1 <= raw <= 5:
                    raise ValidationError('Choose an integer score from the published scale.')
            elif question.answer_type == 'single_choice':
                if not isinstance(raw, str) or raw not in {o.code for o in question.options.all() if o.answer_status == 'answered'}:
                    raise ValidationError('Choose a published option code.')
            elif not isinstance(raw, str) or not raw.strip() or len(raw) > 4000:
                raise ValidationError('Text answers must contain at most 4000 characters.')
            answer['value'] = raw
        elif raw is not None:
            raise ValidationError('Non-score states cannot contain a score or value.')
        if status == 'not_applicable':
            if not (qid.startswith(DIMENSION_PREFIXES) or any(o.code == 'NA' for o in question.options.all())):
                raise ValidationError('This question has no not-applicable option.')
            if qid.startswith(DIMENSION_PREFIXES) and not str(value.get('reason', '')).strip():
                raise ValidationError('Give a reason for a role-specific not-applicable answer.')
        for name in ('reason', 'example', 'development_plan'):
            if name in value:
                text = value[name]
                if not isinstance(text, str) or len(text) > (1000 if name == 'reason' else 4000):
                    raise ValidationError('Invalid optional text length or type.')
                if name != 'reason' and question.answer_type != 'integer_scale':
                    raise ValidationError('Examples and plans accompany score questions only.')
                if text:
                    answer[name] = text
        if question.answer_type == 'integer_scale' and status not in {'answered', 'not_applicable'}:
            complete = False
        normalized[qid] = answer
    return normalized, 'complete' if complete else 'partial'
