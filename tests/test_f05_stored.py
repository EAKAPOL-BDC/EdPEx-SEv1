from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase,Client
from django.core.exceptions import ValidationError
from django.db import transaction,DatabaseError,connection
from django.utils import timezone
from django.urls import reverse
from tests.m2_fixtures import scenario,grant
from apps.rounds.models import PopulationMember
from apps.rounds.services import transition_round
from apps.calculations import activities
from apps.calculations.models import ActivityRevision
from apps.calculations.review import request_review,review_summary,decide_results
from django.contrib.auth import get_user_model

class StoredActivityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.f=scenario(status='open',staff_count=5)
        grant(cls.f.actor,cls.f.scope,['source.manage','result.submit','result.review','result.approve'],'f05-extra')
        cls.reviewer=get_user_model().objects.create_user('f05-reviewer')
        grant(cls.reviewer,cls.f.scope,['result.review','result.approve','calculation.validate','source.manage'],'f05-reviewer')
    def payload(self):
        now=timezone.now()
        return dict(title='Synthetic activity',starts_at=(now-timedelta(hours=3)).isoformat(),ends_at=(now-timedelta(hours=1)).isoformat(),training_hours='1',visit_hours='1',external_visit=True,categories=['T45'],evidence_reference='Synthetic test reference')
    def entry(self,payload=None):
        member=PopulationMember.objects.get(snapshot=self.f.round.population_snapshot,eligible_unit_key='staff-A')
        return activities.save_entry(self.f.actor,self.f.round_instruments['F05'].pk,member,'ACT','SESSION',payload or self.payload(),'Synthetic test','submitted')
    def test_full_stored_review_and_approval(self):
        record=self.entry()
        with self.assertRaises(ValidationError):activities.review_entry(self.reviewer,record.pk,'accepted','Test',1,False)
        activities.review_entry(self.reviewer,record.pk,'accepted','Synthetic evidence checked',1,True)
        transition_round(self.f.actor,self.f.round,'closed',reason='Test complete')
        receipt=activities.calculate(self.f.actor,self.f.round_instruments['F05'].pk,timezone.now(),'f05-test')
        review=request_review(self.f.actor,run_id=receipt['run_id'],reason='Test aggregate')
        packet=review_summary(self.reviewer,run_id=receipt['run_id'])
        self.assertTrue(all(r['status']=='suppressed' for r in packet['results']))
        decide_results(self.reviewer,run_id=receipt['run_id'],outcome='approved',reason='Checked',reviewed_token=review['review_token'])
        client=Client();client.force_login(self.f.actor)
        for name,args in [('activity-list',[self.f.scope.pk]),('activity-collection',[self.f.scope.pk,self.f.round_instruments['F05'].pk]),('activity-entry',[self.f.scope.pk,self.f.round_instruments['F05'].pk,record.pk]),('operator-run',[self.f.scope.pk,receipt['run_id']]),('insights-detail',[self.f.scope.pk,receipt['run_id']])]:
            response=client.get(reverse(name,args=args))
            self.assertEqual(response.status_code,200)
            if name=='operator-run':
                from tests.test_wayfinding import NavigationHTML
                nav=NavigationHTML(response.content.decode())
                self.assertEqual(nav.breadcrumbs,1)
                self.assertContains(response,'href="'+reverse('activity-collection',args=[self.f.scope.pk,self.f.round_instruments['F05'].pk])+'" rel="up"')
    def test_validation_history_and_stale_review(self):
        invalid=self.payload();invalid['training_hours']='20'
        with self.assertRaises(ValidationError):self.entry(invalid)
        record=self.entry()
        activities.review_entry(self.reviewer,record.pk,'revision_requested','Fix evidence',1)
        with self.assertRaises(ValidationError):activities.review_entry(self.reviewer,record.pk,'accepted','Stale',1,True)
        with self.assertRaises(DatabaseError),transaction.atomic():
            with connection.cursor() as cursor:cursor.execute('UPDATE calculations_activityrevision SET reason=%s WHERE record_id=%s',['mutated',record.pk])
        self.assertEqual(ActivityRevision.objects.filter(record=record).count(),2)
    def test_overlap_needs_explanation(self):
        p=self.payload();record=self.entry(p)
        activities.review_entry(self.reviewer,record.pk,'accepted','Verified',1,True)
        other=activities.save_entry(self.f.actor,self.f.round_instruments['F05'].pk,record.member,'ACT2','SESSION',p,'Overlap test','submitted')
        with self.assertRaises(ValidationError):activities.review_entry(self.reviewer,other.pk,'accepted','Verified',1,True)
        activities.review_entry(self.reviewer,other.pk,'accepted','Verified',1,True,'Synthetic concurrent split participation checked')

    def test_five_verified_participants_show_numeric_results(self):
        for member in PopulationMember.objects.filter(snapshot=self.f.round.population_snapshot,group__code='ST1'):
            record=activities.save_entry(self.f.actor,self.f.round_instruments['F05'].pk,member,'TRAIN','1',self.payload(),'Test','submitted')
            activities.review_entry(self.reviewer,record.pk,'accepted','Verified',1,True)
        transition_round(self.f.actor,self.f.round,'closed',reason='Done')
        receipt=activities.calculate(self.f.actor,self.f.round_instruments['F05'].pk,timezone.now(),'five')
        requested=request_review(self.f.actor,run_id=receipt['run_id'],reason='All five')
        packet=review_summary(self.reviewer,run_id=receipt['run_id'])
        self.assertTrue(all(r['status']=='computed' for r in packet['results']))
        self.assertEqual({r['indicator']:r['value'] for r in packet['results']},{'7.3-44':'1','7.3-49':'100'})
        decide_results(self.reviewer,run_id=receipt['run_id'],outcome='approved',reason='Checked',reviewed_token=requested['review_token'])
        client=Client();client.force_login(self.reviewer)
        response=client.get(reverse('insights-compare',args=[self.f.scope.pk]))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'100')
        self.assertEqual(client.get(reverse('insights-compare',args=[self.f.scope.pk]),{'period':'x'*36}).status_code,200)

