"""Deterministic synthetic sources, evaluated by the production formula engine.

These sources and results live only in DemoDataset/DemoSeries, never in real
responses, attendance, calculation runs, review requests or approvals.
"""
import hashlib
import json
from pathlib import Path
from decimal import Decimal
from .catalog import Catalog, CATALOG_DIR
from .engine import calculate, Attendance, ACTIVITY_KEYS, _ANSWER_KEY
from .types import Answer, AnswerRow, FrozenPopulation
from .codec import encode_spec, encode_row, encode_attendance, encode_result, digest, replay_input
from .types import CalculationInputError

DEMO_KEY = 'DEMO-2569-v1'


def validated_series(rows):
    """Validate stored demo numbers on read, just as actual results are replayed."""
    valid, invalid = [], 0
    for row in rows:
        try:
            spec = row.source['spec']
            if (digest(row.source) != row.source_hash or replay_input(row.source) != row.result
                    or row.unit != row.result['unit'] or row.formula_key != spec['formula_key']
                    or row.formula_version != spec['formula_version']):
                raise ValueError('Demo source/result mismatch')
        except (CalculationInputError, ValueError, KeyError, TypeError, ArithmeticError):
            invalid += 1
        else:
            valid.append(row)
    return valid, invalid


def number(*parts):
    return int(hashlib.sha256('|'.join(map(str, parts)).encode()).hexdigest()[:12], 16)


def build_series():
    catalog = Catalog()
    names = json.loads((CATALOG_DIR / 'demo_indicator_labels.json').read_text())
    groups = {r['code']: r['label']['th'] for r in json.loads((CATALOG_DIR / 'groups.json').read_text())}
    output = []
    for code, indicator in catalog.indicators.items():
        binding = indicator['binding']
        form = binding['source_question_ids'][0].split('-')[0]
        for group in binding['group_codes']:
            ids = tuple(f'DEMO-{group}-{i:02}' for i in range(1, 21))
            population = FrozenPopulation(f'{DEMO_KEY}-{group}', ids)
            for dimension in (binding.get('series_dimensions', [None]) if binding['formula_id'] in {'DIMENSION_SAT','SELF_DIMENSION','SELF_BEHAVIOUR'} else [None]):
                spec = catalog.spec(code, group_code=group, dimension=dimension)
                rows, attendance = [], []
                if spec.formula_key in ACTIVITY_KEYS:
                    for i, unit in enumerate(ids):
                        if number(group, i, 'attend') % 10 < 8:
                            categories = frozenset(c for c in ['T45','T46','T48','T47S','T47H','T47E'] if number(group, i, c) % 10 < 6)
                            attendance.append(Attendance(unit, 'DEMO-TRAINING', 'DEMO-SESSION',
                                Decimal(6 + number(group, i, 'hours') % 25), Decimal(4), categories,
                                'accepted', number(group, i, 'visit') % 2 == 0, True))
                else:
                    for i, unit in enumerate(ids[:16]):
                        answers = {}
                        # The same question/group/unit always gets the same synthetic answer.
                        for q in spec.question_ids:
                            n = number(DEMO_KEY, group, unit, q)
                            scale = catalog.questions[q]['scale_id']
                            if scale == 'DIS': value = 'Y' if n % 10 < 2 + number(group) % 3 else 'N'
                            elif spec.formula_key == 'K_EXTERNAL':
                                index = binding['source_question_ids'].index(q)
                                value = ('seen' if n % 10 < 8 else 'not_seen') if index == 0 else (_ANSWER_KEY[index-1] if n % 10 < 7 else 'U')
                            elif spec.formula_key == 'HAPPINESS_10': value = 5 + n % 6
                            else: value = (4 + n % 2) if n % 100 < 55 + number(group) % 30 else 1 + n % 3
                            answers[q] = Answer('answered', value)
                        rows.append(AnswerRow(unit, answers))
                source = {'schema_version':1, 'spec':encode_spec(spec),
                    'population':{'snapshot_id':population.snapshot_id,'unit_ids':list(ids)},
                    'rows':[encode_row(row, spec.question_ids) for row in rows],
                    'attendances':[encode_attendance(a) for a in attendance]}
                result = encode_result(calculate(spec, rows, population=population, attendances=attendance))
                if result['status'] != 'computed': raise ValueError(f'Demo not computed: {code}/{group}/{dimension}')
                output.append(dict(indicator_code=code, indicator_label=names.get(code, indicator['display_name']['th']),
                    form_code=form, group_code=group, group_label=groups[group], dimension=dimension or '',
                    dimension_label=catalog.questions.get(dimension, {}).get('text', {}).get('th', {'S':'Service Mind','E':'Ethics & Excellence','U':'Unity','P':'Professional','overall':'ภาพรวมค่านิยม SEUP'}.get(dimension, dimension or '')),
                    unit=result['unit'], direction=indicator['direction'], formula_key=spec.formula_key,
                    formula_version=spec.formula_version, context_key=f'{DEMO_KEY}-{form}', source=source,
                    source_hash=digest(source), result=result))
    return output
