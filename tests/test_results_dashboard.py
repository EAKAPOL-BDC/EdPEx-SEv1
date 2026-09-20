import csv,io
from unittest.mock import patch
from django.test import TestCase,Client
from django.urls import reverse
from django.core.exceptions import ValidationError
from apps.accounts.models import AccessScope
from apps.calculations.dashboard import csv_cell
from apps.calculations.review import decide_results
from tests.test_operator_web import OperatorResultTests

class ResultsDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        OperatorResultTests.setUpTestData.__func__(cls)
    make_run=OperatorResultTests.make_run
    request_review=OperatorResultTests.request_review
    def setUp(self):
        self.client=Client();self.client.force_login(self.f.reviewer)
    def url(self,name,run=None,scope=None):
        return reverse(name,args=[(scope or self.f.scope).pk]+([run] if run else []))
    def approve(self,key='dashboard'):
        run=self.make_run(key);review=self.request_review(run)
        decide_results(self.f.reviewer,run_id=run,outcome='approved',reason='Synthetic checked',reviewed_token=review['review_token'])
        return run
    def test_approved_only_and_suppressed_csv(self):
        run=self.make_run()
        self.assertNotContains(self.client.get(self.url('insights-list')),self.url('insights-detail',run))
        self.assertEqual(self.client.get(self.url('insights-detail',run)).status_code,404)
        review=self.request_review(run)
        decide_results(self.f.reviewer,run_id=run,outcome='approved',reason='Checked',reviewed_token=review['review_token'])
        self.assertContains(self.client.get(self.url('insights-list')),self.url('insights-detail',run))
        detail=self.client.get(self.url('insights-detail',run))
        self.assertEqual(detail.status_code,200)
        self.assertNotContains(detail,'PRIVATE-EXAMPLE-DO-NOT-DISCLOSE')
        response=self.client.get(self.url('insights-export',run))
        self.assertIn('no-store',response['Cache-Control'])
        rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row['status'],'suppressed')
            for key in ['value','numerator','denominator']:self.assertEqual(row[key],'')
        self.assertNotIn('PRIVATE-EXAMPLE-DO-NOT-DISCLOSE',response.content.decode())
    def test_permission_scope_and_filter(self):
        run=self.approve()
        self.assertNotContains(self.client.get(self.url('insights-list'),{'form':'F03'}),self.url('insights-detail',run))
        other=AccessScope.objects.create(organization=self.f.scope.organization,code='OTHER',name='Other')
        self.assertEqual(self.client.get(self.url('insights-export',run,other)).status_code,403)
        self.client.force_login(self.f.staff)
        self.assertEqual(self.client.get(self.url('insights-list')).status_code,403)
        self.assertEqual(self.client.get(self.url('insights-export',run)).status_code,403)
    def test_superseded_result_not_exportable_and_invalid_fails_closed(self):
        old=self.approve('old');new=self.approve('new')
        self.assertEqual(self.client.get(self.url('insights-export',old)).status_code,404)
        page=self.client.get(self.url('insights-list'))
        self.assertNotContains(page,self.url('insights-detail',old))
        self.assertContains(page,self.url('insights-detail',new))
        with patch('apps.calculations.dashboard.review_summary',side_effect=ValidationError('Synthetic failure')):
            self.assertEqual(self.client.get(self.url('insights-export',new)).status_code,409)
    def test_csv_formula_injection_is_escaped(self):
        for value in ['=1+1',' +CMD','-1','@SUM(A1)','\t=1']:
            self.assertTrue(csv_cell(value).startswith("'"))
        self.assertEqual(csv_cell(0),'0')
        self.assertEqual(csv_cell(None),'')

class DashboardPresentationTests(TestCase):
    def test_disclosure_and_scale(self):
        from apps.calculations.dashboard import presentation_rows
        from types import SimpleNamespace
        with patch('apps.calculations.dashboard.Indicator') as indicators, patch('apps.calculations.dashboard.Question') as questions:
            indicators.objects.filter.return_value.values_list.return_value=[('x','Synthetic indicator')]
            questions.objects.filter.return_value.values_list.return_value=[]
            base={'indicator':'x','group':'ST1','dimension':'','unit':'percent','status':'computed'}
            rows=presentation_rows([dict(base,value=0),dict(base,value=75.25),dict(base,value=999),dict(base,value=88,status='suppressed')],SimpleNamespace(),1)
            self.assertEqual(rows[0]['display_value'],'0')
            self.assertTrue(rows[0]['chart'])
            self.assertEqual(rows[1]['chart_value'],'75.25')
            self.assertFalse(rows[2]['chart'])
            self.assertFalse(rows[3]['has_value'])
            self.assertFalse(rows[3]['chart'])
            self.assertEqual(rows[1]['label'],'Synthetic indicator')
