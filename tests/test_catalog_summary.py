"""Summary accuracy across scopes, versions, filters and pagination."""
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import InstrumentVersion, Question
from tests.test_m1_catalog import CatalogFixtures


class CatalogSummaryTests(CatalogFixtures, TestCase):
    def setUp(self):
        first, _, _ = self.instrument('F01')
        Question.objects.create(version=first, question_id='F01-INACTIVE',
            text_th='Inactive field', answer_type='text', active=False)
        for index in range(2, 14):
            version = InstrumentVersion.objects.create(instrument=first.instrument,
                version=f'test-{index}', title_th='Special form' if index == 13 else 'แบบฟอร์ม',
                assessment_method='survey')
            Question.objects.create(version=version, question_id='F01-ITEM',
                text_th='คำถาม', answer_type='text')
        published, _, bundle = self.instrument('F02')
        self.publish(published, bundle)
        retired, _, bundle = self.instrument('F03')
        retired, _ = self.publish(retired, bundle)
        retired.status = 'retired'
        retired.save()
        self.instrument('F01', scope=self.other_scope)
        self.url = reverse('portal-catalog', args=[self.scope.pk])
        self.client.force_login(self.actor)

    def test_counts_do_not_multiply_with_questions_or_change_between_pages(self):
        expected = dict(total=15, forms=3, published=1, draft=13, retired=1, questions=16)
        for page, length in [(1, 12), (2, 3)]:
            response = self.client.get(self.url, {'page': page})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['summary'], expected)
            self.assertEqual(len(response.context['page']), length)
            self.assertEqual(sum(item['count'] for item in response.context['status_breakdown']), 15)
        foreign_url = reverse('portal-catalog', args=[self.other_scope.pk])
        self.assertEqual(self.client.get(foreign_url).status_code, 403)

    def test_filters_and_empty_chart_describe_only_matching_versions(self):
        response = self.client.get(self.url, {'status': 'published', 'code': 'F02'})
        self.assertEqual(response.context['summary'], dict(
            total=1, forms=1, published=1, draft=0, retired=0, questions=1))
        response = self.client.get(self.url, {'q': 'Special', 'code': 'F01'})
        self.assertEqual(response.context['summary'], dict(
            total=1, forms=1, published=0, draft=1, retired=0, questions=1))
        response = self.client.get(self.url, {'q': '<script>missing</script>'})
        self.assertTrue(all(value == 0 for value in response.context['summary'].values()))
        self.assertContains(response, 'ยังไม่มีข้อมูลสำหรับกราฟ')
        self.assertNotContains(response, '<script>missing</script>')
        self.assertNotContains(response, 'cl-status-track')
        self.client.cookies['django_language'] = 'en'
        response = self.client.get(self.url, {'status': 'published'})
        self.assertContains(response, 'Form version status')
        self.assertContains(response, 'Published')
        self.assertContains(response, 'Draft')
        self.assertContains(response, 'Retired')