from django.test import SimpleTestCase
from types import SimpleNamespace as NS
from apps.calculations.comparisons import compatibility_key

class ComparisonDefinitionTests(SimpleTestCase):
    def test_incompatible_definitions_never_share_a_chart(self):
        binding=NS(instrument_version_id='v1',context='context1')
        run=NS(stored_source=NS(round_instrument=binding),collection_round=NS(period_id='p1'),cutoff=timezone.now())
        row=dict(indicator='7.3-38',dimension='',unit='score_10',method='survey',formula={'key':'happiness'})
        key=compatibility_key(run,row)
        for field,value in [('unit','percent'),('method','self_report'),('dimension','another'),('formula',{'key':'other'})]:
            self.assertNotEqual(key,compatibility_key(run,dict(row,**{field:value})))
        binding.context='different'
        self.assertNotEqual(key,compatibility_key(run,row))
        binding.context='context1';binding.instrument_version_id='v2'
        self.assertNotEqual(key,compatibility_key(run,row))

class ActivityRoundWebTests(StoredActivityTests):
    def test_create_f05_round_uses_only_published_f05(self):
        from apps.rounds.models import CollectionRound
        client=Client();client.force_login(self.f.actor)
        url=reverse('activity-new',args=[self.f.scope.pk])
        self.assertEqual(client.get(url).status_code,200)
        now=timezone.now()
        data=dict(code='F05-new-web',period=self.f.round.period_id,owner=self.f.actor.pk,
            bundle=self.f.round_instruments['F05'].translation_bundle_id,open_at=now.isoformat(),
            due_at=(now+timedelta(hours=2)).isoformat(),close_at=(now+timedelta(hours=3)).isoformat(),privacy_notice='Synthetic F05 notice')
        response=client.post(url,data)
        self.assertEqual(response.status_code,302)
        r=CollectionRound.objects.get(scope=self.f.scope,code='F05-new-web')
        self.assertEqual(r.round_instruments.get().instrument_version.instrument.code,'F05')
        data['code']='invalid-F06';data['bundle']=self.f.round_instruments['F06'].translation_bundle_id
        client.post(url,data)
        self.assertFalse(CollectionRound.objects.filter(scope=self.f.scope,code='invalid-F06').exists())
