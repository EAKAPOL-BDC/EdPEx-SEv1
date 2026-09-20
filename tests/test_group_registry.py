"""Source fidelity, identity preservation and scoped presentation regressions."""
import hashlib
import json
import os
import re
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils.translation import override
from apps.accounts.models import Organization, AccessScope
from apps.catalog.group_registry import registry, group_info, group_display, export_group
from apps.catalog.models import Instrument, InstrumentVersion, Question, TranslationBundle, InstrumentContent, ContentTranslation, source_hash
from apps.catalog.management_forms import QuestionForm
from apps.rounds.models import RespondentGroup
from apps.surveys.forms import SurveyRoundForm
from tests.m2_fixtures import grant
from apps.catalog.services import source_texts, approve_translation, translation_review_snapshot, publish_bundle, publish_instrument_version


class GroupRegistryTests(SimpleTestCase):
    def test_source_taxonomy_and_existing_codes_are_distinct(self):
        data = registry()
        self.assertEqual(hashlib.sha256((settings.BASE_DIR / data['source']['file']).read_bytes()).hexdigest(), data['source']['sha256'])
        rows = data['groups']
        self.assertEqual(len(rows), len({r['code'] for r in rows}))
        official = [r for r in rows if r['source'] == 'register']
        self.assertEqual(len([r for r in official if not r['parent']]), 15)
        self.assertEqual({r['code']: r['parent'] for r in official if r['parent']}, {
            'C2.1':'C2', 'C2.2':'C2', 'C3.1':'C3', 'C4.1':'C4', 'C5.1':'C5', 'C5.2':'C5', 'C5.3':'C5'})
        self.assertEqual({r['code'] for r in rows if r['source'] != 'register'}, {'S3-1','S3-2','ST1','ST2'})
        self.assertEqual(group_info('S3-1')['parent_code'], 'S3')
        self.assertNotEqual(group_display('C4.1'), group_display('C5.1'))
        self.assertEqual(group_info('M1')['category_key'], 'markets')
        self.assertFalse(group_info('F06-M1')['known'])
        self.assertFalse(group_info('C3.2')['known'])
        original = json.loads((settings.BASE_DIR / 'catalog/groups.json').read_text())
        self.assertEqual(len(original), 17)
        self.assertTrue(all(group_info(r['code'])['known'] for r in original))

    def test_language_fallback_and_html_escaping(self):
        with override('th'):
            self.assertEqual(group_display('C2.1'), 'C2.1 · นิสิตชาวไทย (C2 · นิสิตระดับบัณฑิตศึกษา)')
        with override('en'):
            self.assertIn('Thai students (C2 · Graduate students)', group_display('C2.1'))
        self.assertEqual(group_info('X-1', fallback='Custom label')['code'], 'X-1')
        self.assertEqual(group_info('X-1', fallback='Custom label')['label'], 'Custom label')
        html = Template('{% load portal_ui %}{% group_text code fallback %}').render(Context({'code':'<script>', 'fallback':'<img onerror=x>'}))
        self.assertNotIn('<script>', html)
        self.assertNotIn('<img', html)
        self.assertIn('&lt;img', html)
        detail = Template("{% include 'portal/components/group_context.html' with code='CO-2' locale='th' %}").render(Context())
        self.assertIn('ชั้นปีที่ 4', detail)
        self.assertIn('<details>', detail)
        detail = Template("{% include 'portal/components/group_context.html' with code='C2.1' locale='en' %}").render(Context())
        self.assertIn('Thai students (C2 · Graduate students)', detail)


    def test_export_keeps_parent_and_subgroup_distinct(self):
        self.assertEqual(export_group('C4.1')[:3], ['ภาครัฐ','C4','ผู้ให้ทุนวิจัย'])
        self.assertEqual(export_group('C5.1')[:3], ['ภาครัฐ','C5','ผู้รับบริการวิชาการ'])
        self.assertIn('ชั้นปีที่ 4', export_group('CO-2')[4])


class GroupWebTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        org = Organization.objects.create(name='Synthetic group register QA')
        cls.scope = AccessScope.objects.create(organization=org, code='GROUP-QA', name='Synthetic only')
        cls.foreign = AccessScope.objects.create(organization=org, code='OTHER-GROUP-QA', name='Other scope')
        cls.actor = get_user_model().objects.create_user(username='group-qa-reader')
        grant(cls.actor, cls.scope, ['catalog.read','catalog.edit','round.manage','catalog.publish','translation.review'], 'group-qa-reader')
        cls.version = InstrumentVersion.objects.create(instrument=Instrument.objects.create(scope=cls.scope, code='F01'),
            version='group-qa', title_th='แบบสำรวจประสบการณ์ผู้เรียน', assessment_method='survey', group_codes=['C1','C2.1','C2.2','C3.1'])
        cls.question = Question.objects.create(version=cls.version, question_id='F01-X01', text_th='คำถามตัวอย่าง', answer_type='text', group_codes=['C2.1'])
        # Publish small, reviewed fixtures through the same service and database guards.
        def publish(scope, actor, code, codes, instrument=None):
            v = InstrumentVersion.objects.create(instrument=instrument or Instrument.objects.create(scope=scope, code=code),
                version='group-qa-published', title_th='Synthetic published', assessment_method='survey', group_codes=codes, instructions_curated=True)
            Question.objects.create(version=v, question_id=code+'-X01', text_th='คำถามจำลอง', answer_type='text', group_codes=codes)
            InstrumentContent.objects.create(version=v, content_key=code+'.instruction', kind='instruction', audience='respondent', text_th='คำชี้แจงจำลอง')
            b = TranslationBundle.objects.create(instrument_version=v, bundle_version='qa')
            for key, text in source_texts(v).items():
                for locale in ('th','en'):
                    entry = ContentTranslation.objects.create(bundle=b, content_key=key, locale=locale, text=text if locale == 'th' else 'Synthetic reviewed wording', source_hash=source_hash(text))
                    approve_translation(actor, entry, reviewed_token=translation_review_snapshot(actor, entry)['reviewed_token'])
            publish_bundle(actor, b)
            publish_instrument_version(actor, v)
            b.refresh_from_db()
            return b
        cls.bundle = publish(cls.scope, cls.actor, 'F01', cls.version.group_codes, cls.version.instrument)
        publish(cls.scope, cls.actor, 'F02', ['C4.1','C5.1'])
        other = get_user_model().objects.create_user(username='foreign-group-qa')
        grant(other, cls.foreign, ['catalog.read','catalog.edit','catalog.publish','translation.review'], 'foreign-group-qa')
        publish(cls.foreign, other, 'F02', ['CO-1'])
        cls.old_group = RespondentGroup.objects.create(scope=cls.scope, code='C2.1', label='C2.1')

    def setUp(self):
        self.client.force_login(self.actor)

    def test_registry_search_hierarchy_access_and_no_writes(self):
        url = reverse('group-register', args=[self.scope.pk])
        before = list(RespondentGroup.objects.values_list('code','label'))
        page = self.client.get(url)
        self.assertContains(page, 'C2.1')
        self.assertEqual(len(page.context['rows']), 26)
        self.assertEqual(len(self.client.get(url, {'q':'ภาครัฐ'}).context['rows']), 4)
        market = self.client.get(url, {'category':'markets'})
        self.assertEqual([r['code'] for r in market.context['rows']], ['M1','M2'])
        self.assertEqual([r['forms'] for r in market.context['rows']], [[],[]])
        self.assertEqual(self.client.post(url).status_code, 405)
        self.assertEqual(self.client.get(reverse('group-register', args=[self.foreign.pk])).status_code, 403)
        self.assertEqual(before, list(RespondentGroup.objects.values_list('code','label')))
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_choices_preserve_keys_and_reject_other_form_or_scope(self):
        with override('th'):
            question = QuestionForm(version=self.version, question=self.question)
            self.assertEqual([c[0] for c in question.fields['group_codes'].choices], self.version.group_codes)
            self.assertIn('C2 · นิสิตระดับบัณฑิตศึกษา', dict(question.fields['group_codes'].choices)['C2.1'])
            form = SurveyRoundForm(scope=self.scope)
            choices = dict(form.fields['group_code'].choices)
            self.assertIn('C2.1', choices)
            self.assertNotIn('CO-1', choices)
            for code in ['M1','M2','S2','SP1','C2']:
                self.assertNotIn(code, choices)
            wrong = SurveyRoundForm({'bundle':str(self.bundle.pk), 'group_code':'C4.1'}, scope=self.scope)
            wrong.is_valid()
            self.assertIn('group_code', wrong.errors)
            right = SurveyRoundForm({'bundle':str(self.bundle.pk), 'group_code':'C2.1'}, scope=self.scope)
            right.is_valid()
            self.assertNotIn('group_code', right.errors)

    def test_rendered_pages_and_optional_preview(self):
        pages = {}
        for name, route, args, params in [
            ('groups', 'group-register', [self.scope.pk], {}),
            ('groups-c5', 'group-register', [self.scope.pk], {'q':'C5'}),
            ('catalog', 'portal-catalog-detail', [self.scope.pk,self.version.pk], {}),
            ('question', 'portal-catalog-question-edit', [self.scope.pk,self.version.pk,self.question.pk], {}),
            ('survey-round', 'survey-new', [self.scope.pk], {})]:
            page = self.client.get(reverse(route, args=args), params)
            self.assertEqual(page.status_code, 200, name)
            self.assertContains(page, 'นิสิตชาวไทย' if name != 'groups-c5' else 'ผู้รับบริการวิชาการ')
            pages[name] = page.content.decode()
        self.client.cookies['django_language'] = 'en'
        page = self.client.get(reverse('group-register', args=[self.scope.pk]))
        self.assertContains(page, 'Graduate students')
        pages['groups-en'] = page.content.decode()
        folder = os.environ.get('NEXORA_QA_PREVIEW_DIR')
        if folder:
            dest = Path(folder); dest.mkdir(parents=True, exist_ok=True)
            for name, content in pages.items():
                content = re.sub(r'<input[^>]*name="csrfmiddlewaretoken"[^>]*>', '', content)
                content = content.replace('/static/', 'assets/')
                (dest / (name+'.html')).write_text(content, encoding='utf-8')
