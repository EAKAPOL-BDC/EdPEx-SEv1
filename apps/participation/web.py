"""POST-only, no-store adapters. Bearer verifier APIs never use staff sessions."""
import json
import uuid
from functools import wraps
from urllib.parse import urlsplit
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse, HttpResponse
from django.utils.crypto import salted_hmac
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from apps.surveys import services as surveys
from apps.surveys.web import COOKIE
from . import services


def endpoint(*, bearer=False, form=False):
    def decorate(view):
        @wraps(view)
        @sensitive_post_parameters('__ALL__')
        def wrapped(request, *args, **kwargs):
            try:
                services.require_enabled()
                if request.method != 'POST':
                    raise services.ReceiptError('method_not_allowed', 405)
                host = urlsplit('//'+request.get_host()).hostname
                loopback = host in {'localhost', '127.0.0.1', '::1'} and request.META.get('REMOTE_ADDR') in {'127.0.0.1', '::1'}
                test_http = host == 'testserver' and getattr(settings, 'SURVEY_ALLOW_TEST_HTTP', False)
                from .lan_preview import permits_http
                if not request.is_secure() and not (loopback or test_http or permits_http(request)):
                    raise services.ReceiptError('https_required', 400)
                bucket = salted_hmac('participation-access', request.META.get('REMOTE_ADDR', 'unknown')).hexdigest()
                if not surveys.throttle(bucket, limit=120, window_seconds=600):
                    raise services.ReceiptError('rate_limited', 429)
                if request.content_type != ('application/x-www-form-urlencoded' if form else 'application/json'):
                    raise services.ReceiptError('json_required', 415)
                if len(request.body) > 65536:
                    raise services.ReceiptError('request_too_large', 413)
                try:
                    data = ({key: request.POST[key] for key in request.POST if key != 'csrfmiddlewaretoken'}
                            if form else json.loads(request.body))
                    if not isinstance(data, dict):
                        raise ValueError
                except (ValueError, UnicodeDecodeError):
                    raise services.ReceiptError('invalid_json', 422) from None
                if bearer:
                    header = request.headers.get('Authorization', '')
                    if not header.startswith('Bearer ') or len(header) > 100:
                        raise services.ReceiptError('unauthorized', 401)
                    raw_key = header[7:]
                    services.authenticate(raw_key)
                    response = view(request, data, raw_key, *args, **kwargs)
                else:
                    response = view(request, data, *args, **kwargs)
            except services.ReceiptError as exc:
                body = {'error': exc.code}
                if exc.missing:
                    body['missing_question_ids'] = list(exc.missing)
                response = JsonResponse(body, status=exc.status)
            except surveys.SurveyConflict:
                response = JsonResponse({'error': 'session_or_round_unavailable'}, status=409)
            except PermissionDenied:
                response = JsonResponse({'error': 'forbidden'}, status=403)
            except ValidationError:
                # No submitted values, identifying text or server details in errors.
                response = JsonResponse({'error': 'invalid_answers_or_context'}, status=422)
            except Exception:
                # Catch even under DEBUG; request bodies contain bearer secrets.
                response = JsonResponse({'error': 'temporarily_unavailable'}, status=503)
            response['Cache-Control'] = 'no-store, private'
            response['Referrer-Policy'] = 'no-referrer'
            response['X-Robots-Tag'] = 'noindex, nofollow'
            response['Content-Security-Policy'] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
            response['X-Content-Type-Options'] = 'nosniff'
            if response.status_code == 405:
                response['Allow'] = 'POST'
            if response.status_code == 401:
                response['WWW-Authenticate'] = 'Bearer'
            if response.status_code == 429:
                response['Retry-After'] = '600'
            return response
        # Only machine endpoints exempt CSRF: header tokens are mandatory and
        # cookies/user sessions never grant access. Respondent endpoints require it.
        return csrf_exempt(wrapped) if bearer else csrf_protect(wrapped)
    return decorate


def shape(data, keys):
    if set(data) != set(keys):
        raise services.ReceiptError('unexpected_fields', 422)


def verification_fields(data):
    if not isinstance(data['purpose'], str) or data['purpose'] not in services.PURPOSES:
        raise services.ReceiptError('invalid_purpose', 422)
    try:
        if not isinstance(data['policy_id'], str):
            raise ValueError
        uuid.UUID(data['policy_id'])
    except (ValueError, AttributeError):
        raise services.ReceiptError('invalid_policy_id', 422) from None


@endpoint()
def prepare(request, data):
    shape(data, ())
    return JsonResponse(services.prepare(request.COOKIES.get(COOKIE, '')))


