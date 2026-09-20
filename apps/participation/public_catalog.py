"""Public entry taxonomy approved on 2026-09-19; never rewrite frozen catalogs.

These routing keys are not answer-option codes. In particular, undergraduate
year 6+ must never be mapped to the old F01 option_6 (a graduate study stage).
"""
from copy import deepcopy

VERSION = '2026-09-19'


def label(th, en):
    return {'th': th, 'en': en}


CATEGORIES = [
    ('learners', 'ผู้เรียน', 'Learners', 'การเรียนรู้และประสบการณ์ของผู้เรียน', 'Learning and student experiences', ['C1', 'C2.1', 'C2.2', 'C3.1']),
    ('research', 'ผู้ให้ทุนวิจัย', 'Research funders', 'การสนับสนุนทุนวิจัยจากภาครัฐ', 'Government research funding', ['C4.1']),
    ('services', 'ผู้รับบริการวิชาการ', 'Academic service users', 'หน่วยงาน ครู บุคคลทั่วไป และชุมชน', 'Agencies, teachers, the public and communities', ['C5.1', 'C5.2', 'C5.3']),
    ('stakeholders', 'ผู้มีส่วนได้ส่วนเสีย', 'Stakeholders', 'ผู้ปกครองและศิษย์เก่า', 'Parents and alumni', ['S1', 'S3-1', 'S3-2']),
    ('partners', 'คู่ความร่วมมือ', 'Partners', 'คณะร่วมผลิตและเครือข่ายความร่วมมือ', 'Co-producing faculties and partner networks', ['CO-1', 'CO-2', 'CO-3', 'CO-4']),
    ('staff', 'บุคลากร', 'Staff', 'สายวิชาการและสายสนับสนุน', 'Academic and support staff', ['ST1', 'ST2']),
]

GROUPS = {
    'C1': ('นิสิตปริญญาตรี', 'Undergraduate students', 'เลือกหลักสูตรและชั้นปีที่กำลังศึกษา', 'Choose your current programme and year'),
    'C2.1': ('นิสิตบัณฑิตศึกษาชาวไทย', 'Thai graduate students', 'ปริญญาโทหรือปริญญาเอก', 'Master’s or doctoral programmes'),
    'C2.2': ('นิสิตบัณฑิตศึกษาชาวต่างชาติ', 'International graduate students', 'ปริญญาเอก: การบริหารการศึกษา หรือหลักสูตรและการสอน', 'Doctoral programmes in Educational Administration or Curriculum and Instruction'),
    'C3.1': ('ผู้เรียนหลักสูตร Non-degree', 'Non-degree learners', 'บุคลากรทางการศึกษาและผู้มีงานทำที่เรียน Reskill / Upskill', 'Educational personnel and employed learners taking reskilling or upskilling courses'),
    'C4.1': ('ผู้ให้ทุนวิจัยภาครัฐ', 'Government research funders', 'ผู้แทนหน่วยงานภาครัฐที่สนับสนุนทุนวิจัย', 'Representatives of government research funders'),
    'C5.1': ('หน่วยงานภาครัฐ', 'Government agencies', 'ผู้แทนหน่วยงานที่รับบริการวิชาการ', 'Agency representatives receiving academic services'),
    'C5.2': ('บุคคลทั่วไป / ครู', 'Members of the public / teachers', 'ผู้เข้าร่วมกิจกรรมบริการวิชาการ', 'Participants in academic service activities'),
    'C5.3': ('ชุมชน', 'Communities', 'ผู้แทนชุมชนที่รับบริการวิชาการ', 'Representatives of communities receiving academic services'),
    'S1': ('ผู้ปกครอง', 'Parents and guardians', 'ผู้ปกครองของนิสิตวิทยาลัยการศึกษา', 'Parents and guardians of School of Education students'),
    'S3-1': ('ศิษย์เก่าปริญญาตรี', 'Undergraduate alumni', 'ผู้สำเร็จการศึกษาระดับปริญญาตรี', 'Graduates of undergraduate programmes'),
    'S3-2': ('ศิษย์เก่าบัณฑิตศึกษา', 'Graduate alumni', 'ผู้สำเร็จการศึกษาระดับปริญญาโทหรือเอก', 'Graduates of master’s or doctoral programmes'),
    'CO-1': ('คณะร่วมผลิต', 'Co-producing faculties', 'คณะวิทยาศาสตร์ ศิลปศาสตร์ รัฐศาสตร์และสังคมศาสตร์ สถาปัตยกรรมศาสตร์และศิลปกรรมศาสตร์', 'Faculties of Science, Liberal Arts, Political and Social Science, and Architecture and Fine Arts'),
    'CO-2': ('คู่ความร่วมมือในประเทศที่มี MOU', 'Domestic MOU partners', 'หน่วยงานที่มี MOU เช่น แหล่งฝึกประสบการณ์วิชาชีพสำหรับนิสิตชั้นปีที่ 4', 'Domestic MOU partners, including fourth-year placement providers'),
    'CO-3': ('คู่ความร่วมมือต่างประเทศที่มี MOU', 'International MOU partners', 'สถาบันการศึกษาหรือภาคธุรกิจในต่างประเทศที่มี MOU', 'Overseas educational institutions or businesses with an MOU'),
    'CO-4': ('คู่ความร่วมมือไม่เป็นทางการ', 'Informal partners', 'แหล่งฝึกประสบการณ์สำหรับนิสิตชั้นปี 1–3 องค์กรปกครองส่วนท้องถิ่น และชุมชน', 'Years 1–3 placement providers, local government organisations and communities'),
    'ST1': ('บุคลากรสายวิชาการ', 'Academic staff', 'อาจารย์และบุคลากรสายวิชาการของวิทยาลัยการศึกษา', 'Academic staff of the School of Education'),
    'ST2': ('บุคลากรสายสนับสนุน', 'Support staff', 'บุคลากรสายสนับสนุนของวิทยาลัยการศึกษา', 'Support staff of the School of Education'),
}

