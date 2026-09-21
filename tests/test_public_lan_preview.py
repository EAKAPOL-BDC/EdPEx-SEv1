from types import SimpleNamespace
from datetime import timedelta
from django.test import SimpleTestCase, RequestFactory, override_settings
from django.http import HttpResponse
from django.utils import timezone
from apps.participation.lan_preview import permits_http, PublicPreviewOnlyMiddleware
from apps.participation.services import _policy_valid, ReceiptError


@override_settings(SETTINGS_MODULE='edpex.public_demo_lan',
    NEXORA_PARTICIPATION_ALLOW_LIVE=False,
    NEXORA_SYNTHETIC_LAN_NETWORK='10.51.72.0/21', NEXORA_SYNTHETIC_LAN_HOST='10.51.72.64',
    ALLOWED_HOSTS=['10.51.72.64'],
    DATABASES={'default':{'NAME':'edpex_m1_public_ui','PORT':'55469','HOST':'127.0.0.1'}})
class PublicLanTests(SimpleTestCase):
    def request(self, path='/survey/public/', peer='10.51.73.20', **kwargs):
        return RequestFactory().get(path, REMOTE_ADDR=peer, HTTP_HOST='10.51.72.64:8768', **kwargs)

    def test_exception_only_for_explicit_disposable_preview(self):
        self.assertTrue(permits_http(self.request()))
        for module in ('edpex.settings', 'edpex.public_demo', 'edpex.participation_lan'):
            with self.settings(SETTINGS_MODULE=module): self.assertFalse(permits_http(self.request()))
        with self.settings(NEXORA_PARTICIPATION_ALLOW_LIVE=True): self.assertFalse(permits_http(self.request()))
        with self.settings(DATABASES={'default':{'NAME':'production','PORT':'55469','HOST':'127.0.0.1'}}):
            self.assertFalse(permits_http(self.request()))

    def test_real_peer_checked_and_forwarded_headers_do_not_grant_access(self):
        self.assertFalse(permits_http(self.request(peer='203.0.113.1',HTTP_X_FORWARDED_FOR='10.51.73.20')))
        self.assertFalse(permits_http(self.request(peer='192.168.1.20')))

    def test_management_login_and_verifier_apis_are_unavailable(self):
        middleware=PublicPreviewOnlyMiddleware(lambda request:HttpResponse('allowed'))
        for path in ('/workspace/','/login/','/admin/','/participation/v1/verify/','/participation/v1/redeem/'):
            self.assertEqual(middleware(self.request(path)).status_code,404)
        self.assertEqual(middleware(self.request('/survey/public/')).status_code,200)
        self.assertEqual(middleware(self.request('/survey/participation/submit/')).status_code,200)

    def test_live_or_real_collection_policy_rejected(self):
        policy=SimpleNamespace(realm='test',enabled=True,expires_at=timezone.now()+timedelta(days=1),
            binding=SimpleNamespace(collection_round=SimpleNamespace(data_kind='synthetic')))
        _policy_valid(policy)
        policy.binding.collection_round.data_kind='real'
        with self.assertRaises(ReceiptError): _policy_valid(policy)
        policy.binding.collection_round.data_kind='synthetic';policy.realm='live'
        with self.assertRaises(ReceiptError): _policy_valid(policy)
