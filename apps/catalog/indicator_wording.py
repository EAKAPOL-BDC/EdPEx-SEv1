"""Explicit, reviewable wording revisions; originals and formula bindings stay fixed."""
import json
from pathlib import Path
from django.core.exceptions import ValidationError
from django.db import transaction
from apps.accounts.permissions import require_permission
from .models import InstrumentVersion, InstrumentContent, ContentTranslation, source_hash
from .services import clone_instrument_version, source_texts, edit_translation, _audit
from .management_services import check_editor, prepare_translations

REVISION = 'indicator-wording-20260917'
SUPPORTED = {'F01', 'F02', 'F03', 'F04', 'F06'}
INSTRUCTIONS = {
    'F01': ('ตอบจากประสบการณ์ในปีการศึกษาและช่วงวันที่ที่แสดงในรอบนี้ ส่วนความพึงพอใจให้เลือกระดับที่ตรงกับคุณ ส่วนความไม่พึงพอใจให้ตอบว่าเคยมีหรือไม่มีประสบการณ์นั้น หากไม่เคยใช้บริการหรือประเมินไม่ได้ ให้เลือกตัวเลือกที่ระบุไว้ ข้อความเข้าใจเกี่ยวกับองค์กรเลือก “ไม่ทราบ” ได้ ไม่ต้องเดา ไม่ต้องระบุชื่อ รหัสนิสิต หรือข้อมูลที่ระบุตัวคุณในข้อเสนอแนะ',
            'Answer from your experience in the academic year and dates shown for this round. Rate satisfaction separately from whether you experienced dissatisfaction. If you have no relevant experience or cannot assess an item, use the corresponding option. For organizational knowledge, you may select “Do not know”; there is no need to guess. Do not include your name, student ID or identifying details in suggestions.'),
    'F02': ('ตอบเฉพาะบริการหรือความร่วมมือที่คุณเกี่ยวข้องในปีงบประมาณและช่วงวันที่ที่แสดงในรอบนี้ แยกความพึงพอใจออกจากการเคยพบเรื่องที่ไม่พึงพอใจ หากไม่มีประสบการณ์ให้เลือกตัวเลือกที่ระบุไว้ ข้อความเข้าใจเกี่ยวกับองค์กรเลือก “ไม่ทราบ” ได้ ไม่ต้องเดา ไม่ต้องระบุชื่อ ชื่อผู้ติดต่อ หรือข้อมูลที่ระบุตัวคุณในข้อเสนอแนะ',
            'Answer about services or partnerships you experienced during the fiscal year and dates shown for this round. Rate satisfaction separately from whether you experienced dissatisfaction. Use the provided option if you have no relevant experience. For organizational knowledge, you may select “Do not know” instead of guessing. Do not include your name, contact names or identifying details in suggestions.'),
    'F03': ('ตอบจากประสบการณ์ในปีงบประมาณและช่วงวันที่ที่แสดงในรอบนี้ ส่วนปัจจัยในการทำงานให้บอกความพึงพอใจของคุณทีละด้าน ข้อเลือกปัจจัยสำคัญให้เลือกไม่เกิน 3 เรื่อง ข้อความสุขให้ยึดช่วง 3 เดือนตามคำถาม โดย 0 คือมีความสุขน้อยที่สุด ไม่ใช่เว้นว่าง ไม่ต้องระบุชื่อ รหัสบุคลากร หรือข้อมูลที่ระบุตัวคุณในข้อเสนอแนะ',
            'Answer from your experience in the fiscal year and dates shown for this round. Rate your satisfaction with each work factor. Select no more than three priority factors. The happiness question refers to the stated three-month period; 0 is the lowest happiness rating, not a blank answer. Do not include your name, staff ID or identifying details in suggestions.'),
    'F04': ('ก่อนตอบ ตรวจชื่อผู้ถูกประเมิน ตำแหน่ง หลักสูตรถ้ามี และช่วงเวลาที่แสดง ให้คะแนนเฉพาะงานในช่วงนั้นตามที่คุณมีข้อมูล หากมีข้อมูลไม่เพียงพอให้เลือกตัวเลือกที่ระบุไว้ ไม่ให้คะแนนต่ำแทนการไม่มีข้อมูล กรณีเปลี่ยนผู้ดำรงตำแหน่งให้ตอบแยกตามรายการที่คุณได้รับสิทธิ์ ไม่ต้องระบุชื่อหรือข้อมูลที่ระบุตัวคุณในข้อเสนอแนะ',
            'Before answering, check the evaluatee, position, programme if applicable, and displayed assessment period. Rate only work within that period that you can assess. Use the insufficient-information option when needed; do not substitute a low score for missing information. When office holders change, complete each separately authorized assessment. Do not include your name or identifying details in suggestions.'),
    'F06': ('ประเมินความสามารถของตนเองตามงานที่ทำในปีงบประมาณและช่วงวันที่ที่แสดง ส่วน M ถามการทำงานตามพันธกิจ ส่วน T ถามการทำงานตามกลยุทธ์ ให้เลือกคะแนนตามความสามารถจริง หากข้อ M หรือ T ไม่เกี่ยวข้องกับหน้าที่ ให้เลือกไม่เกี่ยวข้องและระบุเหตุผลสั้น ๆ โดยไม่ใส่ข้อมูลที่ระบุตัวคุณ ข้อนั้นจะไม่ถูกนับเป็นศูนย์ ไม่ต้องแนบหลักฐาน',
            'Assess your own ability based on your work in the fiscal year and dates shown. Section M concerns institutional missions; section T concerns strategies. Select the score that reflects your ability. For M or T items unrelated to your duties, select not applicable and give a brief reason without identifying details. Such items are excluded rather than scored zero. Evidence is not required.'),
}


