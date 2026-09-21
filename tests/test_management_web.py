"""User journeys and authorization regressions for catalog/round setup."""
from datetime import timedelta
import json
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.accounts.models import Organization, AccessScope, Role, Membership, RoleAssignment, ALLOWED_PERMISSIONS
from apps.accounts.account_setup import create_account
from apps.auditlog.models import AuditEvent
from apps.catalog.models import Instrument, InstrumentVersion, Question, QuestionOption, ContentTranslation, InstrumentContent, TranslationBundle
from apps.catalog.services import update_question, edit_translation
from apps.catalog.management_services import prepare_translations, editor_token, translation_pack
from apps.rounds.models import ReportingPeriod, CollectionRound, PopulationSnapshot, PopulationMember, RespondentGroup
from apps.selfassessments.models import SelfAssessmentAssignment, SelfAssessmentRevision


class ManagementWebTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Synthetic web management')
        cls.scope = AccessScope.objects.create(organization=cls.org, code='WEB', name='Synthetic web scope')
        cls.foreign = AccessScope.objects.create(organization=cls.org, code='OTHER', name='Other scope')
        cls.actor = get_user_model().objects.create_user(username='web-manager')
        cls.reader = get_user_model().objects.create_user(username='web-reader')
        all_role = Role.objects.create(code='web-all', permissions=sorted(ALLOWED_PERMISSIONS))
        read_role = Role.objects.create(code='web-read', permissions=['catalog.read'])
        cls.self_role = Role.objects.create(code='self-service-v1', permissions=['self.read', 'self.write'])
        for user, role in [(cls.actor, all_role), (cls.reader, read_role)]:
            m = Membership.objects.create(user=user, organization=cls.org)
            RoleAssignment.objects.create(membership=m, role=role, scope=cls.scope)
        RoleAssignment.objects.create(membership=Membership.objects.get(user=cls.actor), role=all_role, scope=cls.foreign)
        cls.version = InstrumentVersion.objects.create(instrument=Instrument.objects.create(scope=cls.scope, code='F06'),
            version='web-test', title_th='F06 การประเมินสมรรถนะ ทักษะ และค่านิยม', assessment_method='self_report', group_codes=['ST1', 'ST2'])
        original = next(q for q in json.loads((settings.BASE_DIR/'catalog/questions.json').read_text()) if q['question_id']=='F06-K01')
        cls.q = Question.objects.create(version=cls.version, question_id='F06-K01', text_th=original['text']['th'], answer_type='integer_scale', group_codes=['ST1','ST2'])
        for n in range(1,6):QuestionOption.objects.create(question=cls.q, code=str(n), label_th=str(n), score=n, position=n)

    def setUp(self):
        self.client=Client(enforce_csrf_checks=True)
        self.client.force_login(self.actor)
        self.client.get('/workspace/')

    def url(self, name, **kw):
        return reverse(name, kwargs={'scope_id':self.scope.pk, **kw})

    def vurl(self, name, **kw):
        return self.url('portal-catalog-'+name, version_id=self.version.pk, **kw)

    def post(self, url, data):
        return self.client.post(url, {**data, 'csrfmiddlewaretoken':self.client.cookies['csrftoken'].value})

    def instructions(self):
        page=self.client.get(self.vurl('edit'))
        self.assertEqual(page.status_code,200)
        form=page.context['form']
        r=self.post(self.vurl('edit'), {'snapshot':form['snapshot'].value(), 'title_th':self.version.title_th,
            'instruction':translation_pack()['instructions']['F06'], 'instructions_curated':'on'})
        self.assertEqual(r.status_code,302, r.content.decode()[:2000])

    def prepared(self):
        self.instructions()
        r=self.post(self.vurl('prepare'),{})
        self.assertEqual(r.status_code,302)
        return self.version.translation_bundles.get()

    def review_data(self, page):
        data={'checked':[]}
        for row in page.context['rows']:
            if row['reviewable']:
                pk=str(row['th'].pk)
                data['checked'].append(pk)
                data.update({f'en_{pk}':str(row['en'].pk), f'th_token_{pk}':row['th_token'], f'en_token_{pk}':row['en_token']})
        return data

    def published(self):
        b=self.prepared()
        u=self.vurl('review',bundle_id=b.pk)
        r=self.post(u,self.review_data(self.client.get(u)))
        self.assertEqual(r.status_code,302)
        r=self.post(self.vurl('publish'),{'bundle':b.pk,'confirm':'on'})
        self.assertEqual(r.status_code,302, r.content.decode()[:2000])
        self.version.refresh_from_db();b.refresh_from_db()
        self.assertEqual(self.version.status,'published')
        return b

    def make_round(self):
        b=self.published()
        r=self.post(self.url('round-period-new'), {'code':'Synthetic AY','calendar_type':'academic','reporting_year_be':2569,
            'start_date':'2026-01-01','last_date':'2026-12-31','reason':'Synthetic actual calendar','confirm':'on'})
        self.assertEqual(r.status_code,302,r.content.decode()[:2000])
        p=ReportingPeriod.objects.get()
        self.assertEqual(str(p.end_date),'2027-01-01')
        now=timezone.localtime()
        r=self.post(self.url('round-new'), {'code':'Synthetic F06 round','period':p.pk,'owner':self.actor.pk,'bundle':b.pk,
            'open_at':(now-timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'), 'due_at':(now+timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),
            'close_at':(now+timedelta(days=2)).strftime('%Y-%m-%dT%H:%M'),'privacy_notice':'Synthetic data-use notice'})
        self.assertEqual(r.status_code,302,r.content.decode()[:2000])
        return CollectionRound.objects.get()

    def population(self,r):
        response=self.post(self.url('round-population',round_id=r.pk), {'definition':'Synthetic staff roster', 'st1':1,'st2':0,
            'source_title':'Synthetic roster','source_location':'Synthetic reference 01','captured_at':timezone.localtime().strftime('%Y-%m-%dT%H:%M')})
        self.assertEqual(response.status_code,302,response.content.decode()[:2000])
        return PopulationSnapshot.objects.get()

    def test_population_shows_actual_form_despite_misleading_round_title(self):
        from apps.rounds.services import update_record
        r = self.make_round()
        update_record(self.actor, r, reason='Synthetic misleading title', code='F03-Synthetic round')
        page = self.client.get(self.url('round-population', round_id=r.pk))
        self.assertContains(page, 'data-round-instrument="F06"')
        self.assertEqual(page.context['round_binding'].instrument_version.instrument.code, 'F06')
        listing = self.client.get(self.url('round-list'))
        self.assertContains(listing, 'F03-Synthetic round')
        self.assertContains(listing, 'F06 · web-test')

    def test_complete_web_journey_including_account_assignment_and_submission(self):
        r=self.make_round();snapshot=self.population(r)
        group=RespondentGroup.objects.get(scope=self.scope,code='ST1')
        result=self.post(self.url('round-member-new',round_id=r.pk),{'eligible_unit_key':'S-001','group':group.pk})
        self.assertEqual(result.status_code,302)
        member=PopulationMember.objects.get()
        result=self.post(self.url('round-member-edit',round_id=r.pk,member_id=member.pk),{'eligible_unit_key':'S-002','group':group.pk,'reason':'Corrected synthetic ID'})
        self.assertEqual(result.status_code,302)
        for action in ['freeze','ready']:
            result=self.post(self.url('round-action',round_id=r.pk,action=action),{'confirm':'on','reason':'Synthetic checked'})
            self.assertEqual(result.status_code,302,result.content.decode()[:1000])
        r.refresh_from_db();self.assertEqual(r.status,'ready')
        result=self.post(self.url('portal-account-new'),{'username':'synthetic-new','first_name':'Test','last_name':'Person','email':'',
            'password1':'Synthetic-Test-938!Password','password2':'Synthetic-Test-938!Password','role':self.self_role.pk})
        self.assertEqual(result.status_code,302,result.content.decode()[:1800])
        owner=get_user_model().objects.get(username='synthetic-new')
        self.assertTrue(owner.check_password('Synthetic-Test-938!Password'))
        self.assertFalse(owner.is_staff or owner.is_superuser)
        selected=r.round_instruments.get()
        result=self.post(self.url('operator-assign',selected_id=selected.pk,member_id=member.pk),{'owner':owner.pk,'duties':'Synthetic teaching work','expected_F06-K01':3})
        self.assertEqual(result.status_code,302,result.content.decode()[:2000])
        result=self.post(self.url('operator-collection',selected_id=selected.pk),{'action':'open','reason':'Synthetic start'})
        self.assertEqual(result.status_code,302)
        self.client.force_login(owner)
        self.client.get('/workspace/')
        self.post('/language/',{'language':'en'})
        assignment=SelfAssessmentAssignment.objects.get()
        u=reverse('self-assessment-detail',kwargs={'assignment_id':assignment.pk})
        response=self.client.get(u)
        self.assertContains(response,'I understand the College')
        form=response.context['form']
        response=self.post(u,{'action':'submitted','expected_revision':0,'idempotency_key':form['idempotency_key'].value(),'F06-K01':'value:4'})
        self.assertEqual(response.status_code,302,response.content.decode()[:2000])
        self.assertEqual(SelfAssessmentRevision.objects.get().completeness,'complete')
        self.client.force_login(self.actor)
        self.client.get('/workspace/')
        self.assertEqual(self.post(self.url('operator-collection',selected_id=selected.pk),{'action':'closed','reason':'Synthetic done'}).status_code,302)

    def test_publication_rejects_missing_or_unreviewed_content(self):
        b=self.prepared()
        self.assertEqual(self.post(self.vurl('publish'),{'bundle':b.pk,'confirm':'on'}).status_code,422)
        self.version.refresh_from_db();b.refresh_from_db()
        self.assertEqual((self.version.status,b.status),('draft','draft'))
        self.assertFalse(b.translations.filter(status='approved').exists())

    def test_stale_review_token_rolls_back_all_selected_pairs(self):
        b=self.prepared();u=self.vurl('review',bundle_id=b.pk)
        page=self.client.get(u);data=self.review_data(page)
        row=list(page.context['rows'])[-1]
        edit_translation(self.actor,row['en'],'Changed after the page was opened')
        self.assertEqual(self.post(u,data).status_code,422)
        self.assertFalse(b.translations.filter(status='approved').exists())

    def test_review_renders_the_snapshot_that_its_token_represents(self):
        b=self.prepared();u=self.vurl('review',bundle_id=b.pk)
        from apps.catalog.services import translation_review_snapshot as actual
        changed=[]
        def intervene(actor,entry):
            if entry.locale=='en' and not changed:
                edit_translation(actor,entry,'New text before snapshot was read')
                changed.append(True)
            return actual(actor,entry)
        with patch('apps.catalog.management_web.translation_review_snapshot',side_effect=intervene):
            page=self.client.get(u)
        self.assertContains(page,'New text before snapshot was read')

    def test_prepare_preserves_manual_english_and_never_approves(self):
        b=self.prepared();e=b.translations.filter(locale='en').first()
        edit_translation(self.actor,e,'Manual English revision')
        self.post(self.vurl('prepare'),{})
        e.refresh_from_db();self.assertEqual(e.text,'Manual English revision')
        self.assertFalse(b.translations.filter(status='approved').exists())

    def test_prepare_requeues_unchanged_english_but_keeps_changed_source_stale(self):
        b = self.prepared()
        entries = list(b.translations.filter(locale='en'))
        from apps.catalog.services import source_texts
        from apps.catalog.models import source_hash
        update_question(self.actor, self.q, text_th='ต้นฉบับเปลี่ยนแล้ว')
        before = {e.pk: e.text for e in entries}
        prepare_translations(self.actor, self.version.pk)
        originals = source_texts(self.version)
        for entry in b.translations.filter(locale='en'):
            self.assertEqual(entry.text, before[entry.pk])
            expected = 'needs_review' if entry.source_hash == source_hash(originals[entry.content_key]) else 'stale'
            self.assertEqual(entry.status, expected)

    def test_management_title_and_labels_follow_selected_ui_language(self):
        page = self.client.get(self.vurl('edit'))
        self.assertContains(page, '<h1>ชื่อและคำชี้แจง</h1>', html=True)
        self.post('/language/', {'language': 'en'})
        page = self.client.get(self.vurl('edit'))
        self.assertContains(page, '<h1>Title and instructions</h1>', html=True)
        self.assertContains(page, '<label for="id_title_th">Thai title<span class="nx-required" aria-hidden="true"> *</span></label>', html=True)

    def test_editor_rejects_stale_tab_and_published_version(self):
        p=self.client.get(self.vurl('edit'))
        update_question(self.actor,self.q,text_th='Changed source')
        response=self.post(self.vurl('edit'),{'snapshot':p.context['form']['snapshot'].value(),'title_th':'Lost update',
            'instruction':'Instructions','instructions_curated':'on'})
        self.assertEqual(response.status_code,422)
        self.version.refresh_from_db();self.assertNotEqual(self.version.title_th,'Lost update')

    def test_question_create_edit_delete_through_forms(self):
        u=self.vurl('question-new')
        p=self.client.get(u)
        data={'snapshot':p.context['form']['snapshot'].value(),'question_id':'F06-X01','text_th':'Custom question','answer_type':'text',
            'group_codes':['ST1','ST2'],'choices-TOTAL_FORMS':0,'choices-INITIAL_FORMS':0,'choices-MIN_NUM_FORMS':0,'choices-MAX_NUM_FORMS':40}
        result=self.post(u,data);self.assertEqual(result.status_code,302,result.content.decode()[:1200])
        q=self.version.questions.get(question_id='F06-X01')
        u=self.vurl('question-edit',question_id=q.pk);p=self.client.get(u)
        result=self.post(u,{**data,'snapshot':p.context['form']['snapshot'].value(),'text_th':'Edited custom question'})
        self.assertEqual(result.status_code,302)
        u=self.vurl('question-delete',question_id=q.pk);p=self.client.get(u)
        self.assertTrue(self.version.questions.filter(pk=q.pk).exists())
        result=self.post(u,{'snapshot':p.context['form']['snapshot'].value(),'reason':'Synthetic removal','confirm':'on'})
        self.assertEqual(result.status_code,302)
        self.assertFalse(self.version.questions.filter(pk=q.pk).exists())

    def test_readonly_gets_do_not_mutate_and_csrf_protects_writes(self):
        before=AuditEvent.objects.count()
        for u in [self.vurl('detail'),self.vurl('edit'),self.vurl('question-new'),self.url('round-new'),self.url('round-list'),self.url('portal-account-new')]:
            self.assertEqual(self.client.get(u).status_code,200,u)
        self.assertEqual(AuditEvent.objects.count(),before)
        self.assertEqual(self.client.get(self.vurl('prepare')).status_code,405)
        for u in [self.vurl('prepare'),self.vurl('publish'),self.url('round-new'),self.url('portal-account-new')]:
            self.assertEqual(self.client.post(u,{}).status_code,403)

    def test_question_search_retains_scope_permissions_and_does_not_write(self):
        Question.objects.create(version=self.version, question_id='F06-X99', text_th='Unique search phrase',
                                answer_type='text', group_codes=['ST1'])
        before = AuditEvent.objects.count()
        self.client.force_login(self.reader)
        page = self.client.get(self.vurl('detail'), {'q': 'Unique search'})
        self.assertEqual([q.question_id for q in page.context['questions']], ['F06-X99'])
        self.assertEqual(page.context['total_questions'], 2)
        self.assertNotContains(page, self.vurl('question-new'))
        self.assertEqual(AuditEvent.objects.count(), before)
        page = self.client.get(self.vurl('detail'), {'q': 'f06-k01'})
        self.assertEqual([q.pk for q in page.context['questions']], [self.q.pk])
        self.assertEqual(len(self.client.get(self.vurl('detail'), {'q': 'absent'}).context['questions']), 0)
        wrong = reverse('portal-catalog-detail', kwargs={'scope_id': self.foreign.pk, 'version_id': self.version.pk})
        self.assertEqual(self.client.get(wrong, {'q': 'Unique search'}).status_code, 403)

    def test_invalid_choice_retains_entered_text_and_returns_field_error(self):
        url = self.vurl('question-new')
        form = self.client.get(url).context['form']
        response = self.post(url, {'snapshot': form['snapshot'].value(), 'question_id': 'F06-X98',
            'text_th': 'Keep this question', 'answer_type': 'single_choice', 'group_codes': ['ST1'],
            'choices-TOTAL_FORMS': 1, 'choices-INITIAL_FORMS': 0,
            'choices-0-code': 'A', 'choices-0-label_th': 'Keep this choice',
            'choices-0-score': 'invalid-number', 'choices-0-answer_status': 'answered'})
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, 'Keep this choice', status_code=422)
        self.assertContains(response, 'id_choices-0-score_error', status_code=422)
        self.assertFalse(self.version.questions.filter(question_id='F06-X98').exists())

    def test_scope_isolation_and_readonly_role(self):
        wrong=reverse('portal-catalog-edit',kwargs={'scope_id':self.foreign.pk,'version_id':self.version.pk})
        self.assertEqual(self.client.get(wrong).status_code,404)
        self.client.force_login(self.reader)
        for u in [self.vurl('edit'),self.vurl('publish'),self.vurl('question-new'),self.url('round-new'),self.url('portal-account-new')]:
            self.assertEqual(self.client.get(u).status_code,403,u)
        self.assertEqual(self.client.get(self.vurl('detail')).status_code,200)

    def test_population_count_and_frozen_edit_guards(self):
        r=self.make_round();s=self.population(r)
        u=self.url('round-action',round_id=r.pk,action='freeze')
        self.assertEqual(self.post(u,{'confirm':'on','reason':'Synthetic'}).status_code,422)
        group=RespondentGroup.objects.get(scope=self.scope,code='ST1')
        murl=self.url('round-member-new',round_id=r.pk)
        self.assertEqual(self.post(murl,{'group':group.pk,'eligible_unit_key':'S1'}).status_code,302)
        self.assertEqual(self.post(murl,{'group':group.pk,'eligible_unit_key':'S1'}).status_code,422)
        self.assertEqual(self.post(u,{'confirm':'on','reason':'Synthetic'}).status_code,302)
        self.assertEqual(self.post(murl,{'group':group.pk,'eligible_unit_key':'S2'}).status_code,422)
        member=PopulationMember.objects.get()
        self.assertEqual(self.post(self.url('round-member-delete',round_id=r.pk,member_id=member.pk),{'confirm':'on','reason':'Try frozen deletion'}).status_code,422)
        self.assertTrue(PopulationMember.objects.filter(pk=member.pk).exists())

    def test_cannot_edit_published_content_but_can_clone(self):
        self.published()
        p=self.client.get(self.vurl('edit'))
        response=self.post(self.vurl('edit'),{'snapshot':p.context['form']['snapshot'].value(),'title_th':'Changed published',
            'instruction':'Instructions','instructions_curated':'on'})
        self.assertEqual(response.status_code,422)
        response=self.post(self.vurl('clone'),{'new_version':'web-copy'})
        self.assertEqual(response.status_code,302)
        copy=self.version.instrument.versions.get(version='web-copy')
        self.assertFalse(ContentTranslation.objects.filter(bundle__instrument_version=copy,status='approved').exists())

    def test_delete_unused_draft_round_preserves_period_and_published_form(self):
        r=self.make_round()
        response=self.post(self.url('round-action',round_id=r.pk,action='delete'),{'confirm':'on','reason':'Unused synthetic round'})
        self.assertEqual(response.status_code,302)
        self.assertFalse(CollectionRound.objects.exists())
        self.assertTrue(ReportingPeriod.objects.exists())
        self.version.refresh_from_db();self.assertEqual(self.version.status,'published')

    def test_no_account_or_membership_survives_failed_delegation(self):
        membership=Membership.objects.get(user=self.reader)
        role=Role.objects.create(code='only-role-management',permissions=['role.manage'])
        RoleAssignment.objects.create(membership=membership,role=role,scope=self.scope)
        self.client.force_login(self.reader);self.client.get('/workspace/')
        response=self.post(self.url('portal-account-new'),{'username':'forbidden-user','first_name':'Test','last_name':'User','email':'',
            'password1':'Synthetic-Test-938!Password','password2':'Synthetic-Test-938!Password','role':self.self_role.pk})
        self.assertEqual(response.status_code,403)
        self.assertFalse(get_user_model().objects.filter(username='forbidden-user').exists())

    def test_translation_pack_covers_all_original_questions_and_choices(self):
        pack=translation_pack()['texts'];p=settings.BASE_DIR/'catalog'
        qs=json.loads((p/'questions.json').read_text());scales={s['scale_id']:s for s in json.loads((p/'scales.json').read_text())}
        self.assertEqual(len(qs),190)
        for q in qs:
            self.assertTrue(pack.get(q['text']['th']),q['question_id'])
            for o in q.get('options') or scales.get(q.get('scale_id'),{}).get('options',[]):
                self.assertTrue(pack.get(o['label']['th']),q['question_id'])


