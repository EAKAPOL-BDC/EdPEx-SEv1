"""Production creates fresh real rounds; existing test rounds remain unchanged."""
import copy
import uuid
from types import SimpleNamespace
from django.core import signing
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from apps.participation import collection_mode, public_setup, public_admission, services, batches
from apps.participation.models import ParticipationReceipt
from apps.rounds.models import CollectionRound
from apps.rounds.services import transition_round
from apps.surveys.models import AnonymousResponse
from tests.test_surveys import setup_surveys
from tests.test_public_assessments import setup_data


class CollectionModeTests(SimpleTestCase):
    @override_settings(PRODUCTION=False, NEXORA_PARTICIPATION_ALLOW_LIVE=False)
    def test_preview_stays_synthetic(self):
        self.assertEqual(collection_mode.creation_contract(), ('synthetic', 'test'))

    @override_settings(PRODUCTION=True, NEXORA_PARTICIPATION_ALLOW_LIVE=False)
    def test_live_creation_requires_explicit_enablement(self):
        with self.assertRaises(services.ReceiptError) as caught:
            collection_mode.creation_contract()
        self.assertEqual(caught.exception.code, 'live_issuance_disabled')

    @override_settings(PRODUCTION=True, NEXORA_PARTICIPATION_ALLOW_LIVE=True)
    def test_production_rejects_test_policy_even_when_live_is_enabled(self):
        for kind, realm in [('synthetic', 'test'), ('real', 'test'), ('synthetic', 'live')]:
            policy = SimpleNamespace(realm=realm, binding=SimpleNamespace(collection_round=SimpleNamespace(data_kind=kind)))
            with self.subTest(kind=kind, realm=realm), self.assertRaises(services.ReceiptError) as caught:
                services._policy_valid(policy)
            self.assertEqual(caught.exception.code, 'production_live_only')


@override_settings(NEXORA_PARTICIPATION_ENABLED=True, NEXORA_PUBLIC_ASSESSMENTS_ENABLED=True,
                   SURVEY_ALLOW_TEST_HTTP=True, PRODUCTION=False)
class LiveCollectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fixture = setup_surveys(only={'F01'}, data_kind='synthetic')
        cls.source = cls.fixture.selected['F01']

    def build(self):
        data = setup_data(self.fixture.actor, self.source, 'C1', level='bachelor', programme='primary')
        data['code'] = 'Real collection integration test'
        return public_setup.build_public_collection(self.fixture.actor, self.fixture.scope,
            self.source.collection_round.period, self.source.translation_bundle, data,
            activity='live-test-'+uuid.uuid4().hex)

    @override_settings(PRODUCTION=True, NEXORA_PARTICIPATION_ALLOW_LIVE=False)
    def test_disabled_live_creates_no_round(self):
        before = CollectionRound.objects.count()
        with self.assertRaises(services.ReceiptError):
            self.build()
        self.assertEqual(CollectionRound.objects.count(), before)

    @override_settings(PRODUCTION=True, NEXORA_PARTICIPATION_ALLOW_LIVE=True)
    def test_new_real_round_accepts_answer_and_issues_live_proof(self):
        binding = self.build()
        self.assertEqual(binding.collection_round.data_kind, 'real')
        self.assertEqual(binding.collection_round.status, 'ready')
        self.assertFalse(binding.public_collection.published)
        self.assertEqual(binding.receiptpolicy.realm, 'live')
        self.source.collection_round.refresh_from_db()
        self.assertEqual(self.source.collection_round.data_kind, 'synthetic')
        binding.collection_round = transition_round(self.fixture.actor, binding.collection_round, 'open')
        public_admission.set_published(self.fixture.actor, binding.pk, True)
        context = public_admission.context_for(binding.public_collection, '1')
        secret = public_admission.start(binding.pk, context)
        # A real C1 collection must not redirect to the test-only prototype.
        from apps.surveys.web import COOKIE
        self.client.cookies[COOKIE] = secret
        for locale in ('th', 'en'):
            page = self.client.get(reverse('public-assessment-form') + '?lang=' + locale, secure=True)
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, 'name="F01-C02"')
        candidate = services.prepare(secret)
        payload = copy.deepcopy(self.fixture.answers['F01'])
        payload['F01-C02'] = {'status': 'answered', 'value': ['option_3']}
        result = services.submit(secret, payload, 0, candidate['issuance_ticket'])
        self.assertEqual(result['status'], 'issued')
        self.assertEqual(AnonymousResponse.objects.filter(binding=binding).count(), 1)
        self.assertEqual(ParticipationReceipt.objects.get().policy.realm, 'live')
        self.assertEqual(services.holder_status(candidate['receipt_token'])['realm'], 'live')

    @override_settings(PRODUCTION=True, NEXORA_PARTICIPATION_ALLOW_LIVE=True)
    def test_multigroup_creation_and_render_use_real_kind(self):
        data = setup_data(self.fixture.actor, self.source, 'C1', level='bachelor', programme='primary')
        data.update(bundle=self.source.translation_bundle, period=self.source.collection_round.period,
            group_codes=['C1', 'C2.1'], entries=[
                dict(group_code='C1', level='bachelor', programme='primary', count=120, counting_unit='person', description='Primary'),
                dict(group_code='C2.1', level='master', programme='stem', count=40, counting_unit='person', description='STEM')],
            setup_stamp=signing.dumps({'actor': str(self.fixture.actor.pk), 'scope': str(self.fixture.scope.pk), 'nonce': str(uuid.uuid4())}, salt=batches.SALT))
        batch = batches.create_batch(self.fixture.actor, self.fixture.scope, data)
        self.assertEqual(batch.items.count(), 2)
        for item in batch.items.all():
            self.assertEqual(item.binding.collection_round.data_kind, 'real')
            self.assertEqual(item.binding.receiptpolicy.realm, 'live')
        self.client.force_login(self.fixture.actor)
        response = self.client.get(reverse('assessment-batch-manage', args=[self.fixture.scope.pk, batch.pk]))
        self.assertContains(response, '<span class="batch-tag">REAL</span>', html=True)


@override_settings(NEXORA_PARTICIPATION_ENABLED=True, NEXORA_PUBLIC_ASSESSMENTS_ENABLED=True,
                   SURVEY_ALLOW_TEST_HTTP=True, PRODUCTION=False)
class LiveLeadershipTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fixture = setup_surveys(only={'F04'}, data_kind='synthetic')
        cls.source = cls.fixture.selected['F04']

    @override_settings(PRODUCTION=True, NEXORA_PARTICIPATION_ALLOW_LIVE=True)
    def test_both_staff_groups_launch_with_live_proofs_without_changing_history(self):
        from apps.leadership.public_collections import create_staff_collections, control_plan
        target = self.source.survey_profile.annual_target
        data = setup_data(self.fixture.actor, self.source, 'ST1')
        data.update(group_codes=['ST1', 'ST2'], count_st1=7, count_st2=5, bundle=self.source.translation_bundle)
        rows = create_staff_collections(self.fixture.actor, self.fixture.scope, target.plan_id, data)
        self.assertEqual({b.survey_profile.group_code for b in rows}, {'ST1', 'ST2'})
        self.assertEqual(len(rows), 2)
        control_plan(self.fixture.actor, self.fixture.scope, target.plan_id, 'launch')
        for binding in rows:
            binding.refresh_from_db()
            self.assertEqual(binding.collection_round.data_kind, 'real')
            self.assertEqual(binding.receiptpolicy.realm, 'live')
            secret = public_admission.start(binding.pk, public_admission.context_for(binding.public_collection))
            candidate = services.prepare(secret)
            result = services.submit(secret, {'F04-P03': {'status': 'answered', 'value': 'none'}}, 0, candidate['issuance_ticket'])
            self.assertEqual(result['status'], 'issued')
        self.source.collection_round.refresh_from_db()
        self.assertEqual(self.source.collection_round.data_kind, 'synthetic')
