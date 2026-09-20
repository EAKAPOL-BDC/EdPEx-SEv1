"""Public entry: no roster/invitation, context safety, proof atomicity and CSRF."""
import copy
import json
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction, connection
from django.test import TestCase, SimpleTestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from apps.participation import public_admission as entry, public_setup, services as proofs
from apps.participation.models import PublicCollection, PublicSession, ParticipationReceipt
from apps.participation.public_catalog import public_catalog, validate_context
from apps.rounds.models import PopulationMember
from apps.rounds.services import transition_round
from apps.surveys.models import AnonymousResponse, Invitation
from tests.test_surveys import setup_surveys


class PublicTaxonomyTests(SimpleTestCase):
    def test_exact_approved_groups_and_programmes(self):
        catalog = public_catalog()
        groups = {g['code']: g for category in catalog['categories'] for g in category['groups']}
        self.assertEqual(len(catalog['categories']), 6)
        self.assertEqual(len(groups), 17)
        self.assertFalse({'S2', 'SP1'} & groups.keys())
        self.assertEqual(groups['ST2']['name']['th'], 'บุคลากรสายสนับสนุน')
        self.assertEqual(groups['C2.2']['levels'], ['doctoral'])
        self.assertEqual(len(catalog['programmes']['bachelor']), 11)
        self.assertEqual(catalog['programmes']['master'][-1]['name']['th'], 'กศ.ม. สาขาวิชาสะเต็มศึกษา')
        self.assertEqual(validate_context('C1', 'bachelor', 'primary', '6+')['year'], '6+')
        self.assertEqual(validate_context('C2.2', 'doctoral', 'curriculum', '4+')['year'], '4+')

    def test_reject_wrong_group_level_programme_and_year(self):
        for args in [('S2', '', '', ''), ('ST2', 'bachelor', 'primary', '1'),
                     ('C2.2', 'master', 'stem', '1'), ('C1', 'bachelor', 'stem', '1'),
                     ('C1', 'bachelor', 'primary', '8'), ('C2.1', 'master', 'stem', '4+')]:
            with self.subTest(args=args), self.assertRaises(ValueError): validate_context(*args)

    def test_public_setup_review_uses_group_programme_and_reference_labels(self):
        from apps.governance.review_presentation import presentation
        data = presentation({'group_code':['C2.1'], 'programme_key':['master:stem'], 'count':['120'],
            'counting_unit':['person']}, 'public-assessment-setup', [])
        self.assertTrue(data['review_is_public'])
        fields = [field for group in data['review_groups'] for field in group['items']]
        self.assertTrue(any('สาขาวิชาสะเต็มศึกษา' in (field.get('copy') or '') for field in fields))
        self.assertTrue(any(field['label'] == 'จำนวนอ้างอิงรวม / Aggregate reference population' for field in fields))


def setup_data(actor, source, group, *, level='', programme='', suffix=''):
    now = timezone.now()
    return dict(code='Public synthetic '+source.instrument_version.instrument.code+suffix, context_th='บริบทสมมุติ', context_en='Synthetic context',
        open_at=now-timedelta(minutes=5), due_at=now+timedelta(days=1), close_at=now+timedelta(days=2), count=5,
        source_title='Synthetic aggregate', source_reference='Synthetic total only', privacy_notice='Synthetic bilingual notice',
        label_th='หลักฐานจำลอง', label_en='Synthetic proof', expires_at=now+timedelta(days=30), workload=True, prize=False,
        group_code=group, level=level, programme=programme,
        setup_stamp=signing.dumps({'actor':str(actor.pk),'source':str(source.pk),'nonce':str(uuid.uuid4())},salt=public_setup.SALT))


