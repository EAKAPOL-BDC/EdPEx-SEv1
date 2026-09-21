"""Anonymous public directory and respondent pages, separate from staff sessions."""
from django.core.exceptions import ValidationError
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from apps.surveys.web import public_page, COOKIE
from apps.surveys.forms import ResponseForm, posted_payload
from apps.catalog.assessment_ui import sections
from . import public_admission as admission, services
from .models import PublicCollection
from .public_catalog import public_catalog, validate_context
from .web import endpoint, shape


@public_page
def home(request):
    if not getattr(settings, 'NEXORA_PUBLIC_ASSESSMENTS_ENABLED', False):
        return HttpResponse(status=404)
    admission.enabled()
    if request.method != 'GET':
        return HttpResponse(status=405)
    from apps.surveys.services import cleanup
    cleanup()
    return render(request, 'participation/public_home.html', {'catalog': public_catalog(),
        'public_preview': settings.SETTINGS_MODULE in {'edpex.public_demo', 'edpex.public_demo_lan'},
        'lan_preview': settings.SETTINGS_MODULE == 'edpex.public_demo_lan'})


@endpoint()
def choices(request, data):
    shape(data, ('group', 'level', 'programme', 'year'))
    admission.enabled()
    try:
        validate_context(**data)
    except (ValueError, TypeError):
        raise services.ReceiptError('invalid_public_context', 422) from None
    now = timezone.now()
    rows = PublicCollection.objects.filter(published=True, contract_version='2026-09-19',
        binding__survey_profile__group_code=data['group'], level=data['level'], programme=data['programme'],
        binding__collection_round__status='open', binding__collection_round__open_at__lte=now,
        binding__collection_round__close_at__gt=now,
        binding__receiptpolicy__enabled=True, binding__receiptpolicy__expires_at__gt=now).select_related(
            'binding__survey_profile', 'binding__collection_round__scope', 'binding__collection_round__period',
            'binding__instrument_version__instrument', 'binding__receiptpolicy').order_by(
                'binding__instrument_version__instrument__code', 'binding__collection_round__code')
    result = []
    for row in rows:
        try:
            b = admission.available(row)
        except (services.ReceiptError, ValidationError):
            continue
        result.append({'id': str(b.pk), 'instrument': b.instrument_version.instrument.code,
                       'title': {'th': b.receiptpolicy.label_th, 'en': b.receiptpolicy.label_en},
                       'context': {'th': b.survey_profile.context_th, 'en': b.survey_profile.context_en},
                       'year': b.collection_round.period.reporting_year_be,
                       'closes': b.collection_round.close_at.isoformat(), 'realm': b.receiptpolicy.realm})
    return JsonResponse({'collections': result, 'leadership': 'all_positions' if data['group'] in {'ST1', 'ST2'} else ''})


@endpoint()
def start(request, data):
    shape(data, ('binding_id', 'context'))
    try:
        secret = admission.start(data['binding_id'], data['context'], request.COOKIES.get(COOKIE, ''))
    except (PublicCollection.DoesNotExist, ValueError, ValidationError):
        raise services.ReceiptError('assessment_unavailable', 409) from None
    response = JsonResponse({'next': reverse('public-assessment-form')})
    response.set_cookie(COOKIE, secret, max_age=86400, httponly=True, secure=request.is_secure(),
                        samesite='Strict', path='/survey/')
    return response


def respondent_form(profile, payload, locale, posted=None):
    form = ResponseForm(profile, payload, 0, locale, *([posted] if posted is not None else []), include_conditional=(posted is None or posted.get('enhanced_js') == '1'))
    for name, field in form.fields.items():
        if name == 'revision' or name.endswith(('-reason', '-month')):
            continue
        if hasattr(field, 'choices'):
            field.choices = [(key, text) for key, text in field.choices if key != '']
        optional = '-O' in name
        field.help_text = ('Optional suggestion. Avoid identifying details.' if locale == 'en' else
                           'ข้อเสนอแนะไม่บังคับ กรุณาไม่ใส่ข้อมูลที่ระบุตัวบุคคล') if optional else (field.help_text or
                           ('Required when shown; an explicit unable-to-assess option is accepted.' if locale == 'en' else
                            'ต้องตอบเมื่อแสดงข้อนี้ เลือกประเมินไม่ได้ได้เมื่อมีตัวเลือก'))
    return form