class F06RevisionCompatibilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from tests.m2_fixtures import scenario
        cls.f=scenario(status='ready')

    def cloned(self, changed_score=False):
        from apps.catalog.services import clone_instrument_version, approve_translation, translation_review_snapshot, publish_bundle, publish_instrument_version, source_texts
        from apps.catalog.models import source_hash
        new=clone_instrument_version(self.f.actor,self.f.versions['F06'],'1.2')
        if changed_score:
            option=new.questions.get(question_id='F06-K01').options.get(code='1')
            option.score=2;option.save()
        else:
            update_question(self.f.actor,new.questions.get(question_id='F06-K01'),text_th='Synthetic revised wording')
        b=new.translation_bundles.get()
        texts=source_texts(new)
        for e in b.translations.all():
            edit_translation(self.f.actor,e,texts[e.content_key] if e.locale=='th' else 'Synthetic revised English')
            e.refresh_from_db()
            approve_translation(self.f.actor,e,reviewed_token=translation_review_snapshot(self.f.actor,e)['reviewed_token'])
        publish_bundle(self.f.actor,b)
        new=publish_instrument_version(self.f.actor,new)
        from apps.rounds.services import transition_round, update_record
        r=transition_round(self.f.actor,self.f.round,'draft',reason='Synthetic revision selection')
        s=update_record(self.f.actor,self.f.round_instruments['F06'],reason='Synthetic revised wording',instrument_version=new,translation_bundle=b)
        r=transition_round(self.f.actor,r,'ready');r=transition_round(self.f.actor,r,'open');r=transition_round(self.f.actor,r,'closed',reason='Synthetic closed')
        return new,s,r

    def test_wording_revision_reuses_math_and_retains_actual_version(self):
        from dataclasses import replace
        from tests.m2_fixtures import packet
        from apps.calculations.services import record_calculation
        from apps.calculations.models import CalculationInputSnapshot
        new,selected,r=self.cloned()
        p=packet(self.f)
        response=replace(p.responses[0],context=replace(p.responses[0].context,instrument_version='1.2'))
        p=replace(p,round_instrument_id=selected.pk,binding_id=new.bindings.get(indicator__code='7.4-3').pk,responses=(response,))
        receipt=record_calculation(self.f.actor,round_id=r.pk,inputs=[p],cutoff=self.f.cutoff,idempotency_key='wording-revision')
        self.assertEqual(receipt.result_count,1)
        snapshot=CalculationInputSnapshot.objects.get(run_id=receipt.run_id)
        self.assertEqual(snapshot.definition['instrument']['version'],'1.2')
        self.assertEqual(snapshot.definition['series']['instrument_version'],'1.2')
        self.assertEqual(snapshot.payload['spec']['instrument_version'],'1.1')

    def test_revision_cannot_change_scores_and_reuse_the_formula(self):
        from dataclasses import replace
        from tests.m2_fixtures import packet
        from apps.calculations.services import _definition
        new,selected,r=self.cloned(changed_score=True)
        p=replace(packet(self.f),round_instrument_id=selected.pk,binding_id=new.bindings.get(indicator__code='7.4-3').pk)
        with self.assertRaisesMessage(ValidationError,'options differ'):
            _definition(r,p,self.f.catalog)

    def test_unrelated_revision_does_not_inherit_compatibility(self):
        from apps.calculations.services import _uses_f06_contract
        version=InstrumentVersion.objects.create(instrument=self.f.versions['F06'].instrument,
            version='arbitrary',title_th='Unrelated',assessment_method='self_report')
        self.assertFalse(_uses_f06_contract(version,'1.1'))

    def test_bound_question_web_editor_ignores_tampered_scores_and_keeps_all_options(self):
        from apps.catalog.services import clone_instrument_version
        new = clone_instrument_version(self.f.actor, self.f.versions['F06'], 'web-edit')
        new.group_codes = ['ST1', 'ST2']
        new.save()
        question = new.questions.get(question_id='F06-K01')
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.f.actor)
        url = reverse('portal-catalog-question-edit', kwargs={'scope_id': self.f.scope.pk, 'version_id': new.pk, 'question_id': question.pk})
        page = client.get(url)
        options = list(question.options.order_by('position', 'pk'))
        self.assertEqual(len(page.context['options'].forms), len(options))
        data = {'csrfmiddlewaretoken': client.cookies['csrftoken'].value,
            'snapshot': page.context['form']['snapshot'].value(), 'text_th': 'ข้อความแก้ไขสำหรับทดสอบ',
            'choices-TOTAL_FORMS': len(options), 'choices-INITIAL_FORMS': len(options),
            'choices-MIN_NUM_FORMS': 0, 'choices-MAX_NUM_FORMS': 40}
        for i, option in enumerate(options):
            data.update({f'choices-{i}-id': option.pk, f'choices-{i}-label_th': option.label_th,
                         f'choices-{i}-score': 999, f'choices-{i}-DELETE': 'on'})
        response = client.post(url, data)
        details = (response.context['form'].errors, response.context['options'].errors) if response.status_code == 422 else response.status_code
        self.assertEqual(response.status_code, 302, details)
        question.refresh_from_db()
        self.assertEqual(question.text_th, 'ข้อความแก้ไขสำหรับทดสอบ')
        self.assertEqual(list(question.options.order_by('position', 'pk').values_list('score', flat=True)), [o.score for o in options])