@override_settings(NEXORA_PARTICIPATION_ENABLED=True, NEXORA_PUBLIC_ASSESSMENTS_ENABLED=True, SURVEY_ALLOW_TEST_HTTP=True)
class PublicAssessmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.f = setup_surveys(only={'F01'}, data_kind='synthetic')
        cls.source = cls.f.selected['F01']
        now = timezone.now()
        cls.data = dict(code='Synthetic public primary', context_th='ประถมศึกษา จำลอง', context_en='Synthetic Primary Education',
            open_at=now-timedelta(minutes=5), due_at=now+timedelta(days=1), close_at=now+timedelta(days=2),
            count=5, source_title='Synthetic aggregate', source_reference='Synthetic total only', privacy_notice='Synthetic notice',
            label_th='หลักฐาน F01 จำลอง', label_en='Synthetic F01 proof', expires_at=now+timedelta(days=30),
            workload=False, prize=True, group_code='C1', level='bachelor', programme='primary',
            setup_stamp=signing.dumps({'actor':str(cls.f.actor.pk),'source':str(cls.source.pk),'nonce':str(uuid.uuid4())},salt=public_setup.SALT))
        cls.binding = public_setup.create_collection(cls.f.actor, cls.source, cls.data)
        cls.binding.collection_round = transition_round(cls.f.actor, cls.binding.collection_round, 'open')
        entry.set_published(cls.f.actor, cls.binding.pk, True)
        cls.context = validate_context('C1', 'bachelor', 'primary', '6+')
        cls.payload = copy.deepcopy(cls.f.answers['F01'])
        cls.payload['F01-C02'] = {'status':'answered','value':['option_3']}

    def prepared(self):
        secret = entry.start(self.binding.pk, self.context)
        return secret, proofs.prepare(secret)

    def test_public_collection_has_no_roster_and_no_invitations(self):
        self.assertFalse(PopulationMember.objects.filter(snapshot__collection_round=self.binding.collection_round).exists())
        self.assertFalse(Invitation.objects.filter(binding=self.binding).exists())
        secret, candidate = self.prepared()
        self.assertEqual(entry.start(self.binding.pk, self.context, secret), secret)
        self.assertEqual(PublicSession.objects.count(), 1)
        result = proofs.submit(secret, self.payload, 0, candidate['issuance_ticket'])
        self.assertEqual(result['status'], 'issued')
        self.assertEqual(AnonymousResponse.objects.get(binding=self.binding).answers['F01-P03'], {'status':'answered','value':'public-year-6+'})
        slot = PublicSession.objects.get()
        self.assertTrue(slot.spent)
        self.assertIsNone(slot.secret_hash); self.assertIsNone(slot.expires_at); self.assertEqual(slot.year, '')
        self.assertEqual(proofs.holder_status(candidate['receipt_token'])['status'], 'issued')
        self.assertFalse({'response','person','user','session'} & {f.name for f in ParticipationReceipt._meta.fields})

    def test_unpublished_closed_and_wrong_context_cannot_start(self):
        changed = dict(self.context, programme='physics')
        with self.assertRaises(proofs.ReceiptError): entry.start(self.binding.pk, changed)
        entry.set_published(self.f.actor, self.binding.pk, False)
        with self.assertRaises(Exception): entry.start(self.binding.pk, self.context)
        self.assertFalse(PublicSession.objects.exists())

    def test_required_answers_do_not_issue_proof_or_spend(self):
        secret, candidate = self.prepared()
        with self.assertRaises(proofs.ReceiptError) as caught:
            proofs.submit(secret, {}, 0, candidate['issuance_ticket'])
        self.assertEqual(caught.exception.code, 'required_answers_missing')
        self.assertNotIn('F01-P03', caught.exception.missing)
        self.assertFalse(PublicSession.objects.get().spent)
        self.assertFalse(ParticipationReceipt.objects.exists())
        self.assertFalse(AnonymousResponse.objects.filter(binding=self.binding).exists())

    def test_rollback_and_retry_then_replay_does_not_duplicate(self):
        secret, candidate = self.prepared()
        with patch('apps.participation.services.ParticipationReceipt.objects.create', side_effect=IntegrityError('test')):
            with self.assertRaises(IntegrityError): proofs.submit(secret, self.payload, 0, candidate['issuance_ticket'])
        self.assertFalse(PublicSession.objects.get().spent)
        self.assertFalse(AnonymousResponse.objects.filter(binding=self.binding).exists())
        proofs.submit(secret, self.payload, 0, candidate['issuance_ticket'])
        with self.assertRaises(Exception): proofs.submit(secret, self.payload, 0, candidate['issuance_ticket'])
        self.assertEqual(ParticipationReceipt.objects.count(), 1)
        self.assertEqual(AnonymousResponse.objects.filter(binding=self.binding).count(), 1)

    def test_pause_invalidates_session_and_foreign_manager_rejected(self):
        secret, _ = self.prepared()
        with self.assertRaises(PermissionDenied): entry.set_published(self.f.other, self.binding.pk, False)
        entry.set_published(self.f.actor, self.binding.pk, False)
        self.assertFalse(PublicSession.objects.exists())
        with self.assertRaises(Exception): entry.read_session(secret)

    def test_year_cannot_be_forged_in_payload(self):
        secret, candidate = self.prepared()
        payload = dict(self.payload, **{'F01-P03': {'status':'answered','value':'option_6'}})
        with self.assertRaises(Exception): proofs.submit(secret, payload, 0, candidate['issuance_ticket'])
        self.assertFalse(ParticipationReceipt.objects.exists())

    def test_http_directory_csrf_and_real_submission(self):
        client = Client(enforce_csrf_checks=True)
        home = client.get(reverse('public-assessments'))
        self.assertEqual(home.status_code, 200)
        csrf = client.cookies['csrftoken'].value
        url = reverse('public-assessment-choices')
        self.assertEqual(client.post(url, self.context, content_type='application/json').status_code, 403)
        response = client.post(url, self.context, content_type='application/json', HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r['id'] for r in response.json()['collections']], [str(self.binding.pk)])
        response = client.post(reverse('public-assessment-start'), {'binding_id':str(self.binding.pk),'context':self.context}, content_type='application/json', HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200)
        form = client.get(response.json()['next'], follow=True)
        self.assertEqual(form.status_code, 200)
        self.assertNotContains(form, 'name="F01-P03"')
        self.assertContains(form, 'section-nav')
        candidate = client.post(reverse('participation-prepare'), {}, content_type='application/json', HTTP_X_CSRFTOKEN=csrf).json()
        submitted = client.post(reverse('participation-submit'), {'answers': self.payload, 'revision': 0, 'confirmed': True,
            'issuance_ticket': candidate['issuance_ticket']}, content_type='application/json', HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(submitted.status_code, 201, submitted.content[:1000])
        self.assertEqual(submitted.json()['status'], 'issued')

    def test_database_balance_rejects_spend_without_answer(self):
        secret, _ = self.prepared()
        with self.assertRaises(IntegrityError), transaction.atomic():
            PublicSession.objects.update(spent=True, secret_hash=None, expires_at=None, year='')
            with connection.cursor() as cursor: cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')

    def test_calculation_records_public_limitations_without_reinterpreting_year(self):
        from apps.surveys.calculations import calculate
        from apps.calculations.models import CalculationRun
        from apps.calculations.services import validate_run
        for _ in range(5):
            secret, candidate = self.prepared()
            proofs.submit(secret, self.payload, 0, candidate['issuance_ticket'])
        transition_round(self.f.actor, self.binding.collection_round, 'closed', reason='Synthetic public collection complete')
        receipt = calculate(self.f.actor, self.binding.pk, timezone.now(), str(uuid.uuid4()))
        run = CalculationRun.objects.get(pk=receipt['run_id'])
        self.assertEqual(run.manifest['intake']['method'], 'public_self_selected')
        self.assertFalse(run.manifest['intake']['verified_unique_people'])
        validate_run(self.f.actor, run_id=run.pk)

    def test_staff_manager_page_and_home_links(self):
        client = Client(); client.force_login(self.f.actor)
        response = client.get(reverse('public-assessment-manage', args=[self.f.scope.pk, self.binding.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ชุดคำตอบที่ส่งสำเร็จ')
        response = client.get(reverse('public-assessment-setup', args=[self.f.scope.pk, self.source.pk]))
        expected = reverse('assessment-batch-new', args=[self.f.scope.pk]) + '?source=' + str(self.source.pk)
        self.assertRedirects(response, expected)
        response = client.get(expected)
        self.assertContains(response, 'name="group_codes"')
        response = client.get(reverse('workspace'))
        self.assertContains(response, reverse('public-assessments'))


@override_settings(NEXORA_PARTICIPATION_ENABLED=True, NEXORA_PUBLIC_ASSESSMENTS_ENABLED=True, SURVEY_ALLOW_TEST_HTTP=True)
class PublicLeadershipTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.f = setup_surveys(only={'F04'}, data_kind='synthetic')
        cls.source = cls.f.selected['F04']
        from apps.leadership import services as leadership
        from apps.leadership.models import Person, Position, AnnualTarget
        original = cls.source.survey_profile.annual_target
        person = leadership.save_record(cls.f.actor, cls.f.scope, Person, dict(code='PUBLIC-AS',name_th='ผู้ช่วยจำลอง',name_en='Synthetic assistant',user=None))
        position = leadership.save_record(cls.f.actor,cls.f.scope,Position,dict(code='AS-PUBLIC',role='AS',title_th='ผู้ช่วยคณบดี',title_en='Assistant dean',programme=None))
        cls.target = leadership.save_record(cls.f.actor,cls.f.scope,AnnualTarget,dict(plan=original.plan,person=person,position=position,title_th='ผู้ช่วยคณบดี',title_en='Assistant dean',responsibility_th='ภารกิจสมมุติ',responsibility_en='Synthetic duty',start_date=original.start_date,end_date=original.end_date,appointment_kind='substantive',source_reference='Synthetic appointment',eligibility_basis='All staff, public self-selection'))
        leadership.freeze_target(cls.f.actor,cls.f.scope,cls.target.pk,'Synthetic full register reviewed',public_all_staff=True)
        cls.staff_data = setup_data(cls.f.actor, cls.source, 'ST2')
        cls.staff_data.update(group_codes=['ST1','ST2'], count_st1=7, count_st2=5, bundle=cls.source.translation_bundle, confirm=True)
        cls.all_bindings = public_setup.create_all_leaders(cls.f.actor, cls.source, cls.staff_data)
        cls.bindings = [b for b in cls.all_bindings if b.survey_profile.group_code == 'ST2']

    def test_all_targets_no_roster_and_no_information_still_issues_separate_proofs(self):
        self.assertEqual(len(self.bindings), 2)
        self.target.refresh_from_db()
        self.assertFalse(self.target.eligibility.exists())
        self.assertEqual(self.target.snapshot['respondent_policy'], 'all_staff_public')
        for binding in self.all_bindings:
            transition_round(self.f.actor, binding.collection_round, 'open')
            entry.set_published(self.f.actor, binding.pk, True)
        for binding in self.bindings:
            self.assertFalse(binding.collection_round.population_snapshot.members.exists())
            secret = entry.start(binding.pk, validate_context('ST2'))
            candidate = proofs.prepare(secret)
            result = proofs.submit(secret, {'F04-P03': {'status':'answered','value':'none'}}, 0, candidate['issuance_ticket'])
            self.assertEqual(result['status'], 'issued')
            self.assertEqual(binding.survey_responses.get().completion, 'unable_to_assess')
        self.assertEqual(ParticipationReceipt.objects.count(), 2)

    def test_incomplete_leadership_publication_is_not_a_selectable_subset(self):
        binding = self.bindings[0]
        transition_round(self.f.actor, binding.collection_round, 'open')
        entry.set_published(self.f.actor, binding.pk, True)
        with self.assertRaises(Exception): entry.start(binding.pk, validate_context('ST2'))
        self.assertFalse(PublicSession.objects.exists())


    def test_both_groups_counts_idempotency_and_target_ui(self):
        from apps.leadership.public_collections import create_staff_collections, StaffCollectionForm
        self.assertEqual(len(self.all_bindings), 4)
        rows=create_staff_collections(self.f.actor,self.f.scope,self.target.plan_id,self.staff_data)
        self.assertEqual({b.pk for b in rows},{b.pk for b in self.all_bindings})
        for b in rows:
            group=b.survey_profile.group_code
            self.assertEqual(b.collection_round.population_snapshot.counts_by_group,{group:7 if group=='ST1' else 5})
            self.assertFalse(b.collection_round.population_snapshot.members.exists())
        form=StaffCollectionForm(self.staff_data,scope=self.f.scope)
        self.assertTrue(form.is_valid(),form.errors)
        bad=StaffCollectionForm(dict(self.staff_data,group_codes=['ST1']),scope=self.f.scope)
        self.assertFalse(bad.is_valid())
        self.assertIn('group_codes',bad.errors)
        source_form=public_setup.PublicSetupForm(dict(self.staff_data,counting_unit='person',programme_key=''),source=self.source)
        self.assertTrue(source_form.is_valid(),source_form.errors)
        self.client.force_login(self.f.actor)
        response=self.client.get(reverse('f04-target',args=[self.f.scope.pk,self.target.pk]))
        self.assertContains(response,'ST1')
        self.assertContains(response,'ST2')
        self.assertNotContains(response,'id_people')
        self.assertNotContains(response,'id_group_code')
        response=self.client.get(reverse('f04-generate',args=[self.f.scope.pk,self.target.plan_id]))
        self.assertContains(response,'count_st1')
        self.assertContains(response,'count_st2')

    def test_one_open_group_cannot_hide_unpublished_other_group(self):
        for binding in self.bindings:
            transition_round(self.f.actor,binding.collection_round,'open')
            entry.set_published(self.f.actor,binding.pk,True)
        with self.assertRaises(Exception):
            entry.start(self.bindings[0].pk,validate_context('ST2'))
        self.assertFalse(PublicSession.objects.exists())

    def test_direct_creation_atomic_and_covers_new_position_without_template_round(self):
        from apps.leadership import services as leadership
        from apps.leadership.models import Position, AnnualTarget
        from apps.leadership.public_collections import create_staff_collections
        from django.core.exceptions import ValidationError
        pos=leadership.save_record(self.f.actor,self.f.scope,Position,dict(code='AS-SECOND',role='AS',title_th='ผู้ช่วยที่สอง',title_en='Second assistant',programme=None))
        t=leadership.save_record(self.f.actor,self.f.scope,AnnualTarget,dict(plan=self.target.plan,person=self.target.person,position=pos,title_th=pos.title_th,title_en=pos.title_en,responsibility_th='สมมุติ',responsibility_en='Synthetic',start_date=self.target.start_date,end_date=self.target.end_date,appointment_kind='substantive',source_reference='Synthetic',eligibility_basis='All staff'))
        before=PublicCollection.objects.count()
        with self.assertRaises(ValidationError):
            create_staff_collections(self.f.actor,self.f.scope,t.plan_id,self.staff_data)
        self.assertEqual(PublicCollection.objects.count(),before)
        leadership.freeze_target(self.f.actor,self.f.scope,t.pk,'Reviewed',public_all_staff=True)
        real_build=public_setup.build_public_collection
        calls=[]
        def fail_second(*args,**kwargs):
            calls.append(1)
            if len(calls)==2: raise ValidationError('Simulated second-group failure')
            return real_build(*args,**kwargs)
        with patch.object(public_setup,'build_public_collection',side_effect=fail_second):
            with self.assertRaises(ValidationError):
                create_staff_collections(self.f.actor,self.f.scope,t.plan_id,self.staff_data)
        self.assertEqual(PublicCollection.objects.count(),before)
        rows=create_staff_collections(self.f.actor,self.f.scope,t.plan_id,self.staff_data)
        self.assertEqual(len(rows),6)
        self.assertEqual(t.survey_profiles.filter(intake_method='public').count(),2)
        self.assertFalse(t.eligibility.exists())

    def test_http_batch_confirmation_preserves_both_groups(self):
        from tests.confirmation_helpers import confirmed_post
        self.client.force_login(self.f.actor)
        data=dict(self.staff_data,bundle=str(self.source.translation_bundle_id))
        for key in ('open_at','due_at','close_at','expires_at'):
            data[key]=data[key].isoformat()
        url=reverse('f04-generate',args=[self.f.scope.pk,self.target.plan_id])
        response=confirmed_post(self.client,url,data)
        self.assertEqual(response.status_code,302)
        self.assertEqual(PublicCollection.objects.count(),4)

    def test_incomplete_new_draft_allows_shutdown_but_not_new_intake(self):
        from apps.leadership import services as leadership
        from apps.leadership.models import Position, AnnualTarget
        from tests.confirmation_helpers import confirmed_post
        pos=leadership.save_record(self.f.actor,self.f.scope,Position,dict(code='PENDING',role='AS',title_th='ร่าง',title_en='Draft',programme=None))
        leadership.save_record(self.f.actor,self.f.scope,AnnualTarget,dict(plan=self.target.plan,person=self.target.person,position=pos,title_th='ร่าง',title_en='Draft',responsibility_th='สมมุติ',responsibility_en='Synthetic',start_date=self.target.start_date,end_date=self.target.end_date,appointment_kind='substantive',source_reference='Synthetic',eligibility_basis='All staff'))
        self.assertEqual(len(entry.leadership_collections(self.bindings[0],all_groups=True,require_complete=False)),4)
        with self.assertRaises(Exception):entry.leadership_collections(self.bindings[0])
        self.client.force_login(self.f.actor)
        url=reverse('public-assessment-manage',args=[self.f.scope.pk,self.bindings[0].pk])
        response=confirmed_post(self.client,url,{'confirm':'on','action':'withdraw'})
        self.assertEqual(response.status_code,302)
        self.assertFalse(PublicCollection.objects.filter(published=True).exists())


    def test_annual_launch_atomic_confirmation_and_dynamic_form(self):
        from apps.leadership.public_collections import control_plan
        from apps.surveys.web import COOKIE
        from apps.surveys.schema import normalize
        from tests.confirmation_helpers import confirmed_post
        from tests.ui_render_export import export
        from django.core.exceptions import ValidationError
        original=entry.set_published
        calls=[]
        def fail_second(*args,**kwargs):
            calls.append(1)
            if len(calls)==2:raise ValidationError('Injected later failure')
            return original(*args,**kwargs)
        with patch.object(entry,'set_published',side_effect=fail_second):
            with self.assertRaises(ValidationError):control_plan(self.f.actor,self.f.scope,self.target.plan_id,'launch')
        self.assertFalse(PublicCollection.objects.filter(published=True).exists())
        for b in self.all_bindings:
            b.collection_round.refresh_from_db()
            self.assertEqual(b.collection_round.status,'ready')
        self.client.force_login(self.f.actor)
        url=reverse('f04-plan',args=[self.f.scope.pk,self.target.plan_id])
        with override_settings(NEXORA_CONFIRM_IMPORTANT_ACTIONS=True):
            result=confirmed_post(self.client,url,{'action':'launch','confirm':'on'})
        self.assertEqual(result.status_code,302,result.content[:500])
        self.assertEqual(PublicCollection.objects.filter(published=True).count(),4)
        export(self.client.get(url),'f04-plan')
        export(self.client.get(reverse('f04-generate',args=[self.f.scope.pk,self.target.plan_id])),'f04-generate')
        binding=self.bindings[0]
        secret=entry.start(binding.pk,validate_context('ST2'))
        self.client.cookies[COOKIE]=secret
        response=self.client.get(reverse('public-assessment-form'))
        self.assertContains(response,'public-question-rules')
        rules=response.context['schema']['questions']
        self.assertTrue(any(q['visibility'].get('op')=='context_role_and_information' for q in rules))
        self.assertFalse(any('score' in option for q in rules for option in q['options']))
        export(response,'f04-response')
        export(self.client.get(reverse('public-assessment-form')+'?lang=en'),'f04-response-en')
        values={'F04-P03':{'status':'answered','value':'none'}}
        normalized,_=normalize(binding.survey_profile,values,submitting=True)
        self.assertTrue(all(a['status']=='not_shown' for key,a in normalized.items() if not key.startswith('F04-P')))
        candidate = response.context['candidate']
        submitted = self.client.post(reverse('public-assessment-form'), {
            'revision': 0, 'action': 'submit', 'confirm': 'on', 'enhanced_js': '1',
            'F04-P03': 'value:none', **candidate,
        })
        self.assertEqual(submitted.status_code, 302, submitted.content[:1000])
        self.assertEqual(proofs.holder_status(candidate['receipt_token'])['status'], 'issued')
        self.assertEqual(binding.survey_responses.count(), 1)
        control_plan(self.f.actor,self.f.scope,self.target.plan_id,'close','Completed test')
        self.assertFalse(PublicCollection.objects.filter(published=True).exists())


@override_settings(NEXORA_PARTICIPATION_ENABLED=True, NEXORA_PUBLIC_ASSESSMENTS_ENABLED=True, SURVEY_ALLOW_TEST_HTTP=True)
class PublicStaffTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from tests.test_governance import GovernanceTests, publish
        from apps.governance import f05_quantitative
        from apps.surveys.operator import save_round
        GovernanceTests.setUpTestData.__func__(cls)
        cls.bundles['F05'] = publish(cls.actor, f05_quantitative.prepare(cls.actor, cls.scope))
        cls.public = {}
        now = timezone.now()
        for code in ('F05', 'F06'):
            source = save_round(cls.actor,cls.scope,dict(code='Public template '+code,bundle=cls.bundles[code],period=cls.period,owner=cls.actor,open_at=now-timedelta(minutes=5),due_at=now+timedelta(days=1),close_at=now+timedelta(days=2),privacy_notice='Synthetic notice',group_code='ST2',counting_unit='person',context_th='บุคลากรสมมุติ',context_en='Synthetic staff',assessor_role='',study_options=[]),data_kind='synthetic')
            binding = public_setup.create_collection(cls.actor, source, setup_data(cls.actor, source, 'ST2'))
            transition_round(cls.actor, binding.collection_round, 'open')
            entry.set_published(cls.actor, binding.pk, True)
            cls.public[code] = binding

    def test_f05_f06_require_answers_and_issue_independent_workload_proofs(self):
        from tests.test_f05_quantitative import answers as training_answers
        from apps.surveys.schema import questions
        for code, binding in self.public.items():
            secret = entry.start(binding.pk, validate_context('ST2'))
            candidate = proofs.prepare(secret)
            with self.assertRaises((proofs.ReceiptError, Exception)):
                proofs.submit(secret, {}, 0, candidate['issuance_ticket'])
            self.assertFalse(binding.survey_responses.exists())
            if code == 'F05':
                payload = training_answers('0')
            else:
                payload = {}
                for key, question in questions(binding.survey_profile).items():
                    if question.answer_type == 'integer_scale': payload[key] = {'status':'answered','value':4}
                    elif question.answer_type == 'single_choice': payload[key] = {'status':'answered','value':next(o.code for o in question.options.all() if o.answer_status == 'answered')}
                    elif question.answer_type == 'text' and '-O' not in key: payload[key] = {'status':'answered','value':'Synthetic development priority'}
            self.assertEqual(proofs.submit(secret, payload, 0, candidate['issuance_ticket'])['status'], 'issued')
            self.assertEqual(binding.survey_responses.count(), 1)
        self.assertEqual(ParticipationReceipt.objects.count(), 2)


@override_settings(NEXORA_PARTICIPATION_ENABLED=True, NEXORA_PUBLIC_ASSESSMENTS_ENABLED=True, SURVEY_ALLOW_TEST_HTTP=True)
class PublicOtherSurveyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.f = setup_surveys(only={'F02', 'F03'}, data_kind='synthetic')
        cls.bindings = {}
        for code, source in cls.f.selected.items():
            data = setup_data(cls.f.actor, source, source.survey_profile.group_code)
            binding = public_setup.create_collection(cls.f.actor, source, data)
            transition_round(cls.f.actor, binding.collection_round, 'open')
            entry.set_published(cls.f.actor, binding.pk, True)
            cls.bindings[code] = binding

    def test_generic_public_forms_require_all_visible_answers_and_issue_proofs(self):
        from apps.surveys.schema import questions, visible, fixed, options
        from apps.surveys.web import COOKIE
        from django.core.exceptions import ValidationError
        for code, binding in self.bindings.items():
            secret = entry.start(binding.pk, validate_context(binding.survey_profile.group_code))
            client = Client(); client.cookies[COOKIE] = secret
            page = client.get(reverse('public-assessment-form')+'?lang=en')
            self.assertEqual(page.status_code, 200, code)
            self.assertContains(page, 'Submit and receive proof')
            candidate = page.context['candidate']
            with self.assertRaises((proofs.ReceiptError, ValidationError)):
                proofs.submit(secret, {}, 0, candidate['issuance_ticket'])
            payload = {}
            for qid, q in questions(binding.survey_profile).items():
                if fixed(binding.survey_profile, q) is not None or '-O' in qid or not visible(binding.survey_profile, q, payload):
                    continue
                if q.answer_type == 'text': value = 'Synthetic improvement'
                elif q.answer_type == 'integer_scale': value = 4
                else:
                    opt = next(o for o in options(binding.survey_profile, q) if o.answer_status == 'answered')
                    value = [opt.code] if q.answer_type == 'multi_choice' else opt.code
                payload[qid] = {'status':'answered','value':value}
                if qid == 'F02-P04' and value == 'month_year': payload[qid]['month'] = timezone.now().strftime('%Y-%m')
            fields = {'revision':0, 'action':'submit', 'confirm':'on', 'enhanced_js':'1', **candidate}
            for qid, answer in payload.items():
                value = answer['value']
                q = questions(binding.survey_profile)[qid]
                fields[qid] = value if isinstance(value,list) or q.answer_type == 'text' else 'value:'+str(value)
                if 'month' in answer: fields[qid+'-month'] = answer['month']
            submitted = client.post(reverse('public-assessment-form')+'?lang=en', fields)
            self.assertEqual(submitted.status_code, 302, submitted.content[:1500])
            self.assertEqual(proofs.holder_status(candidate['receipt_token'])['status'], 'issued')
            self.assertEqual(binding.survey_responses.count(), 1)