@endpoint()
def enter(request,data):
    shape(data, ('invitation_code',))
    from . import admission
    secret=admission.exchange(data['invitation_code'])
    from django.urls import reverse
    response=JsonResponse({'next':reverse('participation-form')})
    response.set_cookie(COOKIE,secret,max_age=86400,httponly=True,secure=request.is_secure(),samesite='Strict',path='/survey/')
    return response


@endpoint()
def submit(request, data):
    shape(data, ('answers', 'revision', 'issuance_ticket', 'confirmed'))
    if data['confirmed'] is not True:
        raise services.ReceiptError('confirmation_required', 422)
    result = services.submit(request.COOKIES.get(COOKIE, ''), data['answers'], data['revision'], data['issuance_ticket'])
    response = JsonResponse(result, status=201)
    response.delete_cookie(COOKIE, path='/survey/')
    return response


@endpoint()
def status(request, data):
    shape(data, ('receipt_token',))
    return JsonResponse(services.holder_status(data['receipt_token']))


@endpoint()
def qr(request, data):
    shape(data, ('receipt_token',))
    result = services.holder_status(data['receipt_token'])
    if result['status'] != 'issued':
        raise services.ReceiptError('receipt_not_issued')
    # New interface remains test-only until invitation/privacy rollout is reviewed.
    if result['realm'] != 'test':
        raise services.ReceiptError('test_interface_only', 403)
    from django.urls import reverse
    from .qr import receipt_svg
    url = request.build_absolute_uri(reverse('participation-holder')) + '#' + data['receipt_token']
    return JsonResponse({'svg': receipt_svg(url)})


@endpoint(form=True)
def download(request, data):
    shape(data, ('receipt_token',))
    details = services.holder_status(data['receipt_token'])
    if details['status'] != 'issued' or details['realm'] != 'test':
        raise services.ReceiptError('test_receipt_required', 409)
    from django.urls import reverse
    from django.utils.html import escape
    from .qr import receipt_svg
    url=request.build_absolute_uri(reverse('participation-holder'))+'#'+data['receipt_token']
    matrix=receipt_svg(url).replace('<svg ', '<svg x="865" y="230" width="340" height="340" ', 1)
    # SVG download is an actual attachment, with no active links or executable content.
    svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="1300" height="820" viewBox="0 0 1300 820">
    <title>NEXORA test participation receipt</title><rect width="1300" height="820" fill="#faf7fd"/>
    <rect x="30" y="30" width="1240" height="760" rx="24" fill="white"/>
    <g font-family="Tahoma, sans-serif" fill="#49337f"><text x="70" y="115" font-size="44" font-weight="bold">NEXORA</text>
    <text x="70" y="180" font-size="28">หลักฐานการเข้าร่วม / Participation receipt</text>
    <text x="70" y="240" font-size="22" fill="#94602b">TEST · NOT FOR LIVE CLAIMS</text>
    <text x="70" y="305" font-size="22">{escape(details['instrument'])} · {details['reporting_year_be']} BE</text>
    <text x="70" y="360" font-size="22">{escape(details['label_th'])}</text>
    <text x="70" y="400" font-size="20">{escape(details['label_en'])}</text>
    <text x="70" y="470" font-family="monospace" font-size="19">{data['receipt_token'][:37]}</text>
    <text x="70" y="505" font-family="monospace" font-size="19">{data['receipt_token'][37:]}</text>
    <text x="70" y="575" font-size="20">เก็บรหัสเป็นความลับ / Keep this receipt private.</text>
    <text x="70" y="620" font-size="18">Test link: requires access to this preview server.</text>
    <text x="70" y="700" font-size="20">School of Education University of Phayao</text>
    <text x="70" y="745" font-size="18">Expires: {escape(details['expires_at'][:10])} · No answers or scores included.</text></g>{matrix}</svg>'''
    response=HttpResponse(svg,content_type='image/svg+xml; charset=utf-8')
    response['Content-Disposition']='attachment; filename="NEXORA-TEST-receipt.svg"'
    return response


@endpoint(bearer=True)
def verify(request, data, raw_key):
    shape(data, ('policy_id', 'purpose', 'receipt_token'))
    verification_fields(data)
    return JsonResponse(services.verify(raw_key, data['policy_id'], data['purpose'], data['receipt_token']))


@endpoint(bearer=True)
def redeem(request, data, raw_key):
    shape(data, ('policy_id', 'purpose', 'receipt_token', 'idempotency_key'))
    verification_fields(data)
    return JsonResponse(services.redeem(raw_key, data['policy_id'], data['purpose'], data['receipt_token'], data['idempotency_key']))
