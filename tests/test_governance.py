"""Synthetic end-to-end policy, account and anonymous staff regression tests."""
import json,re
from datetime import date,timedelta
from unittest.mock import patch
from django.test import TestCase,Client,override_settings
from django.core.exceptions import ValidationError,PermissionDenied
from django.core import mail
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.urls import reverse
from apps.accounts.models import Organization,AccessScope,ALLOWED_PERMISSIONS,Role
from tests.m2_fixtures import grant
from apps.catalog.seeding import seed_catalog
from apps.catalog.models import InstrumentContent
from apps.catalog.management_services import prepare_translations
from apps.catalog.services import (source_texts,edit_translation,approve_translation,translation_review_snapshot,publish_bundle,publish_instrument_version)
from apps.rounds.web_services import create_period,save_population,save_member
from apps.rounds.models import RespondentGroup,PopulationMember
from apps.rounds.services import freeze_population,transition_round
from apps.governance.models import RegistrationPolicy,AccessRequest,AccessCode,Confirmation
from apps.governance import access,f05_contract
from apps.governance.policies import validate_period
from apps.surveys.operator import save_round
from apps.surveys.models import AnonymousSession,AnonymousResponse
from apps.surveys import services
from apps.surveys.schema import normalize,respondent_schema
from apps.surveys.calculations import calculate
from apps.calculations.services import validate_run
from apps.calculations.models import CalculationRun
from apps.calculations.review import request_review,review_summary


