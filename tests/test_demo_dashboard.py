from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch
from django.test import TestCase, Client, SimpleTestCase
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from apps.accounts.models import Organization,AccessScope,Membership,Role,RoleAssignment
from apps.calculations.models import DemoDataset,DemoSeries,CalculationRun,ResultDecision
from apps.calculations.demo_data import build_series
from apps.calculations.demo_dashboard import comparison_cards
from apps.calculations.catalog import Catalog
from apps.calculations.codec import replay_input
from apps.surveys.models import AnonymousResponse

class DemoGenerationTests(SimpleTestCase):
    def test_complete_deterministic_and_replayable(self):
        rows=build_series();self.assertEqual(rows,build_series())
        catalog=Catalog()
        self.assertEqual({r['indicator_code'] for r in rows},set(catalog.indicators))
        self.assertEqual(len(rows),198)
        for row in rows:
            self.assertEqual(row['result'],replay_input(row['source']))
            self.assertEqual(row['result']['status'],'computed')
        for code,indicator in catalog.indicators.items():
            self.assertEqual({r['group_code'] for r in rows if r['indicator_code']==code},set(indicator['binding']['group_codes']))
    def test_comparison_never_pools_context_or_unit(self):
        rows=[SimpleNamespace(**r) for r in build_series() if r['indicator_code']=='7.3-38']
        cards=comparison_cards(rows);self.assertEqual(len(cards),1);self.assertTrue(cards[0]['comparable'])
        rows[1].context_key='another-period';self.assertEqual(len(comparison_cards(rows)),2)
        rows[1].context_key=rows[0].context_key;rows[1].formula_version='other'
        self.assertEqual(len(comparison_cards(rows)),2)

class DemoDatabaseTests(TestCase):
    def setUp(self):
        self.org=Organization.objects.create(name='Synthetic demo test')
        self.scope=AccessScope.objects.create(organization=self.org,code='DEMO',name='Demo test')
        self.other=AccessScope.objects.create(organization=self.org,code='OTHER',name='Other')
        self.user=get_user_model().objects.create_user('demo-admin',password='synthetic')
        member=Membership.objects.create(user=self.user,organization=self.org)
        role=Role.objects.create(code='demo-test-role',permissions=['source.manage','calculation.run','result.review','calculation.validate'])
        RoleAssignment.objects.create(membership=member,scope=self.scope,role=role)
        self.client=Client();self.client.force_login(self.user)
    def seed(self,apply=True):
        call_command('seed_demo_results',scope_id=self.scope.pk,username=self.user.username,apply=apply,stdout=StringIO())
    def test_seed_isolated_audited_and_idempotent(self):
        from apps.auditlog.models import AuditEvent
        before=(CalculationRun.objects.count(),ResultDecision.objects.count(),AnonymousResponse.objects.count())
        self.seed(False);self.assertFalse(DemoDataset.objects.exists())
        self.seed();self.seed()
        self.assertEqual(DemoDataset.objects.count(),1);self.assertEqual(DemoSeries.objects.count(),198)
        self.assertEqual(before,(CalculationRun.objects.count(),ResultDecision.objects.count(),AnonymousResponse.objects.count()))
        self.assertEqual(AuditEvent.objects.filter(action='demo.dataset_created').count(),1)
        DemoSeries.objects.filter(pk=DemoSeries.objects.first().pk).update(indicator_label='changed')
        with self.assertRaises(CommandError):self.seed()
    def test_seed_rolls_back_and_requires_scope_permission(self):
        with patch('apps.calculations.management.commands.seed_demo_results.DemoSeries.objects.bulk_create',side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):self.seed()
        self.assertFalse(DemoDataset.objects.exists())
        with self.assertRaises(PermissionDenied):
            call_command('seed_demo_results',scope_id=self.other.pk,username=self.user.username,apply=True,stdout=StringIO())
    def test_dashboard_export_filters_and_empty_state(self):
        url=reverse('insights-demo',args=[self.scope.pk])
        self.assertContains(self.client.get(url),'ยังไม่ได้สร้างชุดข้อมูลสาธิต')
        self.seed()
        response=self.client.get(url,{'q':'7.3-38'})
        self.assertContains(response,'meter');self.assertContains(response,'ST1');self.assertContains(response,'ST2')
        self.assertContains(response,'ข้อมูลสมมุติ')
        self.assertNotContains(response,'DEMO-ST1-01')
        self.assertEqual(response.context['matched_count'],1)
        filtered=self.client.get(url,{'form':'F03','group':'ST2','q':'7.3-38'})
        self.assertEqual(len(filtered.context['cards'][0]['bars']),1)
        export=self.client.get(reverse('insights-demo-export',args=[self.scope.pk]))
        import csv,io
        rows=list(csv.DictReader(io.StringIO(export.content.decode('utf-8-sig'))))
        self.assertEqual(len(rows),198);self.assertEqual({r['data_kind'] for r in rows},{'SYNTHETIC_DEMO_NOT_ACTUAL'})
        self.assertIn('no-store',export['Cache-Control'])
        self.assertEqual(self.client.get(reverse('insights-demo',args=[self.other.pk])).status_code,403)
        self.assertEqual(self.client.get(reverse('insights-list',args=[self.scope.pk])).context['decisions'].paginator.count,0)
