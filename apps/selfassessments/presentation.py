"""Group the existing bound fields without changing questions, answers or validation."""
GROUPS = (
    ('A', 'สมรรถนะหลัก', 'Core competencies'),
    ('M', 'สมรรถนะด้านการบริหาร', 'Management competencies'),
    ('T', 'สมรรถนะเฉพาะงาน', 'Role-specific competencies'),
    ('D', 'ทักษะดิจิทัล', 'Digital skills'),
    ('K', 'วิสัยทัศน์และค่านิยม', 'Vision and values'),
    ('V', 'พฤติกรรมตามค่านิยม', 'Values in practice'),
)


def question_sections(form, *, english=False, assignment=False):
    sections = []
    questions = form.questions.items() if assignment else ((q['id'], q) for q in form.schema['questions'])
    questions = list(questions)
    for prefix, th, en in GROUPS:
        items = []
        for qid, question in questions:
            if not qid.startswith('F06-'+prefix):
                continue
            name = 'expected_'+qid if assignment else qid
            if name not in form.fields:
                continue
            field = form[name]
            extras = [form[qid+'__'+suffix] for suffix in ('reason', 'example', 'development_plan')
                      if qid+'__'+suffix in form.fields]
            items.append({'id': qid, 'field': field, 'label': str(field.label).removeprefix(qid+' · '), 'extras': extras,
                          'extras_open': any(f.value() or f.errors for f in extras)})
        if items:
            sections.append({'key': prefix, 'title': en if english else th, 'items': items,
                             'number': len(sections)+1})
    return sections
