"""Anonymous collection: state transitions, privacy boundaries and stored-source review."""
import json
from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError,PermissionDenied
from django.db import connection,transaction,IntegrityError
from django.test import TestCase,Client,override_settings
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import Organization,AccessScope,ALLOWED_PERMISSIONS
from apps.auditlog.models import AuditEvent
from apps.catalog.seeding import seed_catalog
from apps.catalog.models import InstrumentContent,ContentTranslation,source_hash
from apps.catalog.services import source_texts,translation_review_snapshot,approve_translation,publish_bundle,publish_instrument_version
from apps.catalog.management_services import prepare_translations
from apps.rounds.models import CollectionRound,PopulationMember,RespondentGroup
from apps.rounds.web_services import create_period,save_population,save_member
from apps.rounds.services import freeze_population,transition_round
from apps.surveys.operator import save_round
from apps.surveys import services
from apps.surveys.models import Invitation,AnonymousSession,AnonymousResponse,SurveyProfile
from apps.surveys.schema import normalize,respondent_schema
from apps.surveys.calculations import calculate
from apps.calculations.models import CalculationRun
from apps.calculations.review import request_review,decide_results,review_summary
from tests.m2_fixtures import grant


def setup_surveys(only=None, *, data_kind='real'):
    from types import SimpleNamespace
    f=SimpleNamespace()
    f.actor=get_user_model().objects.create_user(username='survey-operator')
    f.other=get_user_model().objects.create_user(username='survey-other')
    f.reviewer=get_user_model().objects.create_user(username='survey-reviewer')
    f.org=Organization.objects.create(name='Synthetic survey organization')
    f.scope=AccessScope.objects.create(organization=f.org,code='SURVEY',name='Synthetic survey scope')
    f.foreign=AccessScope.objects.create(organization=f.org,code='OTHER',name='Other scope')
    grant(f.actor,f.scope,sorted(ALLOWED_PERMISSIONS),'survey-operator')
    grant(f.other,f.foreign,sorted(ALLOWED_PERMISSIONS),'survey-other')
    grant(f.reviewer,f.scope,['result.review','result.approve','calculation.validate'],'survey-reviewer')
    now=timezone.now()
    from datetime import date
    fy=now.year+543+(now.month>=10)
    academic=create_period(f.actor,f.scope,{'code':'Synthetic academic','calendar_type':'academic','reporting_year_be':now.year+543,'start_date':now.date().replace(month=1,day=1),'last_date':now.date().replace(month=12,day=31),'reason':'Synthetic institution academic dates'})
    f.period=create_period(f.actor,f.scope,{'code':'Synthetic calendar','calendar_type':'fiscal','reporting_year_be':fy,'start_date':date(fy-544,10,1),'last_date':date(fy-543,9,30),'reason':'Synthetic dates'})
    versions=seed_catalog(f.scope,f.actor)['instrument_versions']
    f.selected={};f.members={};f.answers={}
    for code,group in [('F01','C1'),('F02','C5.3'),('F03','ST1'),('F04','ST1')]:
        if only and code not in only:continue
        print('Synthetic fixture '+code,flush=True)
        v=versions[code]
        v.instructions_curated=True;v.save()
        InstrumentContent.objects.create(version=v,content_key=code+'.instruction',kind='instruction',audience='respondent',text_th='คำชี้แจงจำลองเพื่อทดสอบ')
        prepare_translations(f.actor,v.pk)
        bundle=v.translation_bundles.first()
        for key,text in source_texts(v).items():
            for locale in ('th','en'):
                entry=bundle.translations.get(content_key=key,locale=locale)
                if not entry.text:
                    from apps.catalog.services import edit_translation
                    entry=edit_translation(f.actor,entry,'Synthetic reviewed wording')
                approve_translation(f.actor,entry,reviewed_token=translation_review_snapshot(f.actor,entry)['reviewed_token'])
        publish_bundle(f.actor,bundle);bundle.refresh_from_db();v=publish_instrument_version(f.actor,v)
        data={'code':'Synthetic '+code,'bundle':bundle,'period':academic if code=='F01' else f.period,'owner':f.actor,'open_at':now-timedelta(hours=1),'due_at':now+timedelta(days=1),'close_at':now+timedelta(days=2),'privacy_notice':'Synthetic notice',
            'group_code':group,'counting_unit':'community_representative' if code=='F02' else 'person','context_th':'บริบทจำลอง','context_en':'Synthetic context','assessor_role':'DE' if code=='F04' else '', 'study_options':['option_1','option_2'] if code=='F01' else []}
        if code=='F04':
            from apps.leadership import services as registry
            from apps.leadership.models import Person, Position, AnnualTarget, Eligibility, fiscal_window
            fy=now.year+543+(now.month>=10)
            plan=registry.create_plan(f.actor,f.scope,fy)
            person=registry.save_record(f.actor,f.scope,Person,dict(code='SYN-DE',name_th='คณบดีจำลอง',name_en='Synthetic dean',user=None))
            position=registry.save_record(f.actor,f.scope,Position,dict(code='DE-001',role='DE',title_th='คณบดี',title_en='Dean',programme=None))
            first,last=fiscal_window(fy)
            target=registry.save_record(f.actor,f.scope,AnnualTarget,dict(plan=plan,person=person,position=position,title_th='คณบดี',title_en='Dean',responsibility_th='ภารกิจจำลอง',responsibility_en='Synthetic duty',start_date=first,end_date=last,appointment_kind='substantive',source_reference='Synthetic appointment',eligibility_basis='Synthetic related staff'))
            for n in range(5):
                respondent=registry.save_record(f.actor,f.scope,Person,dict(code=f'PRIVATE-{code}-{n}',name_th=f'ผู้ตอบ {n}',name_en=f'Respondent {n}',user=None))
                registry.save_record(f.actor,f.scope,Eligibility,dict(target=target,person=respondent,group_code=group,relationship='Synthetic related staff'))
            registry.freeze_target(f.actor,f.scope,target.pk,'Synthetic verified appointment and roster')
            selected=registry.generate_collections(f.actor,f.scope,[str(target.pk)],data,data_kind=data_kind)[0]
            r=selected.collection_round
            members=list(PopulationMember.objects.filter(snapshot_id=r.population_snapshot_id).order_by('eligible_unit_key'))
        else:
            selected=save_round(f.actor,f.scope,data,data_kind=data_kind);r=selected.collection_round
            snapshot=save_population(f.actor,r,{'definition':'Synthetic roster','count':5,'captured_at':now,'source_title':'Synthetic roster','source_location':'Synthetic source'})
            group_obj=RespondentGroup.objects.get(scope=f.scope,code=group)
            members=[]
            for n in range(5):members.append(save_member(f.actor,r,{'eligible_unit_key':f'PRIVATE-{code}-{n}','group':group_obj}))
            freeze_population(f.actor,snapshot)
            transition_round(f.actor,r,'ready')
        r=transition_round(f.actor,r,'open');selected.collection_round=r
        f.selected[code]=selected;f.members[code]=members
        payload={}
        for q in v.questions.filter(active=True,audience='respondent'):
            if group not in q.group_codes or q.question_id.split('-')[1].startswith('P'):continue
            if q.answer_type=='integer_scale':payload[q.question_id]={'status':'answered','value':4}
            elif q.answer_type=='single_choice':
                opts=[o.code for o in q.options.all() if o.answer_status=='answered']
                payload[q.question_id]={'status':'answered','value':'U' if 'U' in opts else 'N' if 'N' in opts else opts[0]}
        if code=='F04':payload['F04-P03']={'status':'answered','value':'sufficient'}
        f.answers[code]=payload
    return f


