from django.contrib import messages
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db import transaction, IntegrityError
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.permissions import require_permission, can_access
from apps.selfassessments.operator_web import page
from .models import InstrumentVersion, QuestionOption, ContentTranslation, source_hash
from .presentation import instrument_title
from . import management_forms as forms
from . import management_services as service
from .services import source_texts, translation_review_snapshot, edit_translation, clone_instrument_version


def selected(scope, version_id):
    return get_object_or_404(InstrumentVersion.objects.select_related('instrument__scope'), pk=version_id, instrument__scope=scope)


def errors(form, exc):
    if isinstance(exc, ValidationError):
        form.add_error(None, ' '.join(exc.messages))
    else:
        form.add_error(None, 'รายการซ้ำหรือข้อมูลเปลี่ยนแล้ว กรุณาตรวจใหม่ / Duplicate or changed data; please review.')


def form_page(request, scope, version, form, title, **kwargs):
    options = kwargs.get('options')
    invalid = form.is_bound and (form.errors or (options is not None and
        options.is_bound and (any(options.errors) or options.non_form_errors())))
    return render(request, 'portal/manage_form.html', {'scope': scope, 'version': version, 'form': form,
                  'title': title, **kwargs}, status=422 if invalid else 200)


@page(['GET', 'POST'])
def version_edit(request, scope, version_id):
    require_permission(request.user, 'catalog.edit', scope)
    version = selected(scope, version_id)
    instruction = version.contents.filter(content_key=version.instrument.code+'.instruction').first()
    form = forms.VersionCopyForm(request.POST if request.method == 'POST' else None, initial={
        'snapshot': service.editor_token(request.user, version), 'title_th': instrument_title(version.title_th),
        'instruction': instruction.text_th if instruction else service.translation_pack()['instructions'].get(version.instrument.code, ''),
        'instructions_curated': version.instructions_curated})
    if request.method == 'POST' and form.is_valid():
        try:
            saved_version = service.save_version_copy(request.user, version.pk, form.cleaned_data)
        except (ValidationError, IntegrityError) as exc:
            errors(form, exc)
        else:
            if any(service.bundle_readiness(saved_version, bundle)['ready'] for bundle in saved_version.translation_bundles.filter(status='draft')):
                messages.success(request, 'รับรองคำชี้แจงแล้ว ผลตรวจภาษาครบ สามารถไปหน้าเผยแพร่ได้ / Instructions checked and translations complete. Continue to publication.')
            else:
                messages.success(request, 'บันทึกคำชี้แจงแล้ว กรุณาจัดเตรียมและตรวจคำแปล / Instructions saved. Prepare and review translations.')
            return redirect('portal-catalog-detail', scope_id=scope.pk, version_id=version.pk)
    return form_page(request, scope, version, form, 'ชื่อและคำชี้แจง / Title and instructions',
                     notice='ข้อความเริ่มต้นเป็นข้อเสนอสำหรับตรวจแก้ให้ตรงกับรอบใช้งาน / Initial instructions are a draft for your review.')


@page(['GET', 'POST'])
def question_edit(request, scope, version_id, question_id=None):
    require_permission(request.user, 'catalog.edit', scope)
    version = selected(scope, version_id)
    question = get_object_or_404(version.questions, pk=question_id) if question_id else None
    initial = {k: getattr(question, k) for k in ('question_id', 'text_th', 'answer_type', 'group_codes')} if question else {'answer_type': 'text', 'group_codes': version.group_codes}
    initial['snapshot'] = service.editor_token(request.user, version)
    form = forms.QuestionForm(request.POST if request.method == 'POST' else None, version=version, question=question, initial=initial)
    queryset = question.options.order_by('position', 'pk') if question else QuestionOption.objects.none()
    option_initial = [{'id': o.pk, 'code': o.code, 'label_th': o.label_th, 'score': o.score, 'answer_status': o.answer_status} for o in queryset]
    options = forms.OptionFormSet(request.POST if request.method == 'POST' else None, initial=option_initial,
                                  form_kwargs={'question': question}, prefix='choices')
    if question and question.bindings.exists():
        options.extra = 0
        for option_form in options:
            for key in ('code', 'score', 'answer_status', 'DELETE'):
                option_form.fields[key].disabled = True
    if request.method == 'POST' and form.is_valid() and options.is_valid():
        try:
            service.save_question(request.user, version.pk, question_id, form.cleaned_data,
                                  [r for r in options.cleaned_data if r])
        except (ValidationError, IntegrityError) as exc:
            errors(form, exc)
        else:
            messages.success(request, 'บันทึกคำถามแล้ว ตรวจคำแปลอีกครั้งก่อนเผยแพร่ / Question saved. Review translations before publishing.')
            return redirect('portal-catalog-detail', scope_id=scope.pk, version_id=version.pk)
    return form_page(request, scope, version, form, 'แก้ไขคำถาม / Edit question' if question else 'เพิ่มคำถาม / Add question', options=options,
        notice='คำถามที่เชื่อมตัวชี้วัดแก้ข้อความได้ โดยคงรหัส กลุ่ม ตัวเลือก และคะแนนเดิม / Bound questions retain their calculation schema.')


