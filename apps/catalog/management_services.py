"""Draft editing and review orchestration for the scoped management portal."""
import json
from functools import lru_cache

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.permissions import require_permission
from .models import (InstrumentVersion, InstrumentContent, Question, QuestionOption,
                     TranslationBundle, ContentTranslation, source_hash)
from .services import (_audit, source_texts, edit_translation, approve_translation,
                       publish_bundle, publish_instrument_version)


def locked_draft(actor, version_id):
    version = InstrumentVersion.objects.select_for_update().select_related('instrument__scope').get(pk=version_id)
    require_permission(actor, 'catalog.edit', version.instrument.scope)
    if version.status != 'draft' or version.translation_bundles.exclude(status='draft').exists():
        raise ValidationError('รุ่นนี้ล็อกแล้ว กรุณาสร้างรุ่นใหม่ก่อนแก้ไข / Clone this locked version before editing.')
    return version


def draft_state(version):
    """Protect against stale editor tabs without adding mutable revision columns."""
    state = {'title': version.title_th, 'curated': version.instructions_curated,
             'status': version.status, 'texts': source_texts(version),
             'questions': list(version.questions.order_by('pk').values(
                 'id', 'question_id', 'text_th', 'answer_type', 'active', 'group_codes')),
             'options': list(QuestionOption.objects.filter(question__version=version).order_by('pk').values(
                 'id', 'code', 'label_th', 'score', 'answer_status', 'position'))}
    return source_hash(json.dumps(state, sort_keys=True, ensure_ascii=False, default=str))


def editor_token(actor, version):
    return signing.dumps({'actor': actor.pk, 'version': str(version.pk), 'state': draft_state(version)}, salt='catalog.editor.v1')


def check_editor(actor, version, token):
    try:
        data = signing.loads(token, salt='catalog.editor.v1', max_age=7200)
    except (signing.BadSignature, TypeError, ValueError):
        raise ValidationError('หน้าแก้ไขหมดอายุ กรุณาเปิดหน้าใหม่ / Reopen the editor.')
    if data != {'actor': actor.pk, 'version': str(version.pk), 'state': draft_state(version)}:
        raise ValidationError('มีการแก้ไขข้อมูลแล้ว กรุณาเปิดหน้าใหม่ / Content changed; reopen the editor.')


@lru_cache(maxsize=1)
def translation_pack():
    # Separate from the immutable seed specification and never auto-approved.
    path = settings.BASE_DIR / 'apps' / 'catalog' / 'data' / 'english_drafts.json'
    return json.loads(path.read_text(encoding='utf-8'))


@transaction.atomic
def prepare_translations(actor, version_id):
    version = locked_draft(actor, version_id)
    bundle = version.translation_bundles.order_by('-created_at', '-pk').first()
    if bundle is None:
        bundle = TranslationBundle.objects.create(instrument_version=version, bundle_version='web-1')
    TranslationBundle.objects.select_for_update().get(pk=bundle.pk)
    pack, changed = translation_pack()['texts'], 0
    # Parent locks serialize every draft edit; existing pairs can be loaded once.
    entries = {(entry.content_key,entry.locale):entry for entry in bundle.translations.all()}
    for key, original in source_texts(version).items():
        for locale in ('th', 'en'):
            entry, created = entries.get((key,locale)), False
            if entry is None:
                entry, created = ContentTranslation.objects.get_or_create(bundle=bundle, content_key=key, locale=locale,
                    defaults={'source_hash': source_hash(original), 'text': original if locale == 'th' else '', 'status': 'needs_review'})
                entries[(key,locale)] = entry
            if locale == 'th':
                if entry.text != original or entry.source_hash != source_hash(original) or entry.status == 'stale':
                    edit_translation(actor, entry, original)
                    changed += 1
            elif not entry.text.strip() and original in pack:
                edit_translation(actor, entry, pack[original])
                changed += 1
            elif entry.status == 'stale' and entry.source_hash == source_hash(original):
                # A version edit invalidates every pair. Unchanged sources can
                # re-enter review with their existing English, without approval.
                edit_translation(actor, entry, entry.text)
                changed += 1
            elif created:
                changed += 1
    _audit(actor, version, 'catalog.drafts_prepared', bundle_id=str(bundle.pk), changed=changed)
    return bundle