@transaction.atomic
def prepare(actor, source, new_version, token):
    source = InstrumentVersion.objects.select_for_update().select_related('instrument__scope').get(pk=source.pk)
    require_permission(actor, 'catalog.edit', source.instrument.scope)
    code = source.instrument.code
    if code not in SUPPORTED:
        raise ValidationError('F05 ใช้ขั้นตอนเตรียมแบบสอบถามเชิงปริมาณ / Use the quantitative F05 preparation workflow.')
    check_editor(actor, source, token)
    target = clone_instrument_version(actor, source, new_version)
    changes = json.loads(Path(__file__).with_name('data').joinpath('indicator_wording.json').read_text(encoding='utf-8'))
    changed, preserved, overrides = [], [], {}
    from .presentation import instrument_title
    target.title_th=instrument_title(target.title_th)
    title=target.contents.filter(content_key=code+'.title').first()
    if title and instrument_title(title.text_th)!=title.text_th:
        title.text_th=instrument_title(title.text_th);title.save()
        if code=='F06':overrides[code+'.title']='F06 Personnel competency, skills, capability and values self-assessment'
    for question in target.questions.all():
        change = changes.get(question.question_id)
        if not change:
            continue
        if question.text_th != change['original_th']:
            preserved.append(question.question_id)
            continue
        question.text_th = change['th']
        question.save()
        changed.append(question.question_id)
        overrides[question.question_id + '.text'] = change['en']
    stock = json.loads(Path(__file__).with_name('data').joinpath('indicator_instruction_history.json').read_text(encoding='utf-8'))
    existing = target.contents.filter(content_key=code+'.instruction').first()
    replace_stock = existing is None or existing.text_th in (stock.get(code), INSTRUCTIONS[code][0])
    key = code + ('.instruction' if replace_stock else '.indicator-instruction')
    content, _ = InstrumentContent.objects.get_or_create(version=target, content_key=key,
        defaults={'kind':'instruction', 'audience':'respondent', 'text_th':INSTRUCTIONS[code][0]})
    content.text_th, content.kind, content.audience, content.active = INSTRUCTIONS[code][0], 'instruction', 'respondent', True
    content.save()
    overrides[key] = INSTRUCTIONS[code][1]
    target.instructions_curated = False
    target.source_metadata = {**target.source_metadata, 'wording_revision':REVISION,
        'wording_changed':changed, 'wording_custom_preserved':preserved,
        'wording_custom_instructions_preserved':not replace_stock}
    target.save()
    # Use the normal review machinery. No inherited approval; no publication here.
    bundle = prepare_translations(actor, target.pk)
    texts = source_texts(target)
    for content_key, english in overrides.items():
        for locale, value in (('th',texts[content_key]),('en',english)):
            entry, _ = ContentTranslation.objects.get_or_create(bundle=bundle, content_key=content_key, locale=locale,
                defaults={'text':value,'status':'needs_review','source_hash':source_hash(texts[content_key])})
            edit_translation(actor, entry, value)
    _audit(actor, target, 'catalog.indicator_wording_prepared', source_version=source.version,
        changed=changed, custom_preserved=preserved, revision=REVISION)
    return target