@page(['GET', 'POST'])
def question_delete(request, scope, version_id, question_id):
    require_permission(request.user, 'catalog.edit', scope)
    version = selected(scope, version_id)
    question = get_object_or_404(version.questions, pk=question_id)
    form = forms.DeleteForm(request.POST if request.method == 'POST' else None, initial={'snapshot': service.editor_token(request.user, version)})
    if request.method == 'POST' and form.is_valid():
        try:
            service.delete_question(request.user, version.pk, question.pk, form.cleaned_data['snapshot'], form.cleaned_data['reason'])
        except (ValidationError, IntegrityError) as exc:
            errors(form, exc)
        else:
            messages.success(request, 'ลบคำถามฉบับร่างแล้ว / Draft question deleted.')
            return redirect('portal-catalog-detail', scope_id=scope.pk, version_id=version.pk)
    return form_page(request, scope, version, form, 'ลบคำถาม / Delete question', notice=question.text_th, destructive=True)


@page(['GET', 'POST'])
def clone(request, scope, version_id):
    require_permission(request.user, 'catalog.edit', scope)
    version = selected(scope, version_id)
    form = forms.CloneForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            new = clone_instrument_version(request.user, version, form.cleaned_data['new_version'])
        except (ValidationError, IntegrityError) as exc:
            errors(form, exc)
        else:
            messages.success(request, 'สร้างฉบับร่างรุ่นใหม่แล้ว ต้องตรวจรับรองเนื้อหาอีกครั้ง / New draft created; review is required.')
            return redirect('portal-catalog-detail', scope_id=scope.pk, version_id=new.pk)
    return form_page(request, scope, version, form, 'สร้างรุ่นใหม่ / Create a new version')


@page(['POST'])
def prepare(request, scope, version_id):
    require_permission(request.user, 'catalog.edit', scope)
    version = selected(scope, version_id)
    try:
        bundle = service.prepare_translations(request.user, version.pk)
    except (ValidationError, IntegrityError) as exc:
        messages.error(request, ' '.join(exc.messages) if isinstance(exc, ValidationError) else 'ไม่สามารถเตรียมคำแปลได้ / Unable to prepare translations.')
        return redirect('portal-catalog-detail', scope_id=scope.pk, version_id=version.pk)
    messages.success(request, 'เตรียมคำแปลรอตรวจแล้ว คำแปลที่คุณกรอกไว้ยังคงอยู่ / Draft translations prepared; existing English text was preserved.')
    return redirect('portal-catalog-review', scope_id=scope.pk, version_id=version.pk, bundle_id=bundle.pk)


@page(['GET', 'POST'])
def review(request, scope, version_id, bundle_id):
    require_permission(request.user, 'catalog.read', scope)
    version = selected(scope, version_id)
    bundle = get_object_or_404(version.translation_bundles, pk=bundle_id)
    code, error = 200, None
    can_review = can_access(request.user, 'translation.review', scope) and bundle.status == 'draft'
    if request.method == 'POST':
        require_permission(request.user, 'translation.review', scope)
        try:
            ids = request.POST.getlist('checked')
            if len(ids) > 20 or len(set(ids)) != len(ids):
                raise ValidationError('เลือกไม่เกิน 20 รายการต่อครั้ง / Select at most 20 entries.')
            rows = [(value, request.POST.get('en_'+value), request.POST.get('th_token_'+value), request.POST.get('en_token_'+value)) for value in ids]
            count = service.approve_pairs(request.user, version.pk, bundle.pk, rows)
        except (ValidationError, ObjectDoesNotExist, IntegrityError, ValueError) as exc:
            error = ' '.join(exc.messages) if isinstance(exc, ValidationError) else 'ข้อมูลเปลี่ยนแล้ว กรุณาเปิดหน้าใหม่ / Data changed; reopen this page.'
            code = 422
        else:
            messages.success(request, f'รับรองเนื้อหาไทย–อังกฤษ {count} รายการแล้ว / Approved {count} bilingual pairs.')
            return redirect(request.get_full_path())
    texts = source_texts(version)
    entries = {(t.content_key, t.locale): t for t in bundle.translations.all()}
    rows = []
    query = request.GET.get('q', '').strip()[:200]
    for key, original in sorted(texts.items()):
        th, en = entries.get((key, 'th')), entries.get((key, 'en'))
        approved = all(t and t.status == 'approved' and t.source_hash == source_hash(original) for t in (th, en))
        if request.GET.get('pending') == '1' and approved:
            continue
        if query and query.casefold() not in (key+' '+original+' '+(en.text if en else '')).casefold():
            continue
        rows.append({'key': key, 'source': original, 'th': th, 'en': en, 'approved': approved,
            'reviewable': bool(th and en and th.text == original and en.text.strip() and th.status != 'stale' and en.status != 'stale' and th.source_hash == source_hash(original) and en.source_hash == source_hash(original))})
    page_ = Paginator(rows, 10).get_page(request.GET.get('page'))
    if can_review:
        for row in page_:
            if row['reviewable']:
                th_snapshot = translation_review_snapshot(request.user, row['th'])
                en_snapshot = translation_review_snapshot(request.user, row['en'])
                # Render the exact returned snapshot, not an earlier queryset copy.
                row['source'] = th_snapshot['source_text']
                row['en'].text = en_snapshot['translation_text']
                row['reviewable'] = th_snapshot['source_text'] == en_snapshot['source_text'] and th_snapshot['translation_text'] == th_snapshot['source_text']
                row['th_token'] = th_snapshot['reviewed_token']
                row['en_token'] = en_snapshot['reviewed_token']
    return render(request, 'portal/catalog_review.html', {'scope': scope, 'version': version, 'bundle': bundle,
        'rows': page_, 'query': query, 'pending': request.GET.get('pending') == '1', 'can_review': can_review,
        'can_edit': can_access(request.user, 'catalog.edit', scope) and version.status == 'draft' and bundle.status == 'draft',
        'readiness': service.bundle_readiness(version, bundle), 'error': error}, status=code)


