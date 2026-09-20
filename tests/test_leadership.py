"""Fiscal F04 register: dated identities, explicit eligibility and stored results."""
from datetime import date, timedelta
from unittest import skipUnless
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import connection, transaction, IntegrityError
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import Organization, AccessScope, ALLOWED_PERMISSIONS
from apps.catalog.seeding import seed_catalog
from apps.catalog.models import InstrumentContent
from apps.catalog.management_services import prepare_translations
from apps.catalog.services import source_texts, edit_translation, approve_translation, translation_review_snapshot, publish_bundle, publish_instrument_version
from apps.leadership.models import Person, Programme, Position, AnnualPlan, AnnualTarget, Eligibility, fiscal_window
from apps.leadership import services as registry
from apps.rounds.models import PopulationMember, CollectionRound
from apps.rounds.services import transition_round
from apps.surveys import services as intake
from apps.surveys.models import AnonymousResponse, SurveyProfile
from apps.surveys.schema import respondent_schema, normalize
from apps.surveys.calculations import calculate
from apps.calculations.review import request_review, decide_results, review_summary
from apps.calculations.models import CalculationRun
from tests.m2_fixtures import grant


@override_settings(SURVEY_ALLOW_TEST_HTTP=True, ALLOWED_HOSTS=['testserver'])
class LeadershipTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor=get_user_model().objects.create_user(username='f04-manager')
        cls.reviewer=get_user_model().objects.create_user(username='f04-reviewer')
        cls.outsider=get_user_model().objects.create_user(username='f04-outsider')
        cls.org=Organization.objects.create(name='Synthetic F04 organization')
        cls.scope=AccessScope.objects.create(organization=cls.org,code='F04',name='Synthetic F04')
        cls.foreign=AccessScope.objects.create(organization=cls.org,code='FOREIGN',name='Other scope')
        grant(cls.actor,cls.scope,sorted(ALLOWED_PERMISSIONS),'f04-manager')
        grant(cls.reviewer,cls.scope,sorted(ALLOWED_PERMISSIONS),'f04-reviewer')
        grant(cls.outsider,cls.foreign,sorted(ALLOWED_PERMISSIONS),'f04-outsider')
        now=timezone.localdate();cls.year=now.year+543+(now.month>=10)
        cls.plan=registry.create_plan(cls.actor,cls.scope,cls.year)
        cls.a=registry.save_record(cls.actor,cls.scope,Person,dict(code='LEADER-A',name_th='ผู้บริหาร ก',name_en='Leader A',user=cls.actor))
        cls.b=registry.save_record(cls.actor,cls.scope,Person,dict(code='LEADER-B',name_th='ผู้บริหาร ข',name_en='Leader B',user=None))
        cls.pos=registry.save_record(cls.actor,cls.scope,Position,dict(code='VD-001',role='VD',title_th='รองคณบดีฝ่ายวิชาการ',title_en='Vice dean for academic affairs',programme=None))
        cls.respondents=[]
        for i in range(6):
            cls.respondents.append(registry.save_record(cls.actor,cls.scope,Person,dict(code=f'RELATED-{i}',name_th=f'บุคลากร {i}',name_en=f'Staff {i}',user=None)))
        v=seed_catalog(cls.scope,cls.actor)['instrument_versions']['F04']
        v.instructions_curated=True;v.save()
        InstrumentContent.objects.create(version=v,content_key='F04.instruction',kind='instruction',audience='respondent',text_th='คำชี้แจงจำลอง')
        prepare_translations(cls.actor,v.pk);bundle=v.translation_bundles.first()
        for key,text in source_texts(v).items():
            for locale in ('th','en'):
                e=bundle.translations.get(content_key=key,locale=locale)
                if not e.text:e=edit_translation(cls.actor,e,'Synthetic reviewed wording')
                approve_translation(cls.actor,e,reviewed_token=translation_review_snapshot(cls.actor,e)['reviewed_token'])
        publish_bundle(cls.actor,bundle);bundle.refresh_from_db();publish_instrument_version(cls.actor,v)
        cls.bundle=bundle

    def target(self,**changes):
        start,end=fiscal_window(self.year)
        data=dict(plan=self.plan,person=self.a,position=self.pos,title_th=self.pos.title_th,title_en=self.pos.title_en,
            start_date=start,end_date=end,appointment_kind='substantive',responsibility_th='ภารกิจจำลอง',responsibility_en='Synthetic duties',
            source_reference='Synthetic appointment reference',eligibility_basis='Only the explicitly related staff')
        data.update(changes)
        return registry.save_record(self.actor,self.scope,AnnualTarget,data)

    def eligible(self,t,people=None,group='ST1'):
        for p in people or self.respondents[:5]:
            registry.save_record(self.actor,self.scope,Eligibility,dict(target=t,person=p,group_code=group,relationship='Works on this academic portfolio'))

    def ready(self,t):
        return registry.freeze_target(self.actor,self.scope,t.pk,'Checked real appointment, dates, responsibilities and explicit related people')

    def generate(self,t):
        now=timezone.now()
        bindings = registry.generate_collections(self.actor,self.scope,[str(t.pk)],dict(bundle=self.bundle,owner=self.actor,
            open_at=now-timedelta(hours=1),due_at=now+timedelta(days=1),close_at=now+timedelta(days=2),privacy_notice='Synthetic scoped notice'))
        for binding in bindings:
            self.assertEqual(binding.collection_round.status, 'ready')
            self.assertIsNotNone(binding.collection_round.population_snapshot_id)
        return bindings

    def open(self,b):
        b.collection_round=transition_round(self.actor,b.collection_round,'open')
        return b

    def answer(self,b,n=0,none=False):
        member=b.collection_round.population_snapshot.members.order_by('eligible_unit_key')[n]
        secret=intake.exchange(intake.issue(self.actor,b.pk,member.pk))
        payload={'F04-P03':{'status':'answered','value':'none' if none else 'sufficient'}}
        payload.update({f'F04-VD{i:02}':{'status':'answered','value':4} for i in range(1,6)})
        return intake.save(secret,payload,0,submit=True)

    def test_fiscal_year_dates_and_idempotent_creation(self):
        self.assertEqual((self.plan.period.start_date,self.plan.period.end_date),fiscal_window(self.year))
        self.assertEqual(registry.create_plan(self.actor,self.scope,self.year).pk,self.plan.pk)
        bad=AnnualPlan(scope=self.scope,fiscal_year=self.year+1,period=self.plan.period)
        with self.assertRaises(ValidationError):bad.save()

    def test_overlapping_position_and_invalid_year_rejected(self):
        self.target()
        with self.assertRaises(ValidationError):self.target(person=self.b)
        with self.assertRaises(ValidationError):self.target(start_date=fiscal_window(self.year)[0]-timedelta(days=1))

    def test_two_people_separate_segments_and_multiple_positions(self):
        split=date(self.year-543,4,1)
        first=self.target(end_date=split);second=self.target(person=self.b,start_date=split)
        self.assertNotEqual(first.pk,second.pk)
        pos=registry.save_record(self.actor,self.scope,Position,dict(code='VD-002',role='VD',title_th='รองคณบดีวิจัย',title_en='Research vice dean',programme=None))
        self.target(position=pos)
        self.assertEqual(self.plan.targets.count(),3)

    def test_same_person_two_programmes_distinct_targets(self):
        for i in [1,2]:
            prog=registry.save_record(self.actor,self.scope,Programme,dict(code=f'P{i}',name_th=f'หลักสูตร {i}',name_en=f'Programme {i}'))
            pos=registry.save_record(self.actor,self.scope,Position,dict(code=f'PC-{i}',role='PC',programme=prog,title_th='ประธานหลักสูตร',title_en='Programme chair'))
            self.target(position=pos)
        self.assertEqual(self.plan.targets.values('person_id').distinct().count(),1)
        self.assertEqual(self.plan.targets.count(),2)
        with self.assertRaises(ValidationError):registry.save_record(self.actor,self.scope,Position,dict(code='PC-BAD',role='PC',programme=None,title_th='ประธาน',title_en='Chair'))

    def test_cross_scope_write_and_unauthorized_access(self):
        with self.assertRaises(PermissionDenied):registry.create_plan(self.outsider,self.scope,self.year)
        foreign=registry.save_record(self.outsider,self.foreign,Person,dict(code='FOREIGN',name_th='บุคคลอื่น',name_en='Other',user=None))
        with self.assertRaises(ValidationError):self.target(person=foreign)
        client=Client();client.force_login(self.outsider)
        self.assertEqual(client.get(reverse('f04-register',args=[self.scope.pk])).status_code,403)

    def test_explicit_roster_required_and_frozen(self):
        t=self.target()
        with self.assertRaises(ValidationError):self.ready(t)
        self.eligible(t,people=[self.respondents[0]])
        t=self.ready(t)
        with self.assertRaises(ValidationError):self.eligible(t,people=[self.respondents[1]])
        e=t.eligibility.first()
        with self.assertRaises(ValidationError):registry.remove_eligibility(self.actor,self.scope,e.pk,'Not allowed')
        with self.assertRaises(ValidationError):registry.save_record(self.actor,self.scope,AnnualTarget,{'title_th':'เปลี่ยนชื่อ'},pk=t.pk,reason='Frozen')

    def test_generate_uses_only_related_people_and_reuses_collections(self):
        t=self.target();self.eligible(t,people=self.respondents[:2]);self.eligible(t,people=[self.respondents[2]],group='ST2');t=self.ready(t)
        rows=self.generate(t);again=self.generate(t)
        self.assertEqual({b.pk for b in rows},{b.pk for b in again})
        self.assertEqual(len(rows),2)
        keys=set(PopulationMember.objects.filter(snapshot__collection_round__round_instruments__in=rows).values_list('eligible_unit_key',flat=True))
        self.assertEqual(keys,{'RELATED-0','RELATED-1','RELATED-2'})
        self.assertEqual(AnonymousResponse.objects.count(),0)

    def test_snapshot_survives_master_name_change(self):
        t=self.target();self.eligible(t);t=self.ready(t)
        old=t.snapshot.copy()
        registry.save_record(self.actor,self.scope,Person,{'name_th':'ชื่อใหม่'},pk=self.a.pk,reason='Name changed')
        t.refresh_from_db();self.assertEqual(t.snapshot,old)
        b=self.generate(t)[0]
        self.assertIn('ผู้บริหาร ก',respondent_schema(b.survey_profile,{},'th')['context'])

    def test_invitation_rejects_unrelated_and_target_tampering(self):
        t=self.target();self.eligible(t);t=self.ready(t);b=self.open(self.generate(t)[0])
        with self.assertRaises(PopulationMember.DoesNotExist):intake.issue(self.actor,b.pk,self.respondents[5].pk)
        with self.assertRaises(ValidationError):normalize(b.survey_profile,{'F04-P02':{'status':'answered','value':'another-target'}})
        receipt,state=self.answer(b,none=True)
        self.assertEqual(state,'unable_to_assess')
        response=AnonymousResponse.objects.get(pk=receipt)
        self.assertEqual(response.answers['F04-VD01']['status'],'not_shown')

    def test_split_keeps_answers_and_requires_review_of_both_new_rosters(self):
        t=self.target();self.eligible(t);t=self.ready(t);before=t.snapshot.copy();b=self.open(self.generate(t)[0]);receipt,_=self.answer(b)
        segments=registry.split_target(self.actor,self.scope,t.pk,date(self.year-543,4,1),self.b,'รองคณบดีชื่อใหม่','New vice dean','New appointment order')
        t.refresh_from_db();b.collection_round.refresh_from_db()
        self.assertEqual(t.status,'superseded');self.assertEqual(t.snapshot,before)
        self.assertEqual(b.collection_round.status,'closed');self.assertTrue(AnonymousResponse.objects.filter(pk=receipt,binding=b).exists())
        self.assertEqual([s.status for s in segments],['draft','draft'])
        self.assertEqual(segments[0].end_date,segments[1].start_date)
        with self.assertRaises(ValidationError):intake.issue(self.actor,b.pk,b.collection_round.population_snapshot.members.first().pk)
        self.assertEqual(SurveyProfile.objects.filter(annual_target__in=segments).count(),0)

    def test_copy_next_year_is_draft_only(self):
        t=self.target();self.eligible(t);self.ready(t);next_plan=registry.create_plan(self.actor,self.scope,self.year+1)
        registry.copy_previous(self.actor,self.scope,next_plan.pk,self.plan.pk)
        copy=next_plan.targets.get();self.assertEqual(copy.status,'draft');self.assertFalse(copy.snapshot)
        self.assertEqual(copy.eligibility.count(),5);self.assertFalse(copy.survey_profiles.exists())

    def test_end_to_end_results_include_target_and_exclude_respondent_identity(self):
        t=self.target();self.eligible(t);t=self.ready(t);b=self.open(self.generate(t)[0])
        for i in range(5):self.answer(b,i)
        transition_round(self.actor,b.collection_round,'closed',reason='Complete')
        receipt=calculate(self.actor,b.pk,timezone.now(),'f04-result')
        run=CalculationRun.objects.get(pk=receipt['run_id'])
        import json
        self.assertNotIn('RELATED-',json.dumps(run.manifest))
        request=request_review(self.actor,run_id=run.pk,reason='Review aggregate')
        packet=review_summary(self.reviewer,run_id=run.pk)
        self.assertEqual(packet['results'][0]['leadership']['person_th'],'ผู้บริหาร ก')
        self.assertEqual(str(packet['results'][0]['value']),'4')
        review_client=Client();review_client.force_login(self.reviewer)
        response=review_client.get(reverse('operator-run',args=[self.scope.pk,run.pk]))
        self.assertContains(response,'ผู้บริหาร ก')
        # A distinct evaluatee account must not see approval controls either.
        from unittest.mock import patch
        review_client.force_login(self.actor)
        with patch('apps.calculations.admin_review.can_self_review',return_value=True):
            response=review_client.get(reverse('operator-run',args=[self.scope.pk,run.pk]))
        self.assertFalse(response.context['can_decide'])
        with self.assertRaises(ValidationError):decide_results(self.actor,run_id=run.pk,outcome='approved',reason='Own target',reviewed_token=request['review_token'])
        decide_results(self.reviewer,run_id=run.pk,outcome='approved',reason='Independent review',reviewed_token=request['review_token'])
        client=Client();client.force_login(self.reviewer)
        detail=client.get(reverse('insights-detail',args=[self.scope.pk,run.pk]));self.assertContains(detail,'ผู้บริหาร ก')
        exported=client.get(reverse('insights-export',args=[self.scope.pk,run.pk])).content.decode('utf-8-sig')
        self.assertIn('evaluatee_name',exported);self.assertIn('ผู้บริหาร ก',exported);self.assertNotIn('RELATED-',exported)
        import os
        if os.getenv('F04_PG_FIXTURE'):
            from django.apps import apps
            from django.core.serializers.json import DjangoJSONEncoder
            from django.db.models import JSONField
            from pathlib import Path
            payload=[]
            for model in apps.get_models():
                fields=[f.attname for f in model._meta.local_concrete_fields]
                rows=list(model.objects.values(*fields))
                if rows:payload.append({'table':model._meta.db_table,'json_fields':[f.attname for f in model._meta.local_concrete_fields if isinstance(f,JSONField)],'rows':rows})
            Path(os.environ['F04_PG_FIXTURE']).write_text(json.dumps(payload,cls=DjangoJSONEncoder,ensure_ascii=False))


    def test_http_forms_and_no_cross_year_target_edit(self):
        t=self.target();client=Client();client.force_login(self.actor)
        urls=[reverse('f04-register',args=[self.scope.pk]),reverse('f04-plan',args=[self.scope.pk,self.plan.pk]),reverse('f04-target',args=[self.scope.pk,t.pk]),
            reverse('f04-target-edit',args=[self.scope.pk,self.plan.pk,t.pk]),reverse('f04-generate',args=[self.scope.pk,self.plan.pk]),
            *[reverse('f04-master',args=[self.scope.pk,k]) for k in ['people','positions','programmes']]]
        for i,url in enumerate(urls):
            response=client.get(url)
            self.assertEqual(response.status_code,200,url)
            if i == 3:
                self.assertContains(response, 'type="date" name="start_date" value="2025-10-01"')
                self.assertContains(response, 'type="date" name="last_date" value="2026-09-30"')
            import os
            if os.getenv('F04_HTML_PREVIEW'):
                from pathlib import Path
                folder=Path(os.environ['F04_HTML_PREVIEW']);folder.mkdir(parents=True,exist_ok=True)
                (folder/f'f04-{i}.html').write_bytes(response.content)

        other=registry.create_plan(self.actor,self.scope,self.year+1)
        self.assertEqual(client.get(reverse('f04-target-edit',args=[self.scope.pk,other.pk,t.pk])).status_code,404)

    @skipUnless(connection.vendor=='postgresql','PostgreSQL trigger test requires PostgreSQL')
    def test_database_rejects_frozen_target_and_roster_updates(self):
        t=self.target();self.eligible(t);t=self.ready(t)
        for sql,args in [('UPDATE leadership_annualtarget SET title_th=%s WHERE id=%s',['tampered',t.pk]),
                         ('DELETE FROM leadership_eligibility WHERE target_id=%s',[t.pk])]:
            with self.assertRaises(IntegrityError),transaction.atomic():
                with connection.cursor() as cur:cur.execute(sql,args)
