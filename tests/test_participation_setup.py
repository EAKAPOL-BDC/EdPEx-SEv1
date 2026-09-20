from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.participation.models import ReceiptPolicy, AccessPass, AccessPool
from apps.rounds.models import CollectionRound, PopulationMember
from tests.test_unlinked_access import fixture


@override_settings(NEXORA_PARTICIPATION_ENABLED=True,NEXORA_UNLINKED_ACCESS_ENABLED=True,NEXORA_CONFIRM_IMPORTANT_ACTIONS=False)
class SetupTests(TestCase):
    @classmethod
    def setUpTestData(cls):cls.f=fixture()

    def setUp(self):
        self.client.force_login(self.f.actor)
        self.url=reverse('participation-setup',args=[self.f.scope.pk,self.f.binding.pk])

    def data(self):
        stamp=self.client.get(self.url).context['form'].initial['setup_stamp']
        now=timezone.now()
        return dict(code='New synthetic collection',context_th='บริบทจำลอง',context_en='Synthetic context',
            open_at=now.isoformat(),due_at=(now+timedelta(days=1)).isoformat(),close_at=(now+timedelta(days=2)).isoformat(),
            expires_at=(now+timedelta(days=3)).isoformat(),count=8,source_title='Synthetic aggregate',source_reference='Eight test slots',
            privacy_notice='Synthetic use only; do not include names.',label_th='กิจกรรมทดสอบ',label_en='Test activity',
            workload='on',confirm='on',setup_stamp=stamp)

    def test_atomic_ready_collection_no_people_or_codes_and_replay(self):
        data=self.data();response=self.client.post(self.url,data)
        self.assertEqual(response.status_code,302)
        r=CollectionRound.objects.get(code=data['code'])
        self.assertEqual((r.status,r.data_kind,r.owner_id),('ready','synthetic',self.f.actor.pk))
        policy=ReceiptPolicy.objects.get(binding__collection_round=r)
        self.assertEqual(policy.realm,'test');self.assertTrue(policy.workload);self.assertFalse(policy.prize)
        self.assertEqual(policy.binding.translation_bundle_id,self.f.binding.translation_bundle_id)
        self.assertEqual(r.period_id,self.f.binding.collection_round.period_id)
        self.assertEqual(AccessPool.objects.get(binding=policy.binding).capacity,8)
        self.assertEqual(r.population_snapshot.counts_by_group,{'C1':8})
        self.assertFalse(PopulationMember.objects.filter(snapshot__collection_round=r).exists())
        self.assertFalse(AccessPass.objects.filter(binding=policy.binding).exists())
        data['code']='Attempt to repeat with another name'
        self.assertEqual(self.client.post(self.url,data).status_code,409)
        self.assertFalse(CollectionRound.objects.filter(code=data['code']).exists())
        self.assertEqual(self.client.get(response.url).status_code,200)

    def test_invalid_fields_cannot_leave_partial_collection(self):
        data=self.data();before=CollectionRound.objects.count()
        for changes in [{'count':0},{'expires_at':data['close_at']},{'workload':''},{'confirm':''},{'close_at':data['open_at']}]:
            result=self.client.post(self.url,{**data,**changes})
            self.assertEqual(result.status_code,422)
            self.assertEqual(CollectionRound.objects.count(),before)
        with patch('apps.participation.setup.services.configure_policy',side_effect=ValidationError('bad policy')):
            self.assertEqual(self.client.post(self.url,data).status_code,422)
        self.assertEqual(CollectionRound.objects.count(),before)

    def test_scope_gate_csrf_and_source_permissions(self):
        c=Client();self.assertEqual(c.get(self.url).status_code,302)
        c.force_login(self.f.other);self.assertEqual(c.get(self.url).status_code,403)
        self.assertEqual(self.client.get(reverse('participation-setup',args=[self.f.foreign.pk,self.f.binding.pk])).status_code,404)
        with override_settings(NEXORA_UNLINKED_ACCESS_ENABLED=False):self.assertEqual(self.client.get(self.url).status_code,404)
        c=Client(enforce_csrf_checks=True);c.force_login(self.f.actor)
        self.assertEqual(c.post(self.url,self.data()).status_code,403)
        from tests.m2_fixtures import grant
        grant(self.f.reviewer,self.f.scope,['round.manage','population.manage'],'setup-no-source-manager')
        c.force_login(self.f.reviewer);self.assertEqual(c.get(self.url).status_code,403)

    def test_forged_stamp_and_duplicate_name(self):
        data=self.data();data['setup_stamp']+='tampered'
        self.assertEqual(self.client.post(self.url,data).status_code,409)
        data=self.data();data['code']=self.f.binding.collection_round.code
        self.assertEqual(self.client.post(self.url,data).status_code,422)

    @override_settings(NEXORA_CONFIRM_IMPORTANT_ACTIONS=True)
    def test_existing_confirmation_flow(self):
        data=self.data();review=self.client.post(self.url,data)
        self.assertEqual(review.status_code,200)
        self.assertFalse(CollectionRound.objects.filter(code=data['code']).exists())
        self.assertFalse(any('setup_stamp' in str(label) for label,value in review.context['entries']))
        self.assertEqual([g['number'] for g in review.context['review_groups']],['01','02','03'])
        self.assertContains(review,'data-confirmation-review')
        self.assertContains(review,'data-review-countdown')
        self.assertEqual(dict(review.context['fields'])['context_en'],data['context_en'])
        data.update(operation_ticket=str(review.context['ticket']),operation_ack='yes')
        self.assertEqual(self.client.post(self.url,{**data,'count':99}).status_code,409)
        self.assertFalse(CollectionRound.objects.filter(code=data['code']).exists())
        response=self.client.post(self.url,data);self.assertEqual(response.status_code,302)
        self.assertEqual(self.client.post(self.url,data).status_code,409)
        self.assertEqual(CollectionRound.objects.filter(code=data['code']).count(),1)

    @override_settings(NEXORA_CONFIRM_IMPORTANT_ACTIONS=True)
    def test_expired_review_cannot_create_collection(self):
        from apps.governance.models import Confirmation
        data=self.data();review=self.client.post(self.url,data)
        Confirmation.objects.filter(pk=review.context['ticket']).update(expires_at=timezone.now()-timedelta(seconds=1))
        data.update(operation_ticket=str(review.context['ticket']),operation_ack='yes')
        self.assertEqual(self.client.post(self.url,data).status_code,409)
        self.assertFalse(CollectionRound.objects.filter(code=data['code']).exists())

    def test_localization_and_navigation(self):
        from django.conf import settings
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME]='en'
        response=self.client.get(self.url)
        self.assertContains(response,'Prepare a new assessment collection')
        self.assertEqual(response.context['form'].fields['code'].label,'New test collection name')
        self.assertContains(self.client.get(reverse('participation-manage',args=[self.f.scope.pk,self.f.binding.pk])),self.url)

    @override_settings(NEXORA_CONFIRM_IMPORTANT_ACTIONS=True)
    def test_edit_returns_values_without_creation_even_after_expiry(self):
        from apps.governance.models import Confirmation
        data=self.data();review=self.client.post(self.url,data)
        ticket=review.context['ticket']
        Confirmation.objects.filter(pk=ticket).update(expires_at=timezone.now()-timedelta(seconds=1))
        edit={**data,'operation_ticket':str(ticket),'operation_edit':'yes','operation_ack':'yes'}
        self.assertEqual(self.client.post(self.url,{**edit,'count':99}).status_code,409)
        response=self.client.post(self.url,edit)
        self.assertEqual(response.status_code,200)
        self.assertFalse(CollectionRound.objects.filter(code=data['code']).exists())
        self.assertEqual(response.context['form']['code'].value(),data['code'])
        self.assertEqual(response.context['form']['privacy_notice'].value(),data['privacy_notice'])
        self.assertNotEqual(response.context['form']['setup_stamp'].value(),data['setup_stamp'])
        self.assertEqual(self.client.post(self.url,edit).status_code,409)
        data['setup_stamp']=response.context['form']['setup_stamp'].value()
        fresh=self.client.post(self.url,data)
        self.assertNotEqual(fresh.context['ticket'],ticket)
        result=self.client.post(self.url,{**data,'operation_ticket':str(fresh.context['ticket']),'operation_ack':'yes'})
        self.assertEqual(result.status_code,302)
        self.assertEqual(CollectionRound.objects.filter(code=data['code']).count(),1)