def publish(actor,v):
    if not v.instructions_curated:
        v.instructions_curated=True;v.save()
        InstrumentContent.objects.create(version=v,content_key=v.instrument.code+'.privacy_test',kind='instruction',audience='respondent',text_th='Synthetic privacy and instructions')
        prepare_translations(actor,v.pk)
    bundle=v.translation_bundles.first()
    for key,text in source_texts(v).items():
        for locale in ['th','en']:
            e=bundle.translations.get(content_key=key,locale=locale)
            if not e.text:e=edit_translation(actor,e,'Synthetic reviewed English')
            approve_translation(actor,e,reviewed_token=translation_review_snapshot(actor,e)['reviewed_token'])
    publish_bundle(actor,bundle);bundle.refresh_from_db();publish_instrument_version(actor,v)
    return bundle


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',NEXORA_PUBLIC_ORIGIN='https://nexora.example',SURVEY_ALLOW_TEST_HTTP=True)
class GovernanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor=get_user_model().objects.create_user(username='admin-synthetic')
        cls.org=Organization.objects.create(name='Synthetic organization')
        cls.scope=AccessScope.objects.create(organization=cls.org,code='NEW',name='Synthetic scope')
        cls.foreign=AccessScope.objects.create(organization=cls.org,code='OTHER',name='Other scope')
        grant(cls.actor,cls.scope,sorted(ALLOWED_PERMISSIONS),'all-synthetic')
        cls.role=Role.objects.create(code='reader-synthetic',permissions=['catalog.read'])
        cls.policy=RegistrationPolicy.objects.create(scope=cls.scope,enabled=True,privacy_notice='Synthetic notice',privacy_version='test-1',contact='privacy@example.test')
        cls.now=timezone.now();fy=cls.now.year+543+(cls.now.month>=10)
        cls.period=create_period(cls.actor,cls.scope,dict(code='FY',calendar_type='fiscal',reporting_year_be=fy,start_date=date(fy-544,10,1),last_date=date(fy-543,9,30),reason='Synthetic fiscal year'))
        cls.academic=create_period(cls.actor,cls.scope,dict(code='AY',calendar_type='academic',reporting_year_be=fy,start_date=date(fy-543,6,1),last_date=date(fy-542,5,31),reason='Synthetic academic year'))
        versions=seed_catalog(cls.scope,cls.actor)['instrument_versions']
        v5=f05_contract.prepare(cls.actor,cls.scope)
        cls.bundles={'F05':publish(cls.actor,v5),'F06':publish(cls.actor,versions['F06'])}

    def data(self,email='new@example.test'):
        return dict(email=email,full_name='Synthetic person',affiliation='Synthetic affiliation',purpose='Synthetic request',privacy_ack=True)

    def request(self,email='new@example.test'):
        with self.captureOnCommitCallbacks(execute=True):item=access.request_access(self.scope,self.data(email))
        raw=re.search(r'#code=([^\s]+)',mail.outbox[-1].body).group(1)
        return item,raw

    def approve(self,item):
        with self.captureOnCommitCallbacks(execute=True):
            item=access.decide(self.actor,self.scope,item.pk,outcome='approved',reason='Synthetic approval',role=self.role,mode='temporary')
        raw=re.search(r'เปิดบัญชี: ([^\s]+)',mail.outbox[-1].body).group(1)
        return item,raw

    def round(self,code,group_code="ST1"):
        now=timezone.now();selected=save_round(self.actor,self.scope,dict(code='Anonymous '+code+' '+group_code,bundle=self.bundles[code],period=self.period,owner=self.actor,open_at=now-timedelta(hours=1),due_at=now+timedelta(days=1),close_at=now+timedelta(days=2),privacy_notice='Synthetic notice',group_code=group_code,counting_unit='person',context_th='บุคลากรทั้งหน่วยงาน',context_en='All staff',assessor_role='',study_options=[]))
        r=selected.collection_round
        snapshot=save_population(self.actor,r,dict(definition='Synthetic population',count=5,captured_at=now,source_title='Roster',source_location='Synthetic'))
        group=RespondentGroup.objects.get(scope=self.scope,code=group_code)
        for i in range(5):save_member(self.actor,r,dict(eligible_unit_key=f'PRIVATE-{code}-{group_code}-{i}',group=group))
        freeze_population(self.actor,snapshot);transition_round(self.actor,r,'ready')
        selected.collection_round=transition_round(self.actor,r,'open')
        return selected

    def test_year_basis_all_six_and_exclusive_window(self):
        validate_period('F01',self.academic)
        with self.assertRaises(ValidationError):validate_period('F01',self.period)
        for code in ['F02','F03','F04','F05','F06']:
            validate_period(code,self.period)
            with self.assertRaises(ValidationError):validate_period(code,self.academic)
        r=self.round('F06').collection_round
        self.assertTrue(r.accepting_at(r.open_at))
        self.assertFalse(r.accepting_at(r.close_at))

    def test_verified_approval_activation_one_use_and_no_plaintext_storage(self):
        item,verify=self.request()
        with self.assertRaises(ValidationError):self.approve(item)
        access.verify(verify)
        with self.assertRaises(ValidationError):access.verify(verify)
        item,token=self.approve(item)
        self.assertFalse(item.account.is_active);self.assertFalse(item.account.has_usable_password())
        self.assertFalse(AccessCode.objects.filter(digest=token).exists())
        with self.assertRaises(ValidationError):access.activate(token,'short')
        with self.captureOnCommitCallbacks(execute=True):user=access.activate(token,'a long synthetic phrase for testing 809!')
        self.assertTrue(user.is_active);self.assertTrue(user.check_password('a long synthetic phrase for testing 809!'))
        with self.assertRaises(ValidationError):access.activate(token,'another long synthetic phrase')
        self.assertNotIn(token,json.dumps(list(AccessRequest.objects.values()),default=str))

    def test_wrong_scope_expired_token_revoked_and_mail_failure(self):
        item,verify=self.request();access.verify(verify)
        with self.assertRaises(PermissionDenied):access.decide(self.actor,self.foreign,item.pk,outcome='approved',reason='bad',role=self.role)
        item,token=self.approve(item)
        access.withdraw(self.actor,self.scope,item.pk,'Wrong address')
        with self.assertRaises(ValidationError):access.activate(token,'another long synthetic phrase')
        second,verify=self.request('second@example.test')
        AccessCode.objects.filter(request=second).update(expires_at=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(ValidationError):access.verify(verify)
        with patch('apps.governance.access.send_mail',side_effect=RuntimeError('SMTP offline')):
            with self.captureOnCommitCallbacks(execute=True):third=access.request_access(self.scope,self.data('third@example.test'))
        third.refresh_from_db();self.assertEqual(third.delivery_status,'failed')

    def test_anonymous_staff_full_collection_calculation_and_history_replay(self):
        for code in ['F05','F06']:
            selected=self.round(code);profile=selected.survey_profile
            schema=respondent_schema(profile,{},'th')
            self.assertFalse(any(q['id'].startswith('F06-P') for q in schema['questions']))
            payload={}
            for q in schema['questions']:
                if q['type']=='integer_scale':payload[q['id']]={'status':'answered','value':4}
                elif q['type']=='decimal':payload[q['id']]={'status':'answered','value':'12.50'}
                elif q['type']=='single_choice':
                    opt=next(o for o in q['options'] if o['status']=='answered');payload[q['id']]={'status':'answered','value':opt['value']}
            for member in selected.collection_round.population_snapshot.members.all():
                secret=services.exchange(services.issue(self.actor,selected.pk,member.pk))
                services.save(secret,payload,0)
                self.assertEqual(AnonymousSession.objects.get(secret_hash=services.token_hash(secret)).draft,{})
                services.save(secret,payload,0,submit=True)
            transition_round(self.actor,selected.collection_round,'closed',reason='Synthetic finished')
            receipt=calculate(self.actor,selected.pk,timezone.now(),code+'-run')
            run=CalculationRun.objects.get(pk=receipt['run_id'])
            self.assertEqual(validate_run(self.actor,run_id=run.pk)['status'],'verified')
            self.assertNotIn('PRIVATE-',json.dumps(list(run.inputs.values('payload')),default=str))
            request_review(self.actor,run_id=run.pk,reason='Synthetic aggregate review')
            self.assertTrue(review_summary(self.actor,run_id=run.pk)['results'])
            if code=='F05':
                res=run.results.get(indicator_code='7.3-44').payload
                self.assertEqual(res['value'],'12.50');self.assertEqual(res['counts']['valid_n'],5)
            else:
                with self.assertRaises(ValidationError):normalize(profile,{'F06-P01':{'status':'answered','value':'STAFF-ID'}})

    def test_f05_missing_is_not_zero_and_invalid_hours_rejected(self):
        from apps.calculations.services import encode_snapshot_spec
        from apps.calculations.types import FormulaSpec,CalculationInputError
        p={'contract':f05_contract.CONTRACT,'indicator':'7.3-44','eligible_count':5,'spec':encode_snapshot_spec(FormulaSpec('TRAINING_HOURS',('F05-Y01',),f05_contract.VERSION,f05_contract.VERSION)), 'rows':[{'unit_id':'random-a','answers':{'F05-Y01':{'status':'skipped'}}}]}
        r=f05_contract.replay(p);self.assertIsNone(r['value']);self.assertEqual(r['counts']['not_responded'],4)
        p['rows'][0]['answers']['F05-Y01']={'status':'answered','value':'NaN'}
        with self.assertRaises(CalculationInputError):f05_contract.replay(p)

    @override_settings(NEXORA_CONFIRM_IMPORTANT_ACTIONS=True)
    def test_confirmation_does_not_mutate_until_confirm_and_rejects_replay(self):
        client=Client();client.force_login(self.actor)
        url=reverse('access-policy',args=[self.scope.pk]);data=dict(enabled='on',privacy_notice='Changed notice',privacy_version='test-2',contact='privacy@example.test',retention_days='90')
        response=client.post(url,data);self.assertEqual(response.status_code,200)
        self.policy.refresh_from_db();self.assertEqual(self.policy.privacy_version,'test-1')
        ticket=Confirmation.objects.latest('expires_at')
        bad=client.post(url,{**data,'operation_ticket':str(ticket.pk),'operation_ack':'yes','privacy_notice':'tampered'})
        self.assertEqual(bad.status_code,409)
        ok=client.post(url,{**data,'operation_ticket':str(ticket.pk),'operation_ack':'yes'});self.assertEqual(ok.status_code,302)
        self.policy.refresh_from_db();self.assertEqual(self.policy.privacy_version,'test-2')
        again=client.post(url,{**data,'operation_ticket':str(ticket.pk),'operation_ack':'yes'});self.assertEqual(again.status_code,409)
        self.assertEqual(client.post('/api/v1/self-assessment-assignments/',{},content_type='application/json').status_code,409)

    def test_new_pages_render_without_reverse_errors(self):
        c=Client();c.force_login(self.actor)
        for name in ['access-requests','access-policy','access-admin-create','annual-policy','notifications','anonymous-f05-prepare','survey-new']:
            with self.subTest(page=name):self.assertEqual(c.get(reverse(name,args=[self.scope.pk])).status_code,200)
        c.logout()
        for path in ['/login/','/register/','/account/verify/','/account/activate/']:
            with self.subTest(path=path):self.assertEqual(c.get(path).status_code,200)

    def test_support_staff_and_not_applicable_require_reason(self):
        from apps.surveys.forms import ResponseForm
        from apps.catalog.preview import build_preview
        selected=self.round('F06','ST2');p=selected.survey_profile
        schema=respondent_schema(p,{},'th')
        self.assertIn('F06-A09',{q['id'] for q in schema['questions']})
        form=ResponseForm(p,{},0,'th')
        self.assertIn('state:not_applicable',dict(form.fields['F06-M01'].choices))
        with self.assertRaises(ValidationError):normalize(p,{'F06-M01':{'status':'not_applicable'}})
        answers,_=normalize(p,{'F06-M01':{'status':'not_applicable','reason':'No opportunity in this period'}})
        self.assertEqual(answers['F06-M01']['status'],'not_applicable')
        preview,_,_,_=build_preview(selected.instrument_version,'ST2','th')
        self.assertFalse(any(q.startswith('F06-P') for q in preview.fields))

    @override_settings(NEXORA_CONFIRM_IMPORTANT_ACTIONS=True)
    def test_stale_confirmation_and_expired_ticket_are_rejected(self):
        c=Client();c.force_login(self.actor)
        url=reverse('access-policy',args=[self.scope.pk]);data=dict(enabled='on',privacy_notice='Second notice',privacy_version='test-2',contact='privacy@example.test',retention_days='90')
        c.post(url,data);ticket=Confirmation.objects.latest('expires_at')
        RegistrationPolicy.objects.filter(pk=self.scope.pk).update(contact='changed@example.test')
        self.assertEqual(c.post(url,{**data,'operation_ticket':str(ticket.pk),'operation_ack':'yes'}).status_code,409)
        c.post(url,data);ticket=Confirmation.objects.latest('expires_at')
        Confirmation.objects.filter(pk=ticket.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(c.post(url,{**data,'operation_ticket':str(ticket.pk),'operation_ack':'yes'}).status_code,409)

    def test_activation_post_requires_csrf_and_notice_is_frozen(self):
        item,token=self.request()
        self.assertEqual(item.privacy_notice_snapshot,'Synthetic notice')
        RegistrationPolicy.objects.filter(pk=self.scope.pk).update(privacy_notice='Changed later')
        item.refresh_from_db();self.assertEqual(item.privacy_notice_snapshot,'Synthetic notice')
        c=Client(enforce_csrf_checks=True)
        self.assertEqual(c.post('/account/verify/',{'code':token,'confirm':'on'}).status_code,403)
        self.assertFalse(AccessRequest.objects.get(pk=item.pk).verified_at)
