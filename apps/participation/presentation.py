"""Approved F01 layout with pinned, reviewed respondent wording (test realm only).

No draft catalog fallback, answer keys, invitation IDs or roster data reach HTML.
The prototype and integrated page intentionally share the same layout sources.
"""
import json
import re
import secrets
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit
from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.csrf import csrf_protect
from apps.surveys import schema, services as surveys
from apps.surveys.web import COOKIE
from . import services
from .models import ReceiptPolicy

PREVIEW = Path(__file__).resolve().parents[2] / 'previews' / 'f01'


def form_data(profile):
    if profile.binding.instrument_version.instrument.code != 'F01' or profile.group_code != 'C1':
        raise services.ReceiptError('unsupported_form', 422)
    # Evaluate every permitted conditional branch through the same reviewed
    # respondent-schema gate; never serialize models or private source metadata.
    qs = [q for q in schema.questions(profile).values() if profile.group_code in q.group_codes]
    branch = {}
    for q in qs:
        rule = q.visibility_rule
        if rule.get('op', 'in_group') == 'eq':
            branch[rule['question_id']] = {'status': 'answered', 'value': rule['value']}
        elif rule.get('op', 'in_group') != 'in_group':
            raise ValidationError('Unsupported F01 branch.')
    th, en = (schema.respondent_schema(profile, branch, locale) for locale in ('th', 'en'))
    english = {q['id']: q for q in en['questions']}
    models = {q.question_id: q for q in qs}
    items = []
    for q in th['questions']:
        eq = english[q['id']]
        opts_en = {o['code']: o for o in eq['options']}
        rule = models[q['id']].visibility_rule
        public_rule = ({'op': 'eq', 'question_id': rule['question_id'], 'value': str(rule['value'])}
                       if rule.get('op') == 'eq' else {'op': 'in_group'})
        items.append({'id': q['id'], 'text': q['text'], 'text_en': eq['text'], 'type': q['type'],
                      'fixed': None, 'fixed_en': None, 'rule': public_rule,
                      'options': [{'value': str(o['value']), 'label': o['label'],
                                   'label_en': opts_en[o['code']]['label'], 'status': o['status']}
                                  for o in q['options']]})
    if getattr(profile, '_public_year', ''):
        year = profile._public_year.removeprefix('public-year-')
        items.insert(0, {'id': 'F01-P03', 'text': 'ชั้นปีที่เลือก', 'text_en': 'Selected study year',
                        'type': 'single_choice', 'fixed': 'ปี '+year, 'fixed_en': 'Year '+year,
                        'rule': {'op': 'in_group'}, 'options': []})
    return {'questions': items, 'instructions': '\n'.join(th['instructions']),
            'instructions_en': '\n'.join(en['instructions']),
            'context_th': th['context'], 'context_en': en['context'],
            'reporting_year': th['reporting_year'], 'privacy': th['privacy'], 'group': th['group']}


def page(view):
    @wraps(view)
    @csrf_protect
    def wrapped(request):
        nonce = secrets.token_urlsafe(24)
        request.participation_nonce = nonce
        try:
            services.require_enabled()
            if request.method != 'GET':
                raise services.ReceiptError('method_not_allowed', 405)
            host = urlsplit('//'+request.get_host()).hostname
            local = host in {'127.0.0.1', 'localhost', '::1'} and request.META.get('REMOTE_ADDR') in {'127.0.0.1', '::1'}
            test = host == 'testserver' and getattr(settings, 'SURVEY_ALLOW_TEST_HTTP', False)
            from .lan_preview import permits_http
            if not (request.is_secure() or local or test or permits_http(request)):
                raise services.ReceiptError('https_required', 400)
            response = view(request)
        except services.ReceiptError as exc:
            response = HttpResponse('ยังเปิดหน้านี้ไม่ได้ / Page unavailable.', status=exc.status)
        except surveys.SurveyConflict:
            response = redirect('participation-holder')
        except Exception:
            response = HttpResponse('ยังเปิดหน้านี้ไม่ได้ กรุณาลองอีกครั้ง / Page unavailable. Please retry.', status=503)
        response['Cache-Control'] = 'no-store, private'
        # Ordinary same-origin attachment POSTs need a non-null Origin for CSRF.
        # Fragments never enter referrers; external destinations receive none.
        response['Referrer-Policy'] = 'same-origin'
        response['X-Robots-Tag'] = 'noindex, nofollow'
        response['X-Content-Type-Options'] = 'nosniff'
        response['Content-Security-Policy'] = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
            "img-src 'self' data:; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        return response
    return wrapped