@public_page
def form(request):
    secret = request.COOKIES.get(COOKIE, '')
    session = admission.read_session(secret)
    profile = session.binding.survey_profile
    if (request.method == 'GET' and profile.binding.instrument_version.instrument.code == 'F01'
            and profile.group_code == 'C1' and profile.binding.receiptpolicy.realm == 'test'):
        return redirect(reverse('participation-form') + ('?lang=en' if request.GET.get('lang') == 'en' else ''))
    locale = 'en' if request.GET.get('lang') == 'en' else 'th'
    payload = posted_payload(profile, request.POST) if request.method == 'POST' else {}
    response_form = respondent_form(profile, payload, locale, request.POST if request.method == 'POST' else None)
    candidate = None
    status = 200
    if request.method == 'POST':
        # Candidate is already held by this browser before transmission; it permits
        # safe holder-status recovery if the success response never arrives.
        candidate = {'receipt_token': request.POST.get('receipt_token', ''),
                     'issuance_ticket': request.POST.get('issuance_ticket', '')}
        if not services.TOKEN_RE.fullmatch(candidate['receipt_token']):
            candidate = None
        if response_form.is_valid() and request.POST.get('action') == 'submit' and candidate:
            try:
                if request.POST.get('confirm') != 'on':
                    raise ValidationError('ตรวจคำตอบและเลือกยืนยันก่อนส่ง / Review and confirm before submitting.')
                # The candidate displayed for recovery must match the signed ticket.
                from django.core import signing
                ticket = signing.loads(candidate['issuance_ticket'], salt=services.TICKET_SALT, max_age=7200)
                if ticket.get('token') != candidate['receipt_token']:
                    raise signing.BadSignature
                services.submit(secret, payload, 0, candidate['issuance_ticket'])
                response = redirect(reverse('participation-holder')+'#'+candidate['receipt_token'])
                response.delete_cookie(COOKIE, path='/survey/')
                return response
            except signing.BadSignature:
                response_form.add_error(None, 'หมดเวลายืนยัน กรุณาทบทวนอีกครั้ง / Confirmation expired. Review again.')
                candidate = None
                status = 422
            except services.ReceiptError as exc:
                for key in exc.missing:
                    if key in response_form.fields:
                        response_form.add_error(key, 'กรุณาตอบข้อนี้ / Please answer this item.')
                if not exc.missing:
                    response_form.add_error(None, 'ยังส่งไม่ได้ กรุณาตรวจข้อมูลแล้วลองใหม่ / Unable to submit. Review and retry.')
                status = exc.status
            except ValidationError as exc:
                response_form.add_error(None, exc)
                status = 422
        elif response_form.errors:
            status = 422
    candidate = candidate or services.prepare(secret)
    question_sections = sections(response_form, english=locale == 'en')
    section_order = {key:index for index,key in enumerate(['P','S','D','E','G','H','C','K','R','DE','BO','VD','AS','PC','ET','O'])}
    if profile.binding.instrument_version.instrument.code in {'F01','F02','F03','F04'}:
        question_sections.sort(key=lambda section:section_order.get(section['key'],50))
        for index,section in enumerate(question_sections,1):section['number']=index
    shown = {q['id']:q.get('shown',True) for q in response_form.schema['questions']}
    for section in question_sections:
        for item in section['items']:
            item['condition_hidden'] = not shown.get(item['id'], True)
    return render(request, 'participation/public_form.html', {'form': response_form,
        'schema': response_form.schema, 'locale': locale, 'candidate': candidate,
        'question_sections': question_sections,
        'recovery_url': reverse('participation-holder')+'#'+candidate['receipt_token']}, status=status)
