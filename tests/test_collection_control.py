from datetime import timedelta
import uuid
from unittest.mock import patch
from django.conf import settings
from django.core import signing
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from apps.participation import admission, services, collection_control
from apps.participation.models import AccessPass, ReceiptPolicy, ParticipationReceipt
from apps.participation.setup import create_collection, SALT
from apps.surveys.models import AnonymousResponse
from apps.surveys.services import SurveyConflict
from tests.test_unlinked_access import fixture


@override_settings(NEXORA_PARTICIPATION_ENABLED=True, NEXORA_UNLINKED_ACCESS_ENABLED=True,
                   NEXORA_CONFIRM_IMPORTANT_ACTIONS=False)
class CollectionControlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.f = fixture()
        now = timezone.now()
        data = dict(code='Lifecycle test ready', context_th='บริบททดสอบ', context_en='Test context',
                    open_at=now-timedelta(minutes=5), due_at=now+timedelta(days=1), close_at=now+timedelta(days=2),
                    expires_at=now+timedelta(days=30), count=5, source_title='Synthetic total', source_reference='Five test slots',
                    privacy_notice='Synthetic testing only.', label_th='ทดสอบ', label_en='Test', workload=True, prize=False,
                    setup_stamp=signing.dumps({'actor': str(cls.f.actor.pk), 'source': str(cls.f.binding.pk), 'nonce': str(uuid.uuid4())},salt=SALT))
        cls.ready = create_collection(cls.f.actor, cls.f.binding, data)

    def setUp(self):
        self.client.force_login(self.f.actor)
        self.url = reverse('participation-manage', args=[self.f.scope.pk, self.ready.pk])
        self.open_url = reverse('participation-manage', args=[self.f.scope.pk, self.f.binding.pk])

    def data(self, url=None, action='open_collection'):
        page = self.client.get(url or self.url)
        return {'action': action, 'stamp': page.context['control'].initial['stamp'], 'collection_name':page.context['round'].code, 'confirm': 'on'}

    def test_readiness_get_is_read_only_and_localized(self):
        page = self.client.get(self.url)
        self.assertTrue(page.context['readiness']['can_open'])
        self.assertEqual(page.context['readiness']['passed'],7)
        self.ready.collection_round.refresh_from_db()
        self.assertEqual(self.ready.collection_round.status,'ready')
        self.assertFalse(AccessPass.objects.exists())
        self.assertContains(page,'ตรวจความพร้อมและควบคุมรอบ')
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME]='en'
        self.assertContains(self.client.get(self.url),'Readiness and collection control')
        self.assertNotContains(page,'PRIVATE-')

    @override_settings(NEXORA_CONFIRM_IMPORTANT_ACTIONS=True)
    def test_review_open_once_rechecks_paused_channel(self):
        data = self.data()
        page = self.client.post(self.url,data)
        self.assertEqual(page.status_code,200)
        self.ready.collection_round.refresh_from_db()
        self.assertEqual(self.ready.collection_round.status,'ready')
        data.update(operation_ticket=str(page.context['ticket']),operation_ack='yes')
        admission.set_enabled(self.f.actor,self.ready.pk,False)
        self.assertEqual(self.client.post(self.url,data).status_code,409)
        self.ready.collection_round.refresh_from_db()
        self.assertEqual(self.ready.collection_round.status,'ready')
        admission.set_enabled(self.f.actor,self.ready.pk,True)
        data=self.data();page=self.client.post(self.url,data)
        data.update(operation_ticket=str(page.context['ticket']),operation_ack='yes')
        self.assertEqual(self.client.post(self.url,data).status_code,302)
        self.ready.collection_round.refresh_from_db()
        self.assertEqual(self.ready.collection_round.status,'open')
        self.assertFalse(AccessPass.objects.exists())
        self.assertEqual(self.client.post(self.url,data).status_code,409)

    def test_window_policy_and_checkbox_cannot_be_bypassed(self):
        data=self.data();data.pop('confirm')
        self.assertEqual(self.client.post(self.url,data).status_code,422)
        data=self.data()
        with patch('apps.participation.collection_control.server_time',return_value=self.ready.collection_round.open_at-timedelta(seconds=1)):
            self.assertFalse(self.client.get(self.url).context['readiness']['can_open'])
            self.assertEqual(self.client.post(self.url,data).status_code,409)
        ReceiptPolicy.objects.filter(binding=self.ready).update(enabled=False)
        self.assertFalse(self.client.get(self.url).context['readiness']['can_open'])
        self.assertEqual(self.client.post(self.url,data).status_code,409)
        self.ready.collection_round.refresh_from_db()
        self.assertEqual(self.ready.collection_round.status,'ready')

    def test_scope_csrf_stale_or_foreign_stamps(self):
        data=self.data()
        self.assertEqual(self.client.post(self.url,{**data,'collection_name':'Different collection'}).status_code,409)
        c=Client();self.assertEqual(c.get(self.url).status_code,302)
        c.force_login(self.f.other);self.assertEqual(c.post(self.url,data).status_code,403)
        c.force_login(self.f.reviewer);self.assertEqual(c.post(self.url,data).status_code,403)
        foreign=reverse('participation-manage',args=[self.f.foreign.pk,self.ready.pk])
        self.assertEqual(self.client.post(foreign,data).status_code,404)
        c=Client(enforce_csrf_checks=True);c.force_login(self.f.actor)
        self.assertEqual(c.post(self.url,data).status_code,403)
        for token in [data['stamp']+'bad',collection_control.stamp(self.f.other,self.ready),collection_control.stamp(self.f.actor,self.f.binding)]:
            self.assertEqual(self.client.post(self.url,{**data,'stamp':token}).status_code,409)
        with patch('django.core.signing.time.time',return_value=timezone.now().timestamp()-901):
            expired=collection_control.stamp(self.f.actor,self.ready)
        self.assertEqual(self.client.post(self.url,{**data,'stamp':expired}).status_code,409)
        with override_settings(NEXORA_UNLINKED_ACCESS_ENABLED=False):
            self.assertEqual(self.client.post(self.url,data).status_code,404)

    @override_settings(NEXORA_CONFIRM_IMPORTANT_ACTIONS=True)
    def test_close_blocks_active_answers_preserves_proof_and_no_reopen(self):
        codes=admission.mint(self.f.actor,self.f.binding.pk,2)
        secret=admission.exchange(codes[0]);proof=services.prepare(secret)
        services.submit(secret,self.f.payload,0,proof['issuance_ticket'])
        active=admission.exchange(codes[1])
        before=(AnonymousResponse.objects.count(),ParticipationReceipt.objects.count())
        data=self.data(self.open_url,'close_collection');data['reason']='Testing collection closure'
        page=self.client.post(self.open_url,data)
        self.assertEqual(page.status_code,200)
        self.assertTrue(admission.read_session(active))
        data.update(operation_ticket=str(page.context['ticket']),operation_ack='yes')
        self.assertEqual(self.client.post(self.open_url,data).status_code,302)
        with self.assertRaises(SurveyConflict):admission.read_session(active)
        with self.assertRaises(SurveyConflict):admission.exchange(codes[1])
        self.assertEqual(services.holder_status(proof['receipt_token'])['status'],'issued')
        self.assertEqual((AnonymousResponse.objects.count(),ParticipationReceipt.objects.count()),before)
        self.assertEqual(self.client.post(self.open_url,data).status_code,409)
        with override_settings(NEXORA_CONFIRM_IMPORTANT_ACTIONS=False):
            self.assertEqual(self.client.post(self.open_url,self.data(self.open_url)).status_code,409)

    def test_closing_requires_reason_and_stale_open_stamp_is_rejected(self):
        data=self.data(self.open_url,'close_collection')
        self.assertEqual(self.client.post(self.open_url,data).status_code,422)
        data['reason']='Completed trial'
        self.assertEqual(self.client.post(self.open_url,data).status_code,302)
        self.assertEqual(self.client.post(self.open_url,data).status_code,409)
