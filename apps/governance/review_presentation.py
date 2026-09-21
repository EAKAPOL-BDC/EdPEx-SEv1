"""Read-only presentation of the existing confirmation payload."""
from django.utils.dateparse import parse_datetime

LABELS = {
    'code': 'ชื่อรอบทดสอบ / Test collection name',
    'context_th': 'บริบทภาษาไทย / Thai context', 'context_en': 'บริบทภาษาอังกฤษ / English context',
    'open_at': 'เริ่มรับคำตอบ / Opens', 'due_at': 'กำหนดส่ง / Due', 'close_at': 'ปิดรับคำตอบ / Closes',
    'count': 'จำนวนสิทธิ์ทั้งหมด / Total capacity', 'source_title': 'หลักฐานจำนวนรวม / Aggregate evidence',
    'source_reference': 'เลขอ้างอิงจำนวนรวม / Aggregate reference', 'privacy_notice': 'คำชี้แจงการใช้ข้อมูล / Data-use notice',
    'label_th': 'ชื่อกิจกรรมบนหลักฐานภาษาไทย / Thai proof activity', 'label_en': 'ชื่อกิจกรรมบนหลักฐานภาษาอังกฤษ / English proof activity',
    'expires_at': 'ใช้หลักฐานสอบทานได้ถึง / Proof valid until',
    'workload': 'ตรวจภาระงานในอนาคต / Future workload verification', 'prize': 'ตรวจสิทธิ์รางวัล / Reward verification',
}
GROUPS = (
    ('01', 'ข้อมูลรอบและบริบท / Collection and context', ('code', 'context_th', 'context_en')),
    ('02', 'ช่วงเวลาและจำนวนสิทธิ์ / Schedule and capacity', ('open_at', 'due_at', 'close_at', 'count', 'source_title', 'source_reference')),
    ('03', 'ข้อมูลและหลักฐานการเข้าร่วม / Data use and participation proof', ('privacy_notice', 'label_th', 'label_en', 'expires_at', 'workload', 'prize')),
)
TH_MONTHS = ('ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.')
EN_MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')

def date_copy(value):
    try:
        parsed = parse_datetime(value)
    except (ValueError, TypeError):
        parsed = None
    if parsed is None:
        return None
    # Preserve the submitted wall-clock time instead of using browser timezone.
    clock = parsed.strftime('%H:%M')
    offset = f' (UTC{parsed.strftime("%z")})' if parsed.utcoffset() is not None else ''
    return (f'{parsed.day} {TH_MONTHS[parsed.month-1]} {parsed.year+543} · {clock} น.{offset}'
            f' / {parsed.day} {EN_MONTHS[parsed.month-1]} {parsed.year} · {clock}{offset}')

def presentation(payload, route, entries):
    if route not in {'participation-setup', 'public-assessment-setup'}:
        actions={'open_collection': 'เปิดรับคำตอบ / Open collection', 'close_collection': 'ปิดรับคำตอบ / Close collection',
                 'open': 'เปิดรับคำตอบ / Open collection', 'close': 'ปิดรอบและหยุดเผยแพร่ / Close and withdraw',
                 'publish': 'เผยแพร่ในหน้าสาธารณะ / Publish in public entry', 'withdraw': 'พักการเผยแพร่ / Withdraw publication'}
        return {'review_groups': [{'number': '01', 'title': 'ข้อมูลที่จะดำเนินการ / Submitted entries',
                                  'items': [{'label': key, 'value': value,
                                             'copy': actions.get(value) if route in {'participation-manage', 'public-assessment-manage'} and key == 'การดำเนินการ' else None}
                                            for key, value in entries]}]}
    labels = dict(LABELS)
    definitions = GROUPS
    if route == 'public-assessment-setup':
        labels.update(code='ชื่อรอบสาธารณะ / Public collection name', count='จำนวนอ้างอิงรวม / Aggregate reference population',
            group_codes='กลุ่มผู้ตอบทั้งสองกลุ่ม / Both respondent groups', count_st1='จำนวนอ้างอิง ST1 / ST1 reference count', count_st2='จำนวนอ้างอิง ST2 / ST2 reference count', group_code='กลุ่มผู้ตอบ / Respondent group', programme_key='หลักสูตร / Programme', counting_unit='หน่วยนับอ้างอิง / Reference counting unit')
        definitions = tuple((number, title, keys + (('group_code', 'group_codes', 'programme_key') if number == '01' else ('counting_unit', 'count_st1', 'count_st2') if number == '02' else ())) for number, title, keys in GROUPS)
    groups = []
    for number, title, keys in definitions:
        items = []
        for key in keys:
            for value in payload.get(key, ['']):
                copy = None
                if key in {'workload', 'prize'}:
                    copy = 'เลือกใช้ / Selected' if value else 'ไม่เลือกใช้ / Not selected'
                elif key in {'open_at', 'due_at', 'close_at', 'expires_at'}:
                    copy = date_copy(value)
                elif key in {'group_code', 'group_codes'}:
                    from apps.participation.public_catalog import GROUPS as PUBLIC_GROUPS
                    names = PUBLIC_GROUPS.get(value)
                    copy = names[0]+' / '+names[1] if names else None
                elif key == 'programme_key':
                    from apps.participation.public_catalog import PROGRAMMES
                    names = next(((th,en) for level, rows in PROGRAMMES.items() for code,th,en in rows if level+':'+code == value), None)
                    copy = names[0]+' / '+names[1] if names else 'ไม่ใช้กับกลุ่มนี้ / Not applicable'
                elif key == 'counting_unit':
                    copy = {'person':'บุคคล / Person','organization_representative':'ผู้แทนองค์กร / Organisation representative','community_representative':'ผู้แทนชุมชน / Community representative'}.get(value)
                items.append({'label': labels[key], 'value': value, 'copy': copy,
                              'wide': key in {'code', 'privacy_notice'},
                              'selected': key in {'workload', 'prize'} and bool(value)})
        groups.append({'number': number, 'title': title, 'items': items})
    from .confirmation import display_entries
    extra = display_entries({key: values for key, values in payload.items() if key not in labels}, route=route)
    if extra:
        groups.append({'number': '04', 'title': 'ข้อมูลเพิ่มเติม / Additional entries',
                       'items': [{'label': label, 'value': value} for label, value in extra]})
    return {'review_groups': groups, 'review_is_setup': True,
            'review_is_public': route == 'public-assessment-setup',
            'review_name': next(iter(payload.get('code', [])), ''),
            'review_capacity': next(iter(payload.get('count', [])), '')}
