"""Read-only display and real version-binding regressions."""
import json
import os
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import TestCase, SimpleTestCase
from django.urls import reverse
from apps.accounts.models import Organization, AccessScope, Role, Membership, RoleAssignment
from apps.catalog.models import Instrument, InstrumentVersion, Question, FormulaVersion, Indicator, IndicatorBinding, BindingQuestion
from apps.catalog.presentation import F05_TITLE, F06_TITLE, instrument_title


class DisplaySafetyTests(SimpleTestCase):
    def test_title_aliases_preserve_custom_text(self):
        self.assertEqual(instrument_title('F05 ทะเบียนการพัฒนาบุคลากร'), F05_TITLE)
        self.assertEqual(instrument_title('F06 การประเมินสมรรถนะที่จำเป็น ทักษะ ขีดความสามารถ และค่านิยมของบุคลากรวิทยาลัยการศึกษา'), F06_TITLE)
        self.assertEqual(instrument_title('F05 แบบฟอร์มเฉพาะหน่วยงาน'), 'F05 แบบฟอร์มเฉพาะหน่วยงาน')

    def test_badges_escape_unknown_codes_and_labels(self):
        result = Template('{% load portal_ui %}{% group_badge code fallback %}').render(Context({'code':'<script>', 'fallback':'<img onerror=alert(1)>'}))
        self.assertNotIn('<script>', result)
        self.assertNotIn('<img', result)
        self.assertIn('&lt;img', result)
        self.assertIn('data-group-code="&lt;script&gt;"', result)


class CatalogPresentationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        org = Organization.objects.create(name='Synthetic presentation QA')
        cls.scope = AccessScope.objects.create(organization=org, code='DISPLAY', name='Synthetic only')
        cls.other = AccessScope.objects.create(organization=org, code='OTHER', name='Other scope')
        cls.actor = get_user_model().objects.create_user(username='presentation-reader')
        role = Role.objects.create(code='presentation-reader', permissions=['catalog.read'])
        RoleAssignment.objects.create(membership=Membership.objects.create(user=cls.actor, organization=org), role=role, scope=cls.scope)
        cls.version = InstrumentVersion.objects.create(instrument=Instrument.objects.create(scope=cls.scope, code='F02'), version='test', title_th='F02 synthetic QA', assessment_method='survey', group_codes=['C4.1','C5.1'])
        cls.question = Question.objects.create(version=cls.version, question_id='F02-S01', text_th='คำถามตัวอย่างที่เชื่อมหลายตัวชี้วัด', answer_type='integer_scale', group_codes=['C4.1','C5.1'])
        cls.unbound = Question.objects.create(version=cls.version, question_id='F02-O01', text_th='ข้อเสนอแนะ', answer_type='text')
        formula = FormulaVersion.objects.create(scope=cls.scope, key='SAT_TOP2', version='test', definition_th='Synthetic only', source_hash='a'*64)
        for code in ['7.2-13','7.2-17']:
            indicator = Indicator.objects.create(scope=cls.scope, code=code, original_name_status='synthetic', display_name_th='Synthetic indicator', display_name_status='synthetic', unit='percent', direction='increase')
            binding = IndicatorBinding.objects.create(version=cls.version, indicator=indicator, formula=formula)
            BindingQuestion.objects.create(binding=binding, question=cls.question)
        cls.f05 = InstrumentVersion.objects.create(instrument=Instrument.objects.create(scope=cls.scope, code='F05'), version='test', title_th='F05 ทะเบียนการพัฒนาบุคลากร', assessment_method='verified_activity')
        cls.f06 = InstrumentVersion.objects.create(instrument=Instrument.objects.create(scope=cls.scope, code='F06'), version='test', title_th='F06 การประเมินสมรรถนะที่จำเป็น ทักษะ ขีดความสามารถ และค่านิยมของบุคลากรวิทยาลัยการศึกษา', assessment_method='self_report')

    def setUp(self):
        self.client.force_login(self.actor)

    def test_multiple_bindings_search_unbound_and_scope(self):
        url = reverse('portal-catalog-detail', args=[self.scope.pk, self.version.pk])
        page = self.client.get(url)
        self.assertContains(page, 'class="nx-indicator-code"', count=2)
        self.assertContains(page, '7.2-13')
        self.assertContains(page, '7.2-17')
        self.assertContains(page, 'ไม่มีตัวชี้วัดเชื่อมโยงโดยตรง')
        filtered = self.client.get(url, {'q':'7.2-17'})
        self.assertEqual([q.pk for q in filtered.context['questions']], [self.question.pk])
        self.assertEqual(self.client.get(reverse('portal-catalog-detail', args=[self.other.pk,self.version.pk])).status_code,403)
        self.assertEqual(IndicatorBinding.objects.count(),2)
        self.save_preview('question-indicators', page)
        self.save_preview('groups-colors', self.client.get(reverse('group-register', args=[self.scope.pk])))

    def test_current_names_search_without_rewriting_source(self):
        url = reverse('portal-catalog', args=[self.scope.pk])
        page = self.client.get(url)
        self.assertContains(page,F05_TITLE)
        self.assertContains(page,F06_TITLE)
        filtered=self.client.get(url,{'q':'แบบสำรวจข้อมูลการพัฒนาตนเอง'})
        self.assertContains(filtered,F05_TITLE)
        self.assertNotContains(filtered,F06_TITLE)
        self.f05.refresh_from_db()
        self.assertEqual(self.f05.title_th,'F05 ทะเบียนการพัฒนาบุคลากร')
        self.save_preview('form-names',page)

    def save_preview(self, name, page):
        folder=os.environ.get('NEXORA_QA_PREVIEW_DIR')
        if folder:
            dest=Path(folder);dest.mkdir(parents=True,exist_ok=True)
            (dest/(name+'.html')).write_text(page.content.decode().replace('/static/','assets/'),encoding='utf-8')