@transaction.atomic
def save_version_copy(actor, version_id, data):
    version = locked_draft(actor, version_id)
    check_editor(actor, version, data['snapshot'])
    version.title_th = data['title_th']
    version.instructions_curated = data['instructions_curated']
    version.save()
    for key, kind, value in ((version.instrument.code + '.title', 'title', data['title_th']),
                             (version.instrument.code + '.instruction', 'instruction', data['instruction'])):
        content, _ = InstrumentContent.objects.get_or_create(version=version, content_key=key,
            defaults={'kind': kind, 'audience': 'respondent', 'text_th': value})
        content.text_th, content.active, content.audience = value, True, 'respondent'
        content.save()
    _audit(actor, version, 'catalog.instructions_edited')
    return version


@transaction.atomic
def save_question(actor, version_id, question_id, data, options):
    version = locked_draft(actor, version_id)
    check_editor(actor, version, data['snapshot'])
    question = version.questions.get(pk=question_id) if question_id else Question(version=version)
    bound = bool(question_id and question.bindings.exists())
    if bound and (question.answer_type != data['answer_type'] or sorted(question.group_codes) != sorted(data['group_codes'])):
        raise ValidationError('ข้อที่เชื่อมตัวชี้วัดต้องคงประเภทคำตอบและกลุ่มเดิม / Keep the bound question schema.')
    if question_id and question.question_id != data['question_id']:
        raise ValidationError('รหัสคำถามเดิมเปลี่ยนไม่ได้ / The question ID is fixed.')
    old_options = {str(o.pk): o for o in question.options.all()} if question_id else {}
    if bound:
        kept = {str(row['id'].pk): row for row in options if row.get('id') and not row.get('DELETE')}
        if set(kept) != set(old_options) or any(not row.get('id') and not row.get('DELETE') for row in options):
            raise ValidationError('ข้อที่เชื่อมตัวชี้วัดเพิ่มหรือลบตัวเลือกไม่ได้ / Bound options must be retained.')
        for key, row in kept.items():
            old = old_options[key]
            if (old.code, old.score, old.answer_status) != (row['code'], row.get('score'), row['answer_status']):
                raise ValidationError('ต้องคงรหัสและคะแนนตัวเลือกที่เชื่อมตัวชี้วัด / Keep bound option codes and scores.')
    if version.instrument.code == 'F06' and data['answer_type'] not in {'integer_scale', 'single_choice', 'text', 'context_reference', 'date'}:
        raise ValidationError('ประเภทคำตอบนี้ยังไม่รองรับใน F06 / Unsupported F06 answer type.')
    for name in ('question_id', 'text_th', 'answer_type', 'group_codes'):
        setattr(question, name, data[name])
    question.audience = 'respondent'
    question.save()
    used = set()
    remaining = [row for row in options if not row.get('DELETE')]
    if question.answer_type in {'integer_scale', 'single_choice', 'multi_choice'} and not remaining:
        raise ValidationError('กรุณาเพิ่มตัวเลือกคำตอบ / Add answer choices.')
    for position, row in enumerate(options):
        old = row.get('id')
        if old and str(old.pk) not in old_options:
            raise ValidationError('ตัวเลือกไม่อยู่ในคำถามนี้ / Invalid option.')
        if row.get('DELETE'):
            if old:
                old_options[str(old.pk)].delete()
            continue
        if row['code'] in used:
            raise ValidationError('รหัสตัวเลือกซ้ำกัน / Duplicate choice code.')
        used.add(row['code'])
        option = old_options[str(old.pk)] if old else QuestionOption(question=question)
        for name in ('code', 'label_th', 'score', 'answer_status'):
            setattr(option, name, row.get(name))
        option.position = position
        option.save()
    if version.instrument.code == 'F06' and question.answer_type == 'integer_scale':
        scored = [o.score for o in question.options.all() if o.answer_status == 'answered']
        if sorted(scored, key=lambda x: x if x is not None else -1) != [1, 2, 3, 4, 5]:
            raise ValidationError('F06 ต้องมีคะแนน 1–5 อย่างละหนึ่งตัวเลือก / F06 requires scores 1–5.')
    _audit(actor, version, 'catalog.question_saved', question_id=question.question_id)
    return question