PROGRAMMES = {
    'bachelor': [(key, 'หลักสูตรการศึกษาบัณฑิต '+th, 'B.Ed. '+en) for key, th, en in [
        ('primary', 'สาขาวิชาการประถมศึกษา', 'Primary Education'),
        ('mathematics', 'สาขาวิชาการศึกษา (คณิตศาสตร์)', 'Education (Mathematics)'),
        ('chemistry', 'สาขาวิชาการศึกษา (เคมี)', 'Education (Chemistry)'),
        ('biology', 'สาขาวิชาการศึกษา (ชีววิทยา)', 'Education (Biology)'),
        ('physical', 'สาขาวิชาการศึกษา (พลศึกษา)', 'Education (Physical Education)'),
        ('physics', 'สาขาวิชาการศึกษา (ฟิสิกส์)', 'Education (Physics)'),
        ('thai', 'สาขาวิชาการศึกษา (ภาษาไทย)', 'Education (Thai)'),
        ('english', 'สาขาวิชาการศึกษา (ภาษาอังกฤษ)', 'Education (English)'),
        ('chinese', 'สาขาวิชาการศึกษา (ภาษาจีน)', 'Education (Chinese)'),
        ('social', 'สาขาวิชาการศึกษา (สังคมศึกษา)', 'Education (Social Studies)'),
        ('music-dance', 'สาขาวิชาการศึกษา (ดนตรีและนาฏศิลป์/นาฏศิลป์)', 'Education (Music and Dance / Dance)'),
    ]],
    'master': [
        ('administration', 'กศ.ม. สาขาวิชาการบริหารการศึกษา', 'M.Ed. Educational Administration'),
        ('curriculum', 'กศ.ม. สาขาวิชาหลักสูตรและการสอน', 'M.Ed. Curriculum and Instruction'),
        ('innovator', 'กศ.ม. สาขาวิชานวัตกรทางการศึกษา', 'M.Ed. Educational Innovator'),
        ('stem', 'กศ.ม. สาขาวิชาสะเต็มศึกษา', 'M.Ed. STEM Education'),
    ],
    'doctoral': [
        ('administration', 'ปร.ด. สาขาวิชาการบริหารการศึกษา', 'Ph.D. Educational Administration'),
        ('curriculum', 'ปร.ด. สาขาวิชาหลักสูตรและการสอน', 'Ph.D. Curriculum and Instruction'),
    ],
}
LEVELS = {'C1': ['bachelor'], 'C2.1': ['master', 'doctoral'], 'C2.2': ['doctoral']}
YEARS = {'bachelor': ['1', '2', '3', '4', '5', '6+'], 'master': ['1', '2', '3+'], 'doctoral': ['1', '2', '3', '4+']}


def validate_context(group, level='', programme='', year=''):
    """Reject cross-group programme/year injection; do not infer unspecified values."""
    if any(not isinstance(value, str) for value in (group, level, programme, year)):
        raise ValueError('Public context fields must be strings')
    if group not in GROUPS:
        raise ValueError('Unknown public group')
    if group not in LEVELS:
        if any((level, programme, year)):
            raise ValueError('Study context is not applicable')
    elif (level not in LEVELS[group]
          or programme not in {p[0] for p in PROGRAMMES[level]}
          or year not in YEARS[level]):
        raise ValueError('Select a valid programme and year for this group')
    return {'group': group, 'level': level, 'programme': programme, 'year': year}


def public_catalog():
    groups = []
    for category, th, en, hint_th, hint_en, codes in CATEGORIES:
        groups.append({'key': category, 'name': label(th, en), 'hint': label(hint_th, hint_en),
                       'groups': [{'code': code, 'name': label(*GROUPS[code][:2]),
                                   'hint': label(*GROUPS[code][2:]), 'levels': LEVELS.get(code, [])}
                                  for code in codes]})
    return deepcopy({'version': VERSION, 'categories': groups, 'years': YEARS,
                     'programmes': {level: [{'key': p[0], 'name': label(*p[1:])} for p in rows]
                                    for level, rows in PROGRAMMES.items()}})
