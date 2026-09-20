"""Read-only readiness and guarded lifecycle actions for synthetic F01 pools."""
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.timezone import now as server_time
from apps.rounds.models import CollectionRound, RoundInstrument
from apps.rounds.services import _check_ready, transition_round
from apps.surveys.services import require_manager
from . import admission, services
from .models import AccessPool, ReceiptPolicy

SALT = 'nexora.test.collection.control.v1'


def readiness(binding, pool):
    """A point-in-time explanation; actions always recheck inside their lock."""
    r = binding.collection_round
    now = server_time()
    policy = ReceiptPolicy.objects.filter(binding=binding).first()
    population = r.population_snapshot if r.population_snapshot_id else None
    limit = population.counts_by_group.get('C1', 0) if population else 0
    checks = []

    def add(key, label, passed, help):
        checks.append({'key': key, 'label': label, 'passed': bool(passed), 'help': help})

    add('test', 'ขอบเขตการทดสอบ / Test collection',
        r.data_kind == 'synthetic' and binding.instrument_version.instrument.code == 'F01' and binding.survey_profile.group_code == 'C1',
        'ส่วนนี้รองรับรอบข้อมูลสมมุติ F01 กลุ่ม C1 / This control supports synthetic F01 C1 collections.')
    add('form', 'แบบคำถามและคำแปล / Form and translations',
        binding.instrument_version.status == 'published' and binding.translation_bundle.status == 'published',
        'ต้องใช้รุ่นแบบคำถามและคำแปลที่เผยแพร่แล้ว / Both pinned versions must be published.')
    add('population', 'จำนวนสิทธิ์ที่ตรึงแล้ว / Frozen capacity',
        population and population.status == 'frozen' and type(limit) is int and 0 < pool.capacity <= limit,
        'ตรวจยอดรวมที่ตรึงไว้ จำนวนสิทธิ์ต้องไม่เกินยอดรวม โดยไม่ต้องเพิ่มรายชื่อ / Capacity must fit the frozen aggregate count; no roster is needed.')
    add('receipt', 'หลักฐานการเข้าร่วม / Participation proof',
        policy and policy.realm == 'test' and policy.enabled and policy.expires_at > max(now, r.close_at) and (policy.workload or policy.prize),
        'หลักฐานทดสอบต้องเปิดใช้ มีวัตถุประสงค์ และหมดอายุหลังปิดรอบ / Test proof must be enabled, have a purpose and remain valid beyond closing.')
    add('window', 'ช่วงเวลารับคำตอบ / Collection window', r.open_at <= now < r.close_at,
        'เปิดรับได้เมื่อถึงเวลาเริ่มและยังไม่ถึงเวลาปิด ไม่เปิดอัตโนมัติ / Open once the start time arrives and before closing. Opening is not automatic.')
    add('channel', 'ช่องทางคำเชิญ / Invitation access', pool.enabled,
        'หากระงับอยู่ ให้เปิดช่องทางอีกครั้งก่อนเปิดรอบ / Resume invitation access before opening the collection.')
    try:
        _check_ready(r)
        issues = []
    except ValidationError as exc:
        issues = exc.messages
    add('rules', 'ปีรายงานและข้อกำหนดของรอบ / Reporting period and collection rules', not issues,
        'ตรวจปีที่อนุมัติ คำชี้แจง ช่วงเวลาที่ยืนยัน และข้อกำหนดแบบประเมิน / Check approved period, data-use notice, confirmed dates and assessment rules.')
    passed = sum(item['passed'] for item in checks)
    return {'checks': checks, 'passed': passed, 'total': len(checks), 'issues': issues,
            'checked_at': now, 'can_open': r.status == 'ready' and passed == len(checks),
            'accepting': r.status == 'open' and passed == len(checks),
            'synthetic': r.data_kind == 'synthetic',
            'receipt_ready': next(item['passed'] for item in checks if item['key'] == 'receipt')}


def stamp(actor, binding):
    return signing.dumps({'actor': str(actor.pk), 'binding': str(binding.pk),
                          'state': binding.collection_round.status}, salt=SALT)


@transaction.atomic
def change(actor, binding_id, action, token, *, collection_name, reason=''):
    admission.enabled()
    binding = RoundInstrument.objects.select_related('collection_round__scope', 'instrument_version__instrument', 'translation_bundle', 'survey_profile').get(pk=binding_id)
    r = CollectionRound.objects.select_for_update().get(pk=binding.collection_round_id)
    binding.collection_round = r
    require_manager(actor, binding)
    if collection_name != r.code:
        raise services.ReceiptError('collection_name_changed',409)
    signed = signing.loads(token, salt=SALT, max_age=900)
    if signed != {'actor': str(actor.pk), 'binding': str(binding.pk), 'state': r.status}:
        raise signing.BadSignature('Collection state changed')
    if (r.data_kind != 'synthetic' or binding.instrument_version.instrument.code != 'F01'
        or binding.survey_profile.group_code != 'C1' or not ReceiptPolicy.objects.filter(binding=binding, realm='test').exists()):
        raise services.ReceiptError('test_collection_required', 403)
    pool = AccessPool.objects.select_for_update().get(binding=binding)
    if action == 'open_collection':
        if not readiness(binding, pool)['can_open']:
            raise services.ReceiptError('collection_not_ready', 409)
        target = 'open'
    elif action == 'close_collection' and r.status == 'open' and reason.strip():
        target = 'closed'
    else:
        raise services.ReceiptError('invalid_collection_transition', 409)
    # Existing service revalidates the lifecycle and writes its administrative audit.
    # Receipts, responses, capacity and invitations remain intact.
    return transition_round(actor, r, target, reason=reason)