def runtime(request):
    return {'csrf': get_token(request), **{key: reverse('participation-'+key)
            for key in ('prepare', 'submit', 'status', 'qr', 'holder', 'download')}}


def html_document(request, html, data, scripts, styles):
    from django.template.loader import render_to_string
    styles += '\n' + (PREVIEW.parents[1] / 'apps/accounts/static/portal/experience.css').read_text(encoding='utf-8')
    html = html.replace('<!-- SHARED_IDENTITY -->', render_to_string('portal/components/brand_identity.html'))
    html = html.replace('<!-- SHARED_INSTITUTION -->', render_to_string('portal/components/institution.html'))
    html = re.sub(r'<footer[^>]*>.*?</footer>', '<footer class="nx-unified-footer">' + render_to_string('portal/components/footer_shared.html') + '</footer>', html, flags=re.S)
    # Escape HTML parser delimiters even for approved institution-authored text.
    payload = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('&', '\\u0026')
    html = re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]+>', '', html)
    html = html.replace('/* PREVIEW_DATA */', payload).replace('/* PREVIEW_CSS */', styles)
    html = html.replace('/* PREVIEW_JS */', scripts)
    html = html.replace('PREVIEW_LOGO', '/static/portal/branding/nexora-logo.png').replace('PREVIEW_MASCOT', '/static/portal/branding/nexora-mascot.png').replace('PREVIEW_QR', '')
    html = html.replace('<script', f'<script nonce="{request.participation_nonce}"').replace('<style', f'<style nonce="{request.participation_nonce}"')
    return HttpResponse(html)


@page
def form(request):
    session = surveys.read_session(request.COOKIES.get(COOKIE, ''))
    profile = session.invitation.binding.survey_profile
    policy = ReceiptPolicy.objects.get(binding=profile.binding)
    services._policy_valid(policy)
    if policy.realm != 'test':
        raise services.ReceiptError('test_interface_only', 403)
    data = form_data(profile)
    data['runtime'] = {**runtime(request), 'revision': session.revision, 'realm': policy.realm,
                       'unlinked':request.COOKIES.get(COOKIE,'').startswith(('NXS1-', 'NXP1-')),
                       'public':request.COOKIES.get(COOKIE,'').startswith('NXP1-'),
                       'locale':'en' if request.GET.get('lang')=='en' else 'th'}
    html = (PREVIEW / 'index.html').read_text(encoding='utf-8')
    html = html.replace('NEXORA · F01 Design Preview', 'NEXORA · F01 Test Collection')
    styles = '\n'.join((PREVIEW / n).read_text(encoding='utf-8') for n in ('style.css','refinement.css','v3.css','connected.css'))
    scripts = '\n'.join((PREVIEW / n).read_text(encoding='utf-8') for n in ('validation.js','transport.js','connected.js','app.js'))
    return html_document(request, html, data, scripts, styles)


@page
def holder(request):
    data = {'runtime': runtime(request)}
    return html_document(request, (PREVIEW/'holder.html').read_text(encoding='utf-8'), data,
                         '\n'.join((PREVIEW/n).read_text(encoding='utf-8') for n in ('transport.js','connected.js','holder.js')),
                         '\n'.join((PREVIEW/n).read_text(encoding='utf-8') for n in ('style.css','refinement.css','v3.css','connected.css')))


@page
def entry(request):
    from .admission import enabled
    enabled()
    data={'runtime':{**runtime(request),'enter':reverse('participation-enter')}}
    return html_document(request,(PREVIEW/'entry.html').read_text(encoding='utf-8'),data,
                         (PREVIEW/'entry.js').read_text(encoding='utf-8'),
                         '\n'.join((PREVIEW/n).read_text(encoding='utf-8') for n in ('style.css','refinement.css','v3.css','connected.css')))
