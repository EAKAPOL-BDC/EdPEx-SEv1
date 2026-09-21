"""Aggregate-only invitation -> committed answer/proof -> reviewed result/report."""
from datetime import timedelta
import json
import uuid
from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from apps.calculations.models import CalculationRun
from apps.calculations.review import request_review, review_summary, decide_results
from apps.participation import admission, services, collection_control
from apps.participation.models import ParticipationReceipt
from apps.participation.setup import create_collection, SALT
from apps.rounds.models import PopulationMember
from apps.surveys.calculations import calculate
from apps.surveys.models import AnonymousResponse
from tests.test_unlinked_access import fixture


@override_settings(NEXORA_PARTICIPATION_ENABLED=True,NEXORA_UNLINKED_ACCESS_ENABLED=True,NEXORA_CONFIRM_IMPORTANT_ACTIONS=False)
class ParticipationResultsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.f=fixture();now=timezone.now()
        data=dict(code='Aggregate reporting journey',context_th='บริบททดสอบ',context_en='Test context',
            open_at=now-timedelta(minutes=5),due_at=now+timedelta(days=1),close_at=now+timedelta(days=2),
            expires_at=now+timedelta(days=30),count=5,source_title='Synthetic total',source_reference='Five test slots',
            privacy_notice='Synthetic use only.',label_th='ทดสอบ',label_en='Test',workload=True,prize=False,
            setup_stamp=signing.dumps({'actor':str(cls.f.actor.pk),'source':str(cls.f.binding.pk),'nonce':str(uuid.uuid4())},salt=SALT))
        cls.binding=create_collection(cls.f.actor,cls.f.binding,data)

    def setUp(self):
        self.client.force_login(self.f.actor)
        self.url=reverse('participation-results',args=[self.f.scope.pk,self.binding.pk])

    def collect(self,count):
        b=self.binding;b.collection_round.refresh_from_db()
        collection_control.change(self.f.actor,b.pk,'open_collection',collection_control.stamp(self.f.actor,b),collection_name=b.collection_round.code)
        receipts=[];secrets=[]
        for code in admission.mint(self.f.actor,b.pk,count):
            secret=admission.exchange(code);candidate=services.prepare(secret)
            answers={**self.f.payload,'F01-O01':{'status':'answered','value':'PRIVATE-TEST-COMMENT-749'}}
            result=services.submit(secret,answers,0,candidate['issuance_ticket'])
            self.assertEqual(result['status'],'issued')
            receipts.append(candidate['receipt_token']);secrets.extend([code,secret,candidate['receipt_token']])
        b.collection_round.refresh_from_db()
        collection_control.change(self.f.actor,b.pk,'close_collection',collection_control.stamp(self.f.actor,b),collection_name=b.collection_round.code,reason='Completed synthetic journey')
        return receipts,secrets

    def test_get_scope_roles_locale_and_no_write(self):
        self.assertFalse(CalculationRun.objects.exists())
        page=self.client.get(self.url)
        self.assertEqual(page.status_code,200)
        self.assertEqual(page.context['participation']['eligible'],5)
        self.assertEqual(page.context['participation']['submitted'],0)
        self.assertFalse(page.context['closed'])
        self.assertFalse(CalculationRun.objects.exists())
        self.assertFalse(AnonymousResponse.objects.filter(binding=self.binding).exists())
        self.assertEqual(self.client.post(self.url,{}).status_code,405)
        self.assertIn('no-store',page['Cache-Control'])
        c=Client();self.assertEqual(c.get(self.url).status_code,302)
        c.force_login(self.f.other);self.assertEqual(c.get(self.url).status_code,403)
        foreign_url=reverse('participation-results',args=[self.f.foreign.pk,self.binding.pk])
        self.assertEqual(self.client.get(foreign_url).status_code,403)
        self.assertEqual(c.get(foreign_url).status_code,404)
        c.force_login(self.f.reviewer);self.assertIsNone(c.get(self.url).context['participation'])
        with override_settings(NEXORA_UNLINKED_ACCESS_ENABLED=False):self.assertEqual(self.client.get(self.url).status_code,404)
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME]='en'
        self.assertContains(self.client.get(self.url),'From responses to reviewed results')

    @override_settings(NEXORA_CONFIRM_IMPORTANT_ACTIONS=True)
    def test_full_journey_calculation_review_approval_and_export(self):
        receipts,secrets=self.collect(5)
        self.assertFalse(PopulationMember.objects.filter(snapshot__collection_round=self.binding.collection_round).exists())
        self.assertEqual(AnonymousResponse.objects.filter(binding=self.binding).count(),5)
        self.assertEqual(ParticipationReceipt.objects.count(),5)
        url=reverse('survey-calculate',args=[self.f.scope.pk,self.binding.pk])
        data={'reason':'Synthetic complete coverage','confirm':'on'}
        review=self.client.post(url,data)
        preview=self.client.post(url,{**data,'operation_ticket':str(review.context['ticket']),'operation_ack':'yes'})
        self.assertEqual(preview.status_code,200)
        self.assertContains(preview,'data-calculation-preview')
        self.assertIsNotNone(preview.context['preview_cutoff'])
        self.assertContains(preview,'name="preview"')
        self.assertContains(preview,'Review and save result set')
        self.assertGreater(preview.context['preview']['result_count'],0)
        self.assertFalse(CalculationRun.objects.exists())
        data['preview']=preview.context['token']
        confirm=self.client.post(url,data)
        final={**data,'operation_ticket':str(confirm.context['ticket']),'operation_ack':'yes'}
        saved=self.client.post(url,final);self.assertEqual(saved.status_code,302)
        self.assertEqual(self.client.post(url,final).status_code,409)
        run=CalculationRun.objects.get()
        self.assertEqual(run.population_snapshot.counts_by_group['C1'],5)
        self.assertEqual(self.client.get(self.url).context['runs'][0]['state'],'complete')
        run_url=reverse('operator-run',args=[self.f.scope.pk,run.pk])
        self.assertContains(self.client.get(run_url),'review-submit')
        report=reverse('insights-detail',args=[self.f.scope.pk,run.pk])
        export=reverse('insights-export',args=[self.f.scope.pk,run.pk])
        self.assertEqual(self.client.get(report).status_code,404)
        submit_data={'action':'submit','reason':'Check synthetic aggregate results'}
        confirm=self.client.post(run_url,submit_data)
        submitted=self.client.post(run_url,{**submit_data,'operation_ticket':str(confirm.context['ticket']),'operation_ack':'yes'})
        self.assertEqual(submitted.status_code,302)
        review_request={'review_token':run.review_request.review_token}
        self.assertContains(self.client.get(run_url),'ต้องให้ผู้ตรวจที่มีสิทธิ์รับรอง')
        self.assertEqual(self.client.get(self.url).context['runs'][0]['state'],'review')
        packet=review_summary(self.f.reviewer,run_id=run.pk)
        self.assertTrue(packet['results'])
        with self.assertRaises(ValidationError):
            decide_results(self.f.actor,run_id=run.pk,outcome='approved',reason='Self review',reviewed_token=review_request['review_token'])
        reviewer=Client();reviewer.force_login(self.f.reviewer)
        self.assertContains(reviewer.get(run_url),'review-decision')
        decision_data={'action':'decide','outcome':'approved','reason':'Independent synthetic review','reviewed_token':review_request['review_token']}
        confirm=reviewer.post(run_url,decision_data)
        approved=reviewer.post(run_url,{**decision_data,'operation_ticket':str(confirm.context['ticket']),'operation_ack':'yes'})
        self.assertEqual(approved.status_code,302)
        page=self.client.get(self.url)
        self.assertEqual(page.context['runs'][0]['state'],'approved')
        self.assertTrue(page.context['runs'][0]['report_available'])
        self.assertEqual(self.client.get(report).status_code,200)
        self.assertContains(self.client.get(run_url),report)
        self.assertContains(self.client.get(run_url),export)
        csv=self.client.get(export);self.assertEqual(csv.status_code,200)
        self.assertIn('attachment',csv['Content-Disposition'])
        visible=page.content.decode()+csv.content.decode()+json.dumps(run.manifest)
        for secret in secrets+['PRIVATE-TEST-COMMENT-749']:
            self.assertNotIn(secret,visible)
        self.assertTrue(all(services.holder_status(token)['status']=='issued' for token in receipts))

    def test_small_group_scores_remain_suppressed_and_returned_has_no_export(self):
        self.collect(1)
        receipt=calculate(self.f.actor,self.binding.pk,timezone.now(),'small-report')
        review_request=request_review(self.f.actor,run_id=receipt['run_id'],reason='Small synthetic sample')
        packet=review_summary(self.f.reviewer,run_id=receipt['run_id'])
        self.assertTrue(packet['results'])
        for row in packet['results']:
            self.assertEqual(row['status'],'suppressed')
            self.assertNotIn('value',row)
            self.assertNotIn('numerator',row)
        decide_results(self.f.reviewer,run_id=receipt['run_id'],outcome='returned',reason='Insufficient sample',reviewed_token=review_request['review_token'])
        page=self.client.get(self.url)
        self.assertEqual(page.context['runs'][0]['state'],'returned')
        self.assertFalse(page.context['runs'][0]['report_available'])
        returned_page=self.client.get(reverse('operator-run',args=[self.f.scope.pk,receipt['run_id']]))
        self.assertContains(returned_page,reverse('survey-calculate',args=[self.f.scope.pk,self.binding.pk]))
        self.assertNotContains(page,'ดาวน์โหลด CSV')
        self.assertEqual(self.client.get(reverse('insights-export',args=[self.f.scope.pk,receipt['run_id']])).status_code,404)

    def test_calculation_readiness_and_invalid_preview_fail_without_writes(self):
        url=reverse('survey-calculate',args=[self.f.scope.pk,self.binding.pk])
        page=self.client.get(url)
        self.assertEqual(page.status_code,200)
        self.assertFalse(page.context['ready'])
        self.assertNotContains(page,'name="reason"')
        data={'reason':'Readiness guard test','confirm':'on'}
        self.assertEqual(self.client.post(url,data).status_code,422)
        self.assertFalse(CalculationRun.objects.exists())
        b=self.binding;b.collection_round.refresh_from_db()
        collection_control.change(self.f.actor,b.pk,'open_collection',collection_control.stamp(self.f.actor,b),collection_name=b.collection_round.code)
        b.collection_round.refresh_from_db()
        collection_control.change(self.f.actor,b.pk,'close_collection',collection_control.stamp(self.f.actor,b),collection_name=b.collection_round.code,reason='Empty test round')
        page=self.client.get(url)
        self.assertFalse(page.context['ready'])
        self.assertEqual(sum(c['passed'] for c in page.context['checks']),2)
        self.assertEqual(self.client.post(url,data).status_code,422)
        self.assertFalse(CalculationRun.objects.exists())

    def test_expired_preview_retains_reason_without_creating_results(self):
        from unittest.mock import patch
        self.collect(1)
        url=reverse('survey-calculate',args=[self.f.scope.pk,self.binding.pk])
        data={'reason':'Keep this explanation','confirm':'on'}
        page=self.client.post(url,data)
        self.assertTrue(page.context['ready'])
        token=page.context['token']
        from django.core.signing import TimestampSigner
        with patch.object(TimestampSigner,'timestamp',return_value=signing.b62_encode(int(__import__('time').time())-1801)):
            expired=signing.dumps(signing.loads(token,salt='survey-calculation'),salt='survey-calculation')
        result=self.client.post(url,{**data,'preview':expired})
        self.assertEqual(result.status_code,422)
        self.assertContains(result,'This preview expired or is invalid',status_code=422)
        self.assertEqual(result.context['form']['reason'].value(),data['reason'])
        self.assertFalse(CalculationRun.objects.exists())
