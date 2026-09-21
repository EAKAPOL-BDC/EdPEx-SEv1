"""Narrow HTTP exception for the disposable respondent-only LAN preview.

Does not fake HTTPS, trust forwarding headers, expose staff login, or allow live
proofs. All ordinary settings continue requiring HTTPS for remote respondents.
"""
import ipaddress
from urllib.parse import urlsplit
from django.conf import settings
from django.http import HttpResponse


def enabled():
    db = settings.DATABASES['default']
    return (settings.SETTINGS_MODULE == 'edpex.public_demo_lan'
            and db['NAME'] == 'edpex_m1_public_ui' and str(db['PORT']) == '55469'
            and db['HOST'] in {'127.0.0.1', 'localhost', '::1'}
            and not settings.NEXORA_PARTICIPATION_ALLOW_LIVE)


def permits_http(request):
    if not enabled():
        return False
    try:
        peer = ipaddress.ip_address(request.META.get('REMOTE_ADDR', ''))
        network = ipaddress.ip_network(settings.NEXORA_SYNTHETIC_LAN_NETWORK)
        return (peer in network
                and urlsplit('//'+request.get_host()).hostname == settings.NEXORA_SYNTHETIC_LAN_HOST)
    except (ValueError, AttributeError):
        return False


class PublicPreviewOnlyMiddleware:
    PATHS = frozenset(['/survey/public/', '/survey/public/choices/', '/survey/public/start/', '/survey/public/form/'] +
        ['/survey/participation/'+name+'/' for name in ('form', 'receipt', 'qr', 'download', 'prepare', 'submit', 'status')])

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not permits_http(request):
            return HttpResponse('Synthetic LAN preview unavailable.', status=403)
        if request.path not in self.PATHS and not request.path.startswith('/static/'):
            return HttpResponse('This preview provides public test assessments only.', status=404)
        return self.get_response(request)
