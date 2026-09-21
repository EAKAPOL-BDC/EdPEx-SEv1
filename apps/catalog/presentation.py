"""Current screen labels, separate from versioned questionnaire source text."""

F05_TITLE = 'F05 แบบสำรวจข้อมูลการพัฒนาตนเองของบุคลากร'
F06_TITLE = 'F06 การประเมินสมรรถนะที่จำเป็น ทักษะ ขีดความสามารถ และค่านิยมของบุคลากร'
TITLE_ALIASES = {
    'F05 ทะเบียนการพัฒนาบุคลากร': F05_TITLE,
    'F06 การประเมินสมรรถนะ ทักษะ และค่านิยม': F06_TITLE,
    'F06 การประเมินสมรรถนะที่จำเป็น ทักษะ ขีดความสามารถ และค่านิยมของบุคลากรวิทยาลัยการศึกษา': F06_TITLE,
    'F06 การประเมินสมรรถนะที่จำเป็น ทักษะ ขีดความสามารถ และค่านิยม ของบุคลากรวิทยาลัยการศึกษา': F06_TITLE,
}


def instrument_title(value):
    """Preserve custom titles; never rewrite a frozen source or translation."""
    return TITLE_ALIASES.get(str(value), value)


def title_search_aliases(query):
    return [old for old, current in TITLE_ALIASES.items() if query.casefold() in current.casefold()]
