"""Presentation taxonomy. Never remap respondent keys, frozen wording or dimensions."""
import json
from functools import lru_cache
from pathlib import Path
from django.utils.translation import get_language


@lru_cache(maxsize=1)
def registry():
    return json.loads((Path(__file__).resolve().parents[2] / 'catalog/group_registry.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def _index():
    return {row['code']: row for row in registry()['groups']}


def group_info(code, language=None, fallback=''):
    """Exact group keys only: never apply to question IDs or competency dimensions."""
    code = str(code or '')
    lang = 'en' if (language or get_language() or 'th').startswith('en') else 'th'
    row = _index().get(code)
    if row is None:
        name = fallback if fallback and fallback != code else ('Unregistered group' if lang == 'en' else 'ยังไม่มีคำอธิบายในทะเบียน')
        return dict(code=code, name=name, label=name, display=f'{code} · {name}', parent_code='', parent_name='', description='', category='', known=False, source='unknown')
    parent = _index().get(row['parent'])
    name = row['name'][lang]
    parent_code = parent['code'] if parent else ''
    parent_name = parent['name'][lang] if parent else ''
    label = f'{name} ({parent_code} · {parent_name})' if parent else name
    category = next(c[lang] for c in registry()['categories'] if c['key'] == row['category'])
    return dict(code=code, name=name, label=label, display=f'{code} · {label}', parent_code=parent_code,
                parent_name=parent_name, description=row['description'][lang], category=category,
                category_key=row['category'], known=True, source=row['source'])


def group_label(code, fallback='', language=None):
    return group_info(code, language, fallback)['label']


def group_display(code, fallback='', language=None):
    return group_info(code, language, fallback)['display']


def group_choices(codes):
    return [(code, group_display(code)) for code in codes]


def export_group(code, fallback=''):
    """Stable Thai reference metadata, separate from immutable numeric result fields."""
    row = group_info(code, 'th', fallback)
    return [row['name'], row['parent_code'], row['parent_name'], row['category'], row['description']]


EXPORT_COLUMNS = ['group_name', 'parent_group_code', 'parent_group_name', 'group_category', 'group_description']