@transaction.atomic
def delete_question(actor, version_id, question_id, token, reason):
    version = locked_draft(actor, version_id)
    check_editor(actor, version, token)
    question = version.questions.get(pk=question_id)
    if not reason.strip():
        raise ValidationError('ระบุเหตุผลการลบ / Give a deletion reason.')
    if question.bindings.exists():
        raise ValidationError('คำถามนี้ใช้คำนวณตัวชี้วัด จึงลบไม่ได้ / A calculation depends on this question.')
    for option in question.options.all():
        option.delete()
    qid = question.question_id
    question.delete()
    _audit(actor, version, 'catalog.question_deleted', reason, question_id=qid)


def bundle_readiness(version, bundle):
    expected = source_texts(version)
    entries = {(e.content_key, e.locale): e for e in bundle.translations.all()} if bundle else {}
    complete = 0
    for key, original in expected.items():
        for locale in ('th', 'en'):
            e = entries.get((key, locale))
            if e and e.status == 'approved' and e.reviewed_by_id and e.reviewed_at and e.text.strip() and e.source_hash == source_hash(original) and (locale != 'th' or e.text == original):
                complete += 1
    total = len(expected) * 2
    curated = version.instructions_curated and version.contents.filter(active=True, audience='respondent', kind='instruction').exists()
    return {'total': total, 'complete': complete, 'remaining': total-complete, 'curated': curated,
            'ready': bool(total and total == complete and curated), 'pairs': len(expected)}


@transaction.atomic
def approve_pairs(actor, version_id, bundle_id, rows):
    version = InstrumentVersion.objects.select_for_update().select_related('instrument__scope').get(pk=version_id)
    require_permission(actor, 'translation.review', version.instrument.scope)
    bundle = version.translation_bundles.select_for_update().get(pk=bundle_id)
    if bundle.status != 'draft' or not rows:
        raise ValidationError('เลือกเนื้อหาที่ตรวจแล้ว / Select reviewed content.')
    for th_id, en_id, th_token, en_token in rows:
        th = bundle.translations.get(pk=th_id, locale='th')
        en = bundle.translations.get(pk=en_id, locale='en', content_key=th.content_key)
        # Tokens come from the displayed GET, never regenerated on POST.
        approve_translation(actor, th, reviewed_token=th_token)
        approve_translation(actor, en, reviewed_token=en_token)
    return len(rows)


@transaction.atomic
def publish_reviewed(actor, version_id, bundle_id):
    version = InstrumentVersion.objects.select_for_update().select_related('instrument__scope').get(pk=version_id)
    require_permission(actor, 'catalog.publish', version.instrument.scope)
    bundle = version.translation_bundles.get(pk=bundle_id)
    readiness = bundle_readiness(version, bundle)
    if not readiness['curated']:
        raise ValidationError('ยังไม่ได้รับรองคำชี้แจง กรุณาเปิดหน้า ชื่อและคำชี้แจง เพื่อตรวจและยืนยัน / Instructions are not yet checked. Open Title and instructions to review and confirm.')
    if not readiness['ready']:
        raise ValidationError('เนื้อหายังตรวจไม่ครบ / Content review is incomplete.')
    if bundle.status == 'draft':
        publish_bundle(actor, bundle)
    return publish_instrument_version(actor, version)
