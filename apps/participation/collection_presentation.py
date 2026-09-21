"""Read-only, schedule-aware collection status used across staff pages."""
from django.utils import timezone


def collection_state(binding, now=None):
    now = now or timezone.now()
    r = binding.collection_round
    public = getattr(binding, 'public_collection', None)
    if r.status in {'closed', 'archived'} or r.close_at <= now:
        key, label, icon = 'closed', 'ปิดรับแล้ว / Closed', '■'
    elif r.status == 'draft':
        key, label, icon = 'draft', 'ฉบับร่าง / Draft', '✎'
    elif r.status != 'open' or not public or not public.published:
        key, label, icon = 'ready', 'ยังไม่เปิดสาธารณะ / Not public yet', '○'
    elif r.open_at > now:
        key, label, icon = 'scheduled', 'รอวันเปิด / Scheduled', '◷'
    else:
        key, label, icon = 'open', 'เปิดรับอยู่ / Open for responses', '●'
    return {'key': key, 'label': label, 'icon': icon}


def aggregate_state(bindings):
    states = [collection_state(b) for b in bindings]
    keys = {s['key'] for s in states}
    if len(keys) == 1:
        return states[0]
    if not keys:
        return {'key':'draft', 'label':'ยังไม่มีรายการ / No collections', 'icon':'○'}
    return {'key':'mixed','label':'สถานะต่างกัน / Mixed status','icon':'◐'}


def short_context(public, english=False):
    from .public_catalog import PROGRAMMES, GROUPS
    for key, th, en in PROGRAMMES.get(public.level, []):
        if key == public.programme:
            return en if english else th
    return GROUPS.get(public.binding.survey_profile.group_code, ('บริบทการประเมิน','Assessment context'))[int(english)]
