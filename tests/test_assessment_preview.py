from django.test import TestCase, Client
from django.urls import reverse
from apps.catalog.seeding import seed_catalog
from apps.catalog.models import InstrumentVersion
from apps.catalog.preview import build_preview
from apps.accounts.models import Organization, AccessScope
from django.contrib.auth import get_user_model
from tests.m2_fixtures import grant
from apps.rounds.models import CollectionRound
from apps.surveys.models import Invitation, AnonymousResponse
from apps.selfassessments.models import SelfAssessmentAssignment, SelfAssessmentRevision

class AssessmentPreviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor=get_user_model().objects.create_user(username='preview-admin')
        cls.other=get_user_model().objects.create_user(username='other-admin')
        org=Organization.objects.create(name='Synthetic preview')
        cls.scope=AccessScope.objects.create(organization=org,code='PREVIEW',name='Synthetic preview')
        cls.foreign=AccessScope.objects.create(organization=org,code='OTHER',name='Other')
        grant(cls.actor,cls.scope,['catalog.read','catalog.edit'],'preview-editor')
        grant(cls.other,cls.foreign,['catalog.read'],'other-reader')
        cls.versions=seed_catalog(cls.scope,cls.actor)['instrument_versions']
    def setUp(self):
        self.client=Client();self.client.force_login(self.actor)
    def url(self,code,group):
        return reverse('assessment-preview',args=[self.scope.pk,self.versions[code].pk,group])
    def test_all_forms_and_groups_and_no_writes(self):
        models=[CollectionRound,Invitation,AnonymousResponse,SelfAssessmentAssignment,SelfAssessmentRevision]
        before=[m.objects.count() for m in models]
        response=self.client.get(reverse('assessment-preview-list',args=[self.scope.pk]))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['group_count'],17)
        for code,v in self.versions.items():
            for group in v.group_codes:
                response=self.client.get(self.url(code,group))
                self.assertEqual(response.status_code,200,(code,group,response.content[:200]))
                self.assertContains(response,'data-section-form')
                self.assertNotContains(response,'name="action" value="submit"')
                for section in response.context['question_sections']:
                    for item in section['items']:
                        self.assertIn(group,v.questions.get(question_id=item['id']).group_codes)
        self.assertEqual(before,[m.objects.count() for m in models])
    def test_scope_group_and_post_rejected(self):
        url=self.url('F03','ST1')
        self.assertEqual(self.client.post(url,{'F03-H01':'10'}).status_code,405)
        self.assertEqual(self.client.get(self.url('F03','C1')).status_code,404)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code,403)
        self.assertEqual(self.client.get(reverse('assessment-preview',args=[self.foreign.pk,self.versions['F03'].pk,'ST1'])).status_code,404)
    def test_conditional_questions_roles_and_translation_fallback(self):
        response=self.client.get(self.url('F03','ST1')+'?lang=en')
        self.assertTrue(response.context['source_fallback'])
        self.assertContains(response,'F03-D01-CAUSE')
        self.assertContains(response,'Shown when')
        response=self.client.get(self.url('F04','ST1')+'?role=DE')
        ids=[i['id'] for s in response.context['question_sections'] for i in s['items']]
        self.assertIn('F04-DE01',ids);self.assertNotIn('F04-VD01',ids)
        self.assertEqual(self.client.get(self.url('F04','ST1')+'?role=invalid').status_code,404)
    def test_preview_uses_current_catalog_labels(self):
        q=self.versions['F03'].questions.get(question_id='F03-H01')
        q.text_th='คำถามใหม่สำหรับทดสอบ';q.save()
        response=self.client.get(self.url('F03','ST1'))
        self.assertContains(response,'คำถามใหม่สำหรับทดสอบ')
