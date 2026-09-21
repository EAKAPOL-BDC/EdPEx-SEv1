"""Real scoped lists: summaries span pages, filters persist, reads do not mutate."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from apps.accounts.models import AccessScope
from apps.auditlog.models import AuditEvent
from apps.rounds.models import CollectionRound, RoundInstrument, Calendar, ReportingPeriod
from apps.rounds.services import approve_period
from tests.m2_fixtures import scenario, grant


class CollectionPresentationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.f = scenario(status='open')
        grant(cls.f.actor, cls.f.scope, ['source.manage'], 'collection-source')
        original = cls.f.round
        for number in range(21):
            r = CollectionRound.objects.create(scope=cls.f.scope, period=original.period,
                code=f'Batch {number:02d}', owner=cls.f.actor, open_at=original.open_at,
                due_at=original.due_at, close_at=original.close_at)
            for code in ['F05', 'F06']:
                source = cls.f.round_instruments[code]
                RoundInstrument.objects.create(collection_round=r, instrument_version=source.instrument_version,
                    translation_bundle=source.translation_bundle, context='primary')
        cls.other = AccessScope.objects.create(organization=cls.f.org, code='PRIVATE', name='Foreign scope')
        grant(cls.f.actor, cls.other, ['calendar.manage'], 'foreign-calendar')
        calendar = Calendar.objects.create(scope=cls.other, code='FY', label='Other', calendar_type='calendar')
        p = original.period
        period = ReportingPeriod.objects.create(calendar=calendar, code='PRIVATE', reporting_year_be=p.reporting_year_be,
            start_date=p.start_date, end_date=p.end_date)
        period = approve_period(cls.f.actor, period, reason='Test')
        CollectionRound.objects.create(scope=cls.other, period=period, code='Batch HIDDEN', owner=cls.f.actor,
            open_at=original.open_at, due_at=original.due_at, close_at=original.close_at)
        cls.source_only = get_user_model().objects.create_user(username='source-only')
        grant(cls.source_only, cls.f.scope, ['source.manage'], 'source-only')

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.f.actor)

    def url(self, route, scope=None):
        return reverse(route, args=[(scope or self.f.scope).pk])

    def test_totals_cover_all_pages_and_scope_for_rounds_and_bindings(self):
        before = (AuditEvent.objects.count(), CollectionRound.objects.count(), RoundInstrument.objects.count())
        for route in ['round-list', 'operator-list', 'activity-list']:
            first = self.client.get(self.url(route))
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.context['listing']['total'], 22)
            self.assertEqual({x['key']:x['count'] for x in first.context['listing']['breakdown']}, {'draft':21,'open':1})
            self.assertEqual(len(first.context['listing']['page']), 20)
            second = self.client.get(self.url(route), {'page':2})
            self.assertEqual(second.context['listing']['total'], 22)
            self.assertEqual(len(second.context['listing']['page']), 2)
            self.assertNotContains(first, 'Batch HIDDEN')
            self.assertEqual(self.client.get(self.url(route, self.other)).status_code, 403)
        self.assertEqual(before, (AuditEvent.objects.count(), CollectionRound.objects.count(), RoundInstrument.objects.count()))

    def test_search_status_pagination_empty_and_escaped_input(self):
        for route in ['round-list', 'operator-list', 'activity-list', 'survey-list']:
            expected = 0 if route == 'survey-list' else 21
            response = self.client.get(self.url(route), {'q':'Batch', 'status':'draft'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['listing']['total'], expected)
            if expected:
                self.assertContains(response, 'q=Batch&amp;status=draft&amp;page=2')
                self.assertEqual(self.client.get(self.url(route), {'q':'Batch','status':'draft','page':2}).context['listing']['total'],21)
            response = self.client.get(self.url(route), {'q':'<script>alert(1)</script>'})
            self.assertEqual(response.context['listing']['total'], 0)
            self.assertNotContains(response, '<script>alert(1)</script>')
            self.assertContains(response, '&lt;script&gt;')
        response = self.client.get(self.url('round-list'), {'status':'invalid', 'page':'bad'})
        self.assertEqual(response.context['listing']['status'], '')
        self.assertEqual(response.context['listing']['total'], 22)

    def test_f05_actions_match_permissions_and_english_is_readable(self):
        self.client.force_login(self.source_only)
        response = self.client.get(self.url('activity-list'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.url('activity-new'))
        self.assertNotContains(response, self.url('round-list'))
        self.assertEqual(self.client.get(self.url('round-list')).status_code, 403)
        self.client.post('/language/', {'language':'en'})
        response = self.client.get(self.url('activity-list'))
        self.assertContains(response, 'Staff development activities')
        self.assertContains(response, 'all pages')
        self.assertContains(response, 'Open')


class PersonalCollectionRoutes(TestCase):
    @classmethod
    def setUpTestData(cls):
        from tests.test_self_assessments import self_scenario
        cls.f=self_scenario()
    def test_assigned_card_keeps_ownership_and_opens_existing_answers(self):
        client=Client();client.force_login(self.f.staff)
        response=client.get(reverse('self-assessment-list'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,self.f.round.code)
        self.assertContains(response,reverse('self-assessment-detail',args=[self.f.assignment]))
        self.assertContains(response,'สถานะรอบ')
        client.force_login(self.f.reviewer)
        response=client.get(reverse('self-assessment-list'))
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,reverse('self-assessment-detail',args=[self.f.assignment]))
        self.assertContains(response,'ยังไม่มีแบบประเมินที่ได้รับมอบหมาย')