@override_settings(SURVEY_ALLOW_TEST_HTTP=True)
class SurveyFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):cls.f=setup_surveys()

    def secret(self,code='F03',n=0):
        raw=services.issue(self.f.actor,self.f.selected[code].pk,self.f.members[code][n].pk)
        return services.exchange(raw)

    def test_all_four_complete_journeys_calculation_and_independent_review(self):
        for code in self.f.selected:
            with self.subTest(code=code):
                selected=self.f.selected[code]
                for n in range(5):
                    secret=self.secret(code,n)
                    services.save(secret,self.f.answers[code],0,submit=True)
                transition_round(self.f.actor,selected.collection_round,'closed',reason='Synthetic close')
                receipt=calculate(self.f.actor,selected.pk,timezone.now(),'calc-'+code)
                run=CalculationRun.objects.get(pk=receipt['run_id'])
                self.assertGreater(run.result_count,0)
                request=request_review(self.f.actor,run_id=run.pk,reason='Synthetic review')
                packet=review_summary(self.f.reviewer,run_id=run.pk)
                self.assertTrue(packet['results'])
                with self.assertRaises(ValidationError):decide_results(self.f.actor,run_id=run.pk,outcome='approved',reason='Self approval',reviewed_token=request['review_token'])
                self.assertEqual(decide_results(self.f.reviewer,run_id=run.pk,outcome='approved',reason='Checked',reviewed_token=request['review_token'])['status'],'approved')
                self.assertNotIn('PRIVATE-',json.dumps(run.manifest))

    def test_no_identity_or_token_in_response_and_no_score_on_receipt(self):
        secret=self.secret();receipt,_=services.save(secret,self.f.answers['F03'],0,submit=True)
        response=AnonymousResponse.objects.get(pk=receipt)
        self.assertFalse(AnonymousSession.objects.exists())
        self.assertNotIn('PRIVATE-',json.dumps(response.answers))
        self.assertFalse({'member','invitation','token_hash','session','user','ip','contact'} & {f.name for f in AnonymousResponse._meta.fields})
        audit=json.dumps(list(AuditEvent.objects.values()),default=str)
        self.assertNotIn(secret,audit)
        with self.assertRaises(services.SurveyConflict):services.read_session(secret)

    def test_duplicate_submit_reissue_and_revoke(self):
        secret=self.secret();services.save(secret,self.f.answers['F03'],0,submit=True)
        with self.assertRaises(services.SurveyConflict):services.save(secret,{},0,submit=True)
        with self.assertRaises(services.SurveyConflict):services.issue(self.f.actor,self.f.selected['F03'].pk,self.f.members['F03'][0].pk)
        secret2=self.secret(n=1)
        services.issue(self.f.actor,self.f.selected['F03'].pk,self.f.members['F03'][1].pk,revoke=True)
        with self.assertRaises(services.SurveyConflict):services.save(secret2,{},0,submit=True)
        self.assertEqual(AnonymousResponse.objects.count(),1)

    def test_rollback_keeps_invitation_available(self):
        secret=self.secret()
        with patch('apps.surveys.services.AnonymousResponse.objects.create',side_effect=IntegrityError('synthetic failure')):
            with self.assertRaises(IntegrityError):services.save(secret,{},0,submit=True)
        self.assertFalse(Invitation.objects.get().spent)
        self.assertEqual(AnonymousSession.objects.count(),1)
        services.save(secret,{},0,submit=True)

    def test_branch_cleanup_and_f04_no_information(self):
        p=self.f.selected['F02'].survey_profile
        normalized,_=normalize(p,{'F02-D01':{'status':'answered','value':'N'},'F02-D03':{'status':'answered','value':'SHOULD BE CLEARED'}})
        self.assertEqual(normalized['F02-D03'],{'status':'not_shown'})
        secret=self.secret('F04')
        payload={**self.f.answers['F04'],'F04-P03':{'status':'answered','value':'none'}}
        receipt,state=services.save(secret,payload,0,submit=True)
        self.assertEqual(state,'unable_to_assess')
        data=AnonymousResponse.objects.get(pk=receipt).answers
        self.assertEqual(data['F04-DE01'],{'status':'not_shown'})
        self.assertEqual(data['F04-ET01'],{'status':'not_shown'})

    def test_zero_valid_unknown_wrong_and_maximum_three(self):
        p=self.f.selected['F03'].survey_profile
        data,_=normalize(p,{'F03-H01':{'status':'answered','value':0},'F03-G08':{'status':'answered','value':['G01','G02','G03']}})
        self.assertEqual(data['F03-H01']['value'],0)
        for choices in [['G01','G02','G03','G04'],['none','G01'],['G01','G01']]:
            with self.assertRaises(ValidationError):normalize(p,{'F03-G08':{'status':'answered','value':choices}})
        p1=self.f.selected['F01'].survey_profile
        data,_=normalize(p1,{'F01-K01':{'status':'answered','value':'U'}})
        self.assertEqual(data['F01-K01'],{'status':'answered','value':'U'})
        schema=respondent_schema(p1,{},'en')
        def check_keys(value):
            if isinstance(value,dict):
                self.assertFalse({'score','correct_code','correct_option','answer_key','source_metadata'} & value.keys())
                for child in value.values():check_keys(child)
            elif isinstance(value,list):
                for child in value:check_keys(child)
        check_keys(schema)

    def test_forbidden_context_invalid_score_text_and_group(self):
        p=self.f.selected['F03'].survey_profile
        for payload in [{'F03-P01':{'status':'answered','value':'ST2'}},{'F03-H01':{'status':'answered','value':True}}, {'F03-O01':{'status':'answered','value':'x'*501}}, {'user_id':1}]:
            with self.assertRaises(ValidationError):normalize(p,payload)
        p1=self.f.selected['F01'].survey_profile
        with self.assertRaises(ValidationError):normalize(p1,{'F01-P03':{'status':'answered','value':'option_8'}})

    def test_expired_session_stale_draft_and_closed_round(self):
        secret=self.secret();services.save(secret,{},0)
        self.assertEqual(services.save(secret,{},0),0)
        self.assertEqual(AnonymousSession.objects.get().draft,{})
        transition_round(self.f.actor,self.f.selected['F03'].collection_round,'closed',reason='Synthetic')
        with self.assertRaises(services.SurveyConflict):services.save(secret,{},1,submit=True)
        secret=self.secret('F01')
        with patch('apps.surveys.services.timezone.now',return_value=timezone.now()+timedelta(days=4)):
            services.cleanup()
            with self.assertRaises(services.SurveyConflict):services.read_session(secret)

    def test_scope_permissions_and_database_immutability(self):
        with self.assertRaises(PermissionDenied):services.issue(self.f.other,self.f.selected['F03'].pk,self.f.members['F03'][0].pk)
        secret=self.secret();receipt,_=services.save(secret,{},0,submit=True)
        with self.assertRaises(IntegrityError),transaction.atomic():
            AnonymousResponse.objects.filter(pk=receipt).update(answers={})
        with self.assertRaises(IntegrityError),transaction.atomic():
            Invitation.objects.filter(spent=True).update(spent=False)
        with self.assertRaises(IntegrityError),transaction.atomic():
            SurveyProfile.objects.filter(binding=self.f.selected['F03']).update(group_code='ST2')

    def test_http_csrf_session_isolation_bilingual_draft_and_submit(self):
        client=Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/survey/',{'code':'x'*43}).status_code,403)
        client.get('/survey/')
        raw=services.issue(self.f.actor,self.f.selected['F03'].pk,self.f.members['F03'][0].pk)
        csrf=client.cookies['csrftoken'].value
        response=client.post('/survey/',{'code':raw,'csrfmiddlewaretoken':csrf})
        self.assertEqual(response.status_code,302)
        self.assertNotIn(raw,response['Location'])
        cookie=client.cookies['nexora_survey_session']
        self.assertTrue(cookie['httponly']);self.assertEqual(cookie['samesite'],'Strict')
        # Even a staff-authenticated browser uses the separate anonymous session.
        client.force_login(self.f.actor)
        page=client.get('/survey/answer/?lang=en')
        self.assertEqual(page.status_code,200,page.content.decode()[:600])
        self.assertNotIn(self.f.actor.username,page.content.decode())
        self.assertIn('no-store',page['Cache-Control'])
        self.assertNotIn('PRIVATE-',page.content.decode())
        csrf=client.cookies['csrftoken'].value
        response=client.post('/survey/answer/',{'revision':0,'F03-H01':'value:0','action':'draft','csrfmiddlewaretoken':csrf})
        self.assertEqual(response.status_code,200,response.content.decode()[:600])
        response=client.post('/survey/answer/',{'revision':0,'F03-H01':'value:0','action':'submit','confirm':'on','csrfmiddlewaretoken':csrf})
        self.assertEqual(response.status_code,200,response.content.decode()[:600])
        self.assertContains(response,'Response received')
        self.assertNotIn('PRIVATE-',response.content.decode())

    def test_ui_routes_and_throttle(self):
        client=Client();client.force_login(self.f.actor)
        urls=[reverse('survey-list',args=[self.f.scope.pk]),reverse('survey-new',args=[self.f.scope.pk]),reverse('round-detail',args=[self.f.scope.pk,self.f.selected['F03'].collection_round_id]),reverse('survey-collection',args=[self.f.scope.pk,self.f.selected['F03'].pk])]
        for url in urls:self.assertEqual(client.get(url).status_code,200,url)
        client.force_login(self.f.other)
        self.assertEqual(client.get(urls[0]).status_code,403)
        client=Client()
        for _ in range(20):self.assertNotEqual(client.post('/survey/',{'code':'invalid'*6}).status_code,429)
        self.assertEqual(client.post('/survey/',{'code':'invalid'*6}).status_code,429)

    def test_create_round_roster_and_invitation_through_web(self):
        from tests.confirmation_helpers import confirmed_post
        client=Client(enforce_csrf_checks=True);client.force_login(self.f.actor)
        url=reverse('survey-new',args=[self.f.scope.pk]);client.get(url)
        csrf=client.cookies['csrftoken'].value
        now=timezone.localtime()
        data={'csrfmiddlewaretoken':csrf,'code':'Web-created survey','bundle':self.f.selected['F03'].translation_bundle_id,'period':self.f.period.pk,'owner':self.f.actor.pk,
            'open_at':(now-timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'),'due_at':(now+timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),'close_at':(now+timedelta(days=2)).strftime('%Y-%m-%dT%H:%M'),
            'privacy_notice':'Synthetic privacy notice','group_code':'ST1','counting_unit':'person','context_th':'รอบเว็บจำลอง','context_en':'Synthetic web round','context_checked':'on'}
        response=confirmed_post(client,url,data)
        self.assertEqual(response.status_code,302,response.content.decode()[:900])
        r=CollectionRound.objects.get(code=data['code']);selected=r.round_instruments.get()
        url=reverse('round-population',args=[self.f.scope.pk,r.pk])
        response=confirmed_post(client,url,{'csrfmiddlewaretoken':csrf,'definition':'Synthetic eligibility','count':1,'source_title':'Synthetic source','source_location':'Test fixture','captured_at':now.strftime('%Y-%m-%dT%H:%M')})
        self.assertEqual(response.status_code,302,response.content.decode()[:900])
        response=confirmed_post(client,reverse('round-member-new',args=[self.f.scope.pk,r.pk]),{'csrfmiddlewaretoken':csrf,'eligible_unit_key':'WEB-PRIVATE-UNIT','group':RespondentGroup.objects.get(scope=self.f.scope,code='ST1').pk})
        self.assertEqual(response.status_code,302,response.content.decode()[:900])
        for action in ['freeze','ready']:
            response=confirmed_post(client,reverse('round-action',args=[self.f.scope.pk,r.pk,action]),{'csrfmiddlewaretoken':csrf,'reason':'Synthetic check','confirm':'on'})
            self.assertEqual(response.status_code,302,response.content.decode()[:900])
        r.refresh_from_db();member=r.population_snapshot.members.get()
        response=confirmed_post(client,reverse('survey-invite',args=[self.f.scope.pk,selected.pk,member.pk]),{'csrfmiddlewaretoken':csrf,'reason':'Synthetic invitation','confirm':'on','action':'issue'})
        self.assertEqual(response.status_code,200,response.content.decode()[:900])
        self.assertTrue(response.context['code'])
        response=confirmed_post(client,reverse('survey-collection',args=[self.f.scope.pk,selected.pk]),{'csrfmiddlewaretoken':csrf,'reason':'Synthetic open','confirm':'on','action':'open'})
        self.assertEqual(response.status_code,302,response.content.decode()[:900])

    def test_unpaired_spend_fails_at_constraint_check(self):
        self.secret()
        with self.assertRaises(IntegrityError),transaction.atomic():
            Invitation.objects.all().update(spent=True)
            with connection.cursor() as cursor:cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
        self.assertFalse(Invitation.objects.get().spent)

    def test_f02_month_and_f04_role_are_enforced(self):
        p=self.f.selected['F02'].survey_profile
        with self.assertRaises(ValidationError):normalize(p,{'F02-P04':{'status':'answered','value':'month_year','month':'2026-13'}})
        data,_=normalize(p,{'F02-P04':{'status':'answered','value':'month_year','month':'2026-09'}})
        self.assertEqual(data['F02-P04']['month'],'2026-09')
        p4=self.f.selected['F04'].survey_profile
        data,_=normalize(p4,{'F04-P03':{'status':'answered','value':'sufficient'},'F04-VD01':{'status':'answered','value':5}})
        self.assertEqual(data['F04-VD01'],{'status':'not_shown'})
