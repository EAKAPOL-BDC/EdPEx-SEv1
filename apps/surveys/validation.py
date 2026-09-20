"""Activation gate: reviewed wording plus the implemented branching/scoring contract."""
from django.core.exceptions import ValidationError
from apps.calculations.catalog import Catalog
from .models import SurveyProfile


def validate_round(r, snapshot):
    for binding in r.round_instruments.select_related('instrument_version__instrument'):
        version = binding.instrument_version
        code = version.instrument.code
        if code not in {'F01','F02','F03','F04','F05','F06'}:
            continue
        profile = SurveyProfile.objects.filter(binding=binding).first()
        if profile is None:
            continue  # Existing typed-source rounds do not acquire an anonymous intake.
        profile.full_clean()
        from apps.leadership.services import validate_binding
        validate_binding(binding, snapshot, accepting=True)
        if set(snapshot.counts_by_group) != {profile.group_code} or snapshot.counting_unit != profile.counting_unit:
            raise ValidationError('แยกรอบตามกลุ่มและหน่วยนับ / Use one group and counting unit per survey round.')
        from django.conf import settings
        aggregate_access=False
        from apps.participation.models import PublicCollection
        if PublicCollection.objects.filter(binding=binding).exists():
            from apps.participation.public_admission import validate_population
            validate_population(binding, snapshot)
            aggregate_access = True
        if not aggregate_access and getattr(settings,'NEXORA_UNLINKED_ACCESS_ENABLED',False) and code=='F01' and profile.group_code=='C1':
            from apps.participation.models import AccessPool, ReceiptPolicy
            aggregate_access=(AccessPool.objects.filter(binding=binding,enabled=True,capacity__lte=snapshot.counts_by_group[profile.group_code]).exists()
                and ReceiptPolicy.objects.filter(binding=binding,realm='test',enabled=True).exists()
                and snapshot.source.source_type=='aggregate' and not snapshot.members.exists())
        if not aggregate_access and snapshot.members.count() != snapshot.counts_by_group[profile.group_code]:
            raise ValidationError('ต้องมีรายชื่อหน่วยผู้มีสิทธิ์ครบก่อนออกคำเชิญ / Complete the eligibility roster first.')
        validate_schema(profile)


def validate_schema(profile):
    version = profile.binding.instrument_version
    code = version.instrument.code
    if code == 'F05':
        from apps.governance.f05_registry import for_version
        return for_version(version.version).validate_version(version)
    catalog = Catalog()
    baseline = {qid:q for qid,q in catalog.questions.items() if q['instrument_id']==code and q.get('audience','respondent')=='respondent'}
    actual = {q.question_id:q for q in version.questions.filter(active=True,audience='respondent').prefetch_related('options')}
    if actual.keys()!=baseline.keys():
        raise ValidationError('ชุดคำถามต่างจากสัญญาเก็บข้อมูลที่รองรับ / Survey questions differ from the supported contract.')
    for qid,q in actual.items():
        original=baseline[qid]
        if q.answer_type!=original['answer_type'] or q.visibility_rule!=original['visibility_condition'] or q.group_codes!=original['group_codes']:
            raise ValidationError('ชนิดคำถามหรือเงื่อนไขต่างจากรุ่นที่รองรับ / Unsupported question type or branching.')
        expected={o['code']:(o.get('score'),o.get('answer_status') or (('unable_to_assess' if original.get('scale_id') in {'AGR','ADM'} else 'not_applicable') if o['code']=='NA' else 'answered')) for o in original.get('options',[])}
        current={o.code:(o.score,o.answer_status) for o in q.options.all()}
        if current != expected:
            raise ValidationError('ตัวเลือกหรือคะแนนต่างจากสูตรที่รองรับ / Unsupported option/scoring contract.')
