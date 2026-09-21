"""Closed server-side branching over the reviewed, pinned survey schema."""
import re
from datetime import date
from django.core.exceptions import ValidationError
from apps.catalog.models import source_hash
from apps.catalog.services import source_texts


def questions(profile):
    items = list(profile.binding.instrument_version.questions.filter(active=True, audience='respondent').prefetch_related('options').order_by('question_id'))
    items.sort(key=lambda q: (0 if q.question_id.split('-')[1].startswith('P') else 2 if q.question_id.split('-')[1].startswith('O') else 1, q.question_id))
    return {q.question_id:q for q in items if not q.question_id.startswith('F06-P') and (not q.question_id.startswith('F06-') or profile.group_code in q.group_codes)}


def fixed(profile, q):
    code = profile.binding.instrument_version.instrument.code
    # Public intake contract 2026-09-19 pins a new, explicit study-year key.
    # Never reinterpret the old option_5 (5+) or option_6 (coursework).
    if q.question_id == 'F01-P03' and getattr(profile, '_public_year', ''):
        return profile._public_year
    if q.question_id == code+'-P01':
        return profile.group_code
    if q.answer_type == 'context_reference':
        return profile.binding.context
    if q.question_id == 'F02-P03':
        return profile.counting_unit
    return None


def visible(profile, q, payload):
    if profile.group_code not in q.group_codes:
        return False
    if profile.binding.instrument_version.instrument.code == 'F04' and payload.get('F04-P03',{}).get('value') == 'none' and not q.question_id.startswith('F04-P'):
        return False
    rule = q.visibility_rule
    op = rule.get('op', 'in_group')
    if op == 'in_group':
        return True
    if op == 'eq':
        return payload.get(rule['question_id'], {}).get('value') == rule['value']
    if op == 'context_role_and_information':
        return profile.assessor_role == rule['role'] and payload.get('F04-P03', {}).get('value') in rule['information']
    raise ValidationError('Unsupported survey visibility rule.')


def options(profile, q):
    choices = sorted(q.options.all(),key=lambda o:(o.position,o.code))
    if q.question_id == 'F01-P03':
        choices = [o for o in choices if o.code in profile.study_options]
    return choices


def normalize(profile, payload, *, submitting=False):
    if profile.binding.instrument_version.instrument.code == 'F06':
        from types import SimpleNamespace
        from apps.selfassessments.validation import normalize_answers
        assignment=SimpleNamespace(round_instrument=profile.binding,member=SimpleNamespace(group=SimpleNamespace(code=profile.group_code)),applicable_question_ids=list(questions(profile)))
        return normalize_answers(assignment,payload)
    qs = questions(profile)
    if not isinstance(payload, dict) or set(payload) - qs.keys():
        raise ValidationError('คำถามไม่ตรงกับรุ่นนี้ / Unknown survey question.')
    if any(not isinstance(v,dict) for v in payload.values()):
        raise ValidationError('Invalid survey answer shape.')
    normalized, complete = {}, True
    for qid, q in qs.items():
        if not visible(profile,q,payload):
            normalized[qid] = {'status':'not_shown'}
            continue
        server_value = fixed(profile,q)
        if server_value is not None:
            if qid in payload and payload[qid] != {'status':'answered','value':server_value}:
                raise ValidationError('เปลี่ยนกลุ่มหรือบริบทคำเชิญไม่ได้ / Invitation context cannot be changed.')
            normalized[qid] = {'status':'answered','value':server_value}
            continue
        value = payload.get(qid, {'status':'skipped'})
        if not isinstance(value, dict) or set(value) - ({'status','value','month'} if qid == 'F02-P04' else {'status','value'}):
            raise ValidationError('Invalid survey answer shape.')
        status, raw = value.get('status'), value.get('value')
        if status not in {'answered','skipped','not_applicable','unable_to_assess'}:
            raise ValidationError('Invalid answer status.')
        opts = options(profile,q)
        if status == 'answered':
            if q.answer_type == 'integer_scale':
                allowed = {int(o.score) for o in opts if o.score is not None and o.answer_status == 'answered'}
                valid = type(raw) is int and raw in allowed
            elif q.answer_type in {'single_choice','multi_choice'}:
                allowed = {o.code for o in opts if o.answer_status == 'answered'}
                if q.answer_type == 'multi_choice':
                    valid = isinstance(raw,list) and all(isinstance(v,str) for v in raw) and bool(raw) and len(set(raw)) == len(raw) and set(raw) <= allowed
                    if qid == 'F03-G08' and valid:
                        valid = len(raw) <= 3 and ('none' not in raw or len(raw) == 1)
                else:
                    valid = isinstance(raw,str) and raw in allowed
            elif q.answer_type == 'decimal':
                from decimal import Decimal,InvalidOperation
                try:
                    n=Decimal(raw) if isinstance(raw,str) else Decimal('NaN')
                    valid=n.is_finite() and 0<=n<=8784 and n.as_tuple().exponent>=-2
                except InvalidOperation:valid=False
            elif q.answer_type == 'text':
                valid = isinstance(raw,str) and bool(raw.strip()) and len(raw) <= 500
            else:
                valid = False
            if not valid:
                raise ValidationError(f'{qid}: ตรวจตัวเลือกหรือความยาวคำตอบ / Check the selected options or text length.')
        elif raw is not None:
            raise ValidationError('Non-answer states cannot contain a value.')
        if status == 'not_applicable' and not any(o.answer_status == 'not_applicable' for o in opts):
            raise ValidationError(f'{qid}: ไม่มีตัวเลือกไม่เกี่ยวข้อง / Not-applicable is unavailable.')
        # K "do not know" is option U (answered, incorrect), never a missing score.
        if status == 'unable_to_assess' and (q.answer_type == 'text' or '-K' in qid):
            raise ValidationError(f'{qid}: เลือกคำตอบหรือข้าม / Select an option or skip.')
        if status in {'skipped','unable_to_assess'} and q.answer_type != 'text':
            complete = False
        normalized[qid] = {'status':status, **({'value':raw} if status == 'answered' else {})}
        if qid == 'F02-P04' and status == 'answered' and raw == 'month_year':
            month = value.get('month','')
            if not isinstance(month,str) or not re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])',month):
                raise ValidationError('F02-P04: ระบุเดือนและปี ค.ศ. / Enter a month and year.')
            normalized[qid]['month'] = month
    if profile.binding.instrument_version.instrument.code == 'F04':
        info = normalized.get('F04-P03', {})
        if submitting and info.get('status') != 'answered':
            raise ValidationError('กรุณาระบุว่ามีข้อมูลเพียงพอหรือไม่ / Indicate whether you have enough information.')
        if info.get('value') == 'none':
            # No rating survives this branch; receipt explains the non-assessment.
            return normalized, 'unable_to_assess'
    if submitting and is_quantitative_f05(profile):
        missing=[qid for qid,a in normalized.items() if a['status']!='answered']
        if missing:raise ValidationError('กรุณาตอบให้ครบทั้ง 8 ข้อก่อนส่ง ไม่ได้อบรมให้กรอก 0 ชั่วโมงหรือเลือกไม่ได้เข้าร่วม / Complete all eight items before submitting: '+', '.join(missing))
        from decimal import Decimal
        if Decimal(normalized['F05-Y01']['value'])==0 and any(normalized['F05-Y%02d'%i]['value']=='yes' for i in range(2,8)):
            raise ValidationError('คุณเลือกได้รับการอบรมอย่างน้อยหนึ่งด้าน แต่กรอกชั่วโมงรวมเป็น 0 กรุณาตรวจจำนวนชั่วโมงก่อนส่ง / Training was reported but total hours are zero; check your answers.')
    return normalized, 'complete' if complete else 'partial'