@page(['GET', 'POST'])
def translation_edit(request, scope, version_id, entry_id):
    require_permission(request.user, 'catalog.edit', scope)
    version = selected(scope, version_id)
    entry = get_object_or_404(ContentTranslation, pk=entry_id, bundle__instrument_version=version, locale='en')
    original = source_texts(version).get(entry.content_key)
    if original is None:
        from django.http import Http404
        raise Http404
    form = forms.TranslationForm(request.POST if request.method == 'POST' else None, initial={
        'text': entry.text or service.translation_pack()['texts'].get(original, ''),
        'revision': entry.review_revision, 'source_digest': source_hash(original)})
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                service.locked_draft(request.user, version.pk)
                # Follow the same version -> bundle -> entry lock order as the domain service.
                entry.bundle.__class__.objects.select_for_update().get(pk=entry.bundle_id)
                current = ContentTranslation.objects.select_for_update().get(pk=entry.pk)
                original_now = source_texts(selected(scope, version_id)).get(entry.content_key)
                if current.review_revision != form.cleaned_data['revision'] or not original_now or source_hash(original_now) != form.cleaned_data['source_digest']:
                    raise ValidationError('ต้นฉบับหรือคำแปลเปลี่ยนแล้ว กรุณาเปิดหน้าใหม่ / Source or translation changed.')
                edit_translation(request.user, current, form.cleaned_data['text'])
        except (ValidationError, IntegrityError) as exc:
            errors(form, exc)
        else:
            messages.success(request, 'บันทึกคำแปลรอตรวจแล้ว / Translation saved for review.')
            return redirect('portal-catalog-review', scope_id=scope.pk, version_id=version.pk, bundle_id=entry.bundle_id)
    return form_page(request, scope, version, form, 'แก้ไขคำแปล / Edit translation', notice=original, bundle=entry.bundle)


@page(['GET', 'POST'])
def publish(request, scope, version_id):
    require_permission(request.user, 'catalog.publish', scope)
    version = selected(scope, version_id)
    form = forms.PublishForm(request.POST if request.method == 'POST' else None, version=version)
    if request.method == 'POST' and form.is_valid():
        try:
            service.publish_reviewed(request.user, version.pk, form.cleaned_data['bundle'].pk)
        except (ValidationError, IntegrityError) as exc:
            errors(form, exc)
        else:
            messages.success(request, 'เผยแพร่รุ่นแบบฟอร์มแล้ว พร้อมนำไปสร้างรอบ / Form version published and available for new rounds.')
            return redirect('portal-catalog-detail', scope_id=scope.pk, version_id=version.pk)
    bundles = [{'bundle': b, **service.bundle_readiness(version, b)} for b in version.translation_bundles.all()]
    return form_page(request, scope, version, form, 'เผยแพร่แบบฟอร์ม / Publish form', readiness_rows=bundles,
        notice='เผยแพร่เพื่อใช้สร้างรอบในระบบ เมื่อเผยแพร่แล้วให้สร้างรุ่นใหม่สำหรับการแก้ไข / Publication enables collection in this system and locks this version.')
