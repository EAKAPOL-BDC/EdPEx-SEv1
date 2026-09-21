"""Build a standalone, database-free F01 C1 design preview from repository wording.

Uses the same stock wording replacements as indicator_wording.prepare, without
importing Django, reading credentials, publishing a form, or exporting answers.
Local edits made only in the live catalog are not included.
"""
import argparse
import base64
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_data():
    def read(relative):
        return json.loads((ROOT / relative).read_text(encoding='utf-8'))
    wording = read('apps/catalog/data/indicator_wording.json')
    english = read('apps/catalog/data/english_drafts.json')['texts']
    english['ยังประเมินไม่ได้'] = 'Unable to assess'
    def institutional_name(value):
        return value.replace('College of Education', 'School of Education').replace('the College', 'the School').replace("The College", "The School") if value else value
    scales = {s['scale_id']: s['options'] for s in read('catalog/scales.json')}
    tree = ast.parse((ROOT / 'apps/catalog/indicator_wording.py').read_text(encoding='utf-8'))
    instructions = next(ast.literal_eval(n.value)['F01'] for n in tree.body
                        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'INSTRUCTIONS' for t in n.targets))
    items = []
    for row in read('catalog/questions.json'):
        if row['instrument_id'] != 'F01' or 'C1' not in row['group_codes'] or row.get('audience', 'respondent') != 'respondent':
            continue
        qid, text = row['question_id'], row['text']['th']
        change = wording.get(qid)
        text_en = english.get(text)
        if change and text == change['original_th']:
            text = change['th']
            text_en = change['en']
        # Explicit public-field allowlist: no answer keys, formula data or scores.
        options = [{'value': o['code'], 'label': o['label']['th'], 'label_en': english.get(o['label']['th'])} for o in
                   (row.get('options') or scales.get(row.get('scale_id'), []))]
        if qid == 'F01-P03':
            options = [o for o in options if o['value'] in {f'option_{i}' for i in range(1, 6)}]
        fixed = {'F01-P01': 'C1 · นิสิตระดับปริญญาตรี', 'F01-P02': 'หลักสูตรตัวอย่าง — กำหนดจากรอบเก็บข้อมูล'}.get(qid)
        if options and row['answer_type'] != 'multi_choice' and '-K' not in qid and not fixed and not any(o['label_en'] == 'Unable to assess' for o in options):
            options.append({'value': 'unable_to_assess', 'label': 'ยังประเมินไม่ได้', 'label_en': 'Unable to assess'})
        for option in options:
            option['label_en'] = institutional_name(option['label_en'])
            if option['label'] == 'พึงพอใจน้อยที่สุด':
                option['label_en'] = 'Very low satisfaction'
        if not text_en or any(not o['label_en'] for o in options):
            raise ValueError(f'Missing English preview translation: {qid}')
        items.append({'id': qid, 'text': text, 'text_en': institutional_name(text_en), 'type': row['answer_type'], 'options': options,
                      'rule': row.get('visibility_condition', {'op': 'in_group'}), 'fixed': fixed,
                      'fixed_en': {'F01-P01': 'C1 · Undergraduate students', 'F01-P02': 'Sample programme — set by this collection round'}.get(qid)})
    return {'instructions': instructions[0], 'instructions_en': instructions[1], 'questions': items}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = ROOT / 'previews/f01'
    html = (source / 'index.html').read_text(encoding='utf-8')
    payload = json.dumps(build_data(), ensure_ascii=False).replace('<', '\\u003c')
    html = html.replace('/* PREVIEW_CSS */', '\n'.join((source / name).read_text(encoding='utf-8') for name in ('style.css', 'refinement.css', 'v3.css')))
    html = html.replace('/* PREVIEW_DATA */', payload)
    html = html.replace('/* PREVIEW_JS */', '\n'.join((source / name).read_text(encoding='utf-8') for name in ('validation.js', 'app.js')))
    logo = ROOT / 'apps/accounts/static/portal/branding/nexora-logo.png'
    html = html.replace('PREVIEW_LOGO', 'data:image/png;base64,' + base64.b64encode(logo.read_bytes()).decode('ascii'))
    mascot = ROOT / 'apps/accounts/static/portal/branding/nexora-mascot.png'
    html = html.replace('PREVIEW_MASCOT', 'data:image/png;base64,' + base64.b64encode(mascot.read_bytes()).decode('ascii'))
    # An explicitly reusable DEMO receipt, never a production credential.
    html = html.replace('PREVIEW_QR', (source / 'demo-qr.svg').read_text(encoding='utf-8'))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding='utf-8')
    print(f'Built {args.output.name}: {len(build_data()["questions"])} question definitions; no database used.')


if __name__ == '__main__':
    main()
