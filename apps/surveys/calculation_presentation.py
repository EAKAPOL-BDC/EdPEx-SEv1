"""Read-only guidance for the existing survey calculation/review workflow."""
from django.conf import settings
from django.urls import reverse
from apps.participation.models import AccessPool, ReceiptPolicy
from .models import AnonymousResponse


def participation_hub(selected):
    if not (getattr(settings, 'NEXORA_PARTICIPATION_ENABLED', False)
            and getattr(settings, 'NEXORA_UNLINKED_ACCESS_ENABLED', False)):
        return None
    if (selected.collection_round.data_kind == 'synthetic'
            and selected.instrument_version.instrument.code == 'F01'
            and selected.survey_profile.group_code == 'C1'
            and AccessPool.objects.filter(binding=selected).exists()
            and ReceiptPolicy.objects.filter(binding=selected, realm='test').exists()):
        return reverse('participation-results', args=[selected.collection_round.scope_id, selected.pk])
    return None


def calculation_guidance(selected):
    r = selected.collection_round
    hub = participation_hub(selected)
    public = selected.survey_profile.intake_method == 'public'
    checks = [
        {'passed': r.status in {'closed', 'review', 'approved'},
         'label': 'ปิดรับคำตอบแล้ว / Collection is closed',
         'help': 'เก็บคำตอบให้เสร็จ แล้วปิดรอบก่อนคำนวณ / Complete collection and close the round before calculating.'},
        {'passed': bool(r.population_snapshot_id and r.population_snapshot.status == 'frozen'),
         'label': 'ตรึงจำนวนผู้มีสิทธิ์แล้ว / Eligible population is frozen',
         'help': 'ต้องมีจำนวนผู้มีสิทธิ์ที่ตรึงไว้สำหรับตัวหาร / A frozen eligible population is required for denominators.'},
    ]
    if public:
        checks[1].update(label='ตรึงจำนวนอ้างอิงรวมแล้ว / Aggregate reference population is frozen',
            help='จำนวนอ้างอิงไม่ใช่จำนวนผู้ตอบที่ยืนยันตัวตน ไม่ตีความชุดคำตอบเป็นคนที่ไม่ซ้ำ / Reference totals do not verify respondent identity or uniqueness.')
    if hub or public:
        checks.append({'passed': AnonymousResponse.objects.filter(binding=selected).exists(),
            'label': 'มีคำตอบที่ส่งแล้วในรอบนี้ / This collection has submitted responses',
            'help': 'รอบนี้ไม่มีคำตอบสำหรับคำนวณ ตรวจว่าเลือกรอบถูกต้อง / There are no submitted responses to calculate. Check the selected collection.'})
    return {'checks': checks, 'ready': all(item['passed'] for item in checks),
            'back_url': reverse('survey-list', args=[r.scope_id]) if public else hub or reverse('survey-collection', args=[r.scope_id, selected.pk])}
