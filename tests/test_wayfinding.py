"""Regression checks for parent destinations, workflow gates and guide anchors."""
import json
from html.parser import HTMLParser
from types import SimpleNamespace as Obj
from unittest.mock import patch
from uuid import uuid4

from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.wayfinding import page_navigation
from apps.manuals.views import catalog
from tests import test_backoffice


class NavigationHTML(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.ids = set()
        self.anchors = []
        self.breadcrumbs = 0
        self.page_navigation = 0
        self.current_crumbs = 0
        self.in_breadcrumbs = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            self.ids.add(attrs['id'])
        if tag == 'a':
            self.anchors.append(attrs.get('href', ''))
        if tag == 'nav' and attrs.get('class') == 'nx-breadcrumbs':
            self.breadcrumbs += 1
            self.in_breadcrumbs = True
        if tag == 'nav' and attrs.get('class') == 'nx-page-navigation':
            self.page_navigation += 1
        if self.in_breadcrumbs and attrs.get('aria-current') == 'page':
            self.current_crumbs += 1

    def handle_endtag(self, tag):
        if tag == 'nav':
            self.in_breadcrumbs = False


class WorkflowDestinationTests(SimpleTestCase):
    def nav(self, route, *, grants=(), code='F06', status='ready', **extra):
        scope = Obj(pk=uuid4())
        selected = Obj(pk=uuid4(), collection_round=Obj(code='Synthetic round', status=status),
                       instrument_version=Obj(instrument=Obj(code=code)))
        request = RequestFactory().get('/?next=https://example.invalid/', HTTP_REFERER='https://example.invalid/')
        request.user = Obj(is_authenticated=True)
        request.resolver_match = Obj(url_name=route)
        context = dict(request=request, scope=scope, selected=selected, **extra)
        with patch('apps.accounts.wayfinding.can_access', side_effect=lambda user, action, scope: action in grants):
            return page_navigation(context), scope, selected

    def test_f05_result_returns_to_activity_collection_never_survey(self):
        nav, scope, selected = self.nav('operator-run', code='F05', grants=['source.manage'])
        self.assertEqual(nav['back']['url'], reverse('activity-collection', args=[scope.pk, selected.pk]))
        self.assertFalse(any('/surveys/' in (x['url'] or '') for x in nav['crumbs']))
        self.assertIsNone(nav['crumbs'][-1]['url'])

    def test_f06_assignment_returns_to_roster_and_skips_inaccessible_ancestors(self):
        nav, scope, selected = self.nav('operator-assign', grants=['selfassessment.assign', 'population.manage'])
        self.assertEqual(nav['back']['url'], reverse('operator-roster', args=[scope.pk, selected.pk]))
        denied, _, _ = self.nav('operator-assign')
        self.assertEqual(denied['back']['url'], reverse('workspace'))
        self.assertFalse(any(x['url'] for x in denied['crumbs'][1:]))

    def test_next_step_requires_both_workflow_state_and_permissions(self):
        for status in ['draft', 'open']:
            nav, _, _ = self.nav('operator-collection', status=status,
                                 grants=['selfassessment.assign', 'population.manage', 'calculation.run'])
            self.assertIsNone(nav['next'])
        nav, scope, selected = self.nav('operator-collection', grants=['selfassessment.assign', 'population.manage'])
        self.assertEqual(nav['next']['url'], reverse('operator-roster', args=[scope.pk, selected.pk]))
        nav, _, _ = self.nav('operator-collection', grants=['selfassessment.assign'])
        self.assertIsNone(nav['next'])
        nav, scope, selected = self.nav('operator-collection', status='closed', grants=['calculation.run'])
        self.assertEqual(nav['next']['url'], reverse('operator-calculate', args=[scope.pk, selected.pk]))

    def test_foreign_or_error_context_does_not_use_url_to_build_scope_links(self):
        request = RequestFactory().get('/?next=https://example.invalid/')
        request.user = Obj(is_authenticated=True)
        request.resolver_match = Obj(url_name='round-detail', kwargs={'scope_id': uuid4(), 'round_id': uuid4()})
        nav = page_navigation({'request': request})
        self.assertEqual(nav['crumbs'], [])
        self.assertEqual(nav['back']['url'], reverse('workspace'))


class WayfindingWebTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        test_backoffice.BackofficeTests.setUpTestData.__func__(cls)

    def test_directories_have_one_current_breadcrumb_and_contextual_footer(self):
        self.client.force_login(self.admin)
        for route, args in [('portal-catalog', [self.scope.pk]), ('round-list', [self.scope.pk]),
            ('operator-list', [self.scope.pk]), ('survey-list', [self.scope.pk]),
            ('activity-list', [self.scope.pk]), ('backoffice-settings', [self.scope.pk]),
            ('quality-home', [self.scope.pk]), ('manuals-home', [])]:
            response = self.client.get(reverse(route, args=args))
            self.assertEqual(response.status_code, 200, route)
            parsed = NavigationHTML(response.content.decode())
            self.assertEqual((parsed.breadcrumbs, parsed.current_crumbs, parsed.page_navigation), (1, 1, 1), route)
            self.assertContains(response, 'portal/wayfinding.css')
        home = self.client.get(reverse('workspace')).content.decode()
        sidebar = home.split('id="workspace-navigation"', 1)[1].split('</aside>', 1)[0]
        self.assertIn('หน้าหลัก', sidebar)
        self.assertNotIn('พื้นที่ทำงาน', sidebar)

    def test_period_cancel_preserves_origin_on_get_and_invalid_post(self):
        self.client.force_login(self.admin)
        for origin, parent in [('survey', 'survey-new'), ('f06', 'round-new')]:
            url = reverse('round-period-new', args=[self.scope.pk]) + '?return_to=' + origin
            for response in [self.client.get(url), self.client.post(url, {'return_to': origin})]:
                html = response.content.decode()
                expected = reverse(parent, args=[self.scope.pk])
                self.assertIn('href="'+expected+'">ยกเลิก', html)
                self.assertIn('href="'+expected+'" rel="up"', html)
        bad = self.client.get(reverse('round-period-new', args=[self.scope.pk])+'?return_to=https://example.invalid/')
        self.assertNotContains(bad, 'example.invalid')

    def test_manual_chapters_have_resolvable_anchors_and_do_not_mutate_pdf_source(self):
        data, _ = catalog()
        before = json.dumps(data, sort_keys=True)
        self.client.force_login(self.admin)
        for manual in data['manuals']:
            response = self.client.get(reverse('manuals-detail', args=[manual['slug']]))
            self.assertEqual(response.status_code, 200)
            parser = NavigationHTML(response.content.decode())
            self.assertEqual(parser.breadcrumbs, 1)
            self.assertIn('manual-contents', parser.ids)
            for href in parser.anchors:
                if href.startswith('#'):
                    self.assertIn(href[1:], parser.ids, (manual['slug'], href))
            self.assertContains(response, 'class="manual-chapter-navigation"', count=len(manual['sections']))
        self.assertEqual(json.dumps(catalog()[0], sort_keys=True), before)

    def test_public_survey_breadcrumb_is_usable_without_account(self):
        response = self.client.get(reverse('survey-access'), secure=True)
        self.assertEqual(response.status_code, 200)
        parsed = NavigationHTML(response.content.decode())
        self.assertEqual(parsed.breadcrumbs, 1)
        self.assertIn(reverse('home'), parsed.anchors)
        self.assertNotIn(reverse('workspace'), parsed.anchors)