def respondent_schema(profile, payload, locale, *, include_conditional=False):
    if locale not in {'th','en'}:
        raise ValidationError('Unsupported language.')
    binding, texts = profile.binding, {}
    version = binding.instrument_version
    if version.status not in {'published','retired'} or binding.translation_bundle.status not in {'published','retired'}:
        raise ValidationError('Published survey wording is unavailable.')
    originals = source_texts(version)
    for entry in binding.translation_bundle.translations.filter(locale=locale, status='approved'):
        if entry.content_key in originals and entry.reviewed_by_id and entry.reviewed_at and entry.source_hash == source_hash(originals[entry.content_key]) and entry.text.strip():
            texts[entry.content_key] = entry.text
    if set(originals) - texts.keys():
        raise ValidationError('Reviewed wording is incomplete; no draft fallback is allowed.')
    result = []
    for qid,q in questions(profile).items():
        eligible = profile.group_code in q.group_codes and (q.visibility_rule.get('op') != 'context_role_and_information' or q.visibility_rule.get('role') == profile.assessor_role)
        if (not eligible if include_conditional else not visible(profile,q,payload)) or fixed(profile,q) is not None:
            continue
        # Whitelist respondent fields: scores, correct codes and source metadata stay server-side.
        result.append({'id':qid,'type':q.answer_type,'text':texts[qid+'.text'],
            **({'visibility': q.visibility_rule, 'shown': visible(profile,q,payload)} if include_conditional else {}),
            'options':[{'code':o.code, 'label':texts[qid+'.option.'+o.code], 'status':o.answer_status,
                        'value':int(o.code) if q.answer_type == 'integer_scale' and o.code.isdigit() else o.code}
                       for o in options(profile,q)]})
    return {'data_kind':binding.collection_round.data_kind,'quantitative_f05':is_quantitative_f05(profile),'title':texts.get(version.instrument.code+'.title', version.instrument.code),
        'instructions':[texts[c.content_key] for c in version.contents.filter(active=True,audience='respondent',kind='instruction')],
        'questions':result, 'context':profile.context_en if locale == 'en' else profile.context_th,
        'reporting_year':binding.collection_round.period.reporting_year_be,'year_type':binding.collection_round.period.calendar.get_calendar_type_display(),'open_at':binding.collection_round.open_at,'close_at':binding.collection_round.close_at,
        'group':profile.group_code, 'unit':profile.counting_unit,
        'privacy':binding.collection_round.privacy_notice, 'answers':payload}


def is_quantitative_f05(profile):
    from apps.governance.f05_quantitative import VERSION
    version=profile.binding.instrument_version
    from apps.governance.f05_registry import is_quantitative_version
    return version.instrument.code=='F05' and is_quantitative_version(version.version)
