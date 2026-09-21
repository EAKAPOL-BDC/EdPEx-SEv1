import csv
import io
from html.parser import HTMLParser
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, SimpleTestCase
from django.urls import reverse

from apps.calculations.models import CalculationRun, ResultDecision, DemoSeries
from apps.calculations.visualization import chart_card, actual_cards, visual_summary
from django.http import QueryDict
from tests.test_backoffice import BackofficeTests
from tests.test_results_dashboard import ResultsDashboardTests


class ChartProjectionTests(SimpleTestCase):
    def test_reference_summary_counts_entries_without_averaging_scores(self):
        cards = [chart_card(dict(form='F01', indicator='A'), [
            dict(group='C1', unit='percent', value='0'),
            dict(group='C2', unit='percent', value=None)]),
            chart_card(dict(form='F03', indicator='B'), [
            dict(group='ST1', unit='score_5', value='4'),
            dict(group='ST2', unit='score_5', value='5')])]
        result = visual_summary(cards, QueryDict('source=actual&focus=999&page=4'))
        forms = {f['code']: f for f in result['form_summaries']}
        self.assertEqual((forms['F01']['visible'], forms['F01']['total'], forms['F01']['coverage']), (1,2,50))
        self.assertEqual(forms['F03']['coverage'], 100)
        self.assertIsNone(forms['F06']['coverage'])
        self.assertEqual(result['focus_card']['indicator'], 'B')
        self.assertEqual(result['focus_params'], [('source','actual')])
        self.assertNotIn('focus=', forms['F01']['filters'])
        self.assertNotIn('page=', forms['F01']['filters'])
        self.assertEqual(visual_summary(cards, QueryDict('focus=0'))['focus_card']['indicator'], 'A')

    def test_reference_summary_empty_filters_and_invalid_selection(self):
        summary = visual_summary([], QueryDict('source=demo&form=F04&focus=bad'))
        self.assertIsNone(summary['focus_card'])
        self.assertEqual(len(summary['form_summaries']), 1)
        self.assertEqual(summary['form_summaries'][0]['code'], 'F04')
        self.assertIsNone(summary['form_summaries'][0]['coverage'])

    def test_zero_missing_scale_and_difference(self):
        rows = [dict(group='ST1', unit='percent', value='0'), dict(group='ST2', unit='percent', value='80'),
                dict(group='ST3', unit='percent', value=None)]
        card = chart_card({}, rows)
        self.assertEqual(rows[0]['width'], '0.000')
        self.assertIsNone(rows[2]['width'])
        self.assertEqual(card['difference'], '80.00')
        self.assertEqual(card['difference_unit'], 'จุดร้อยละ')
        self.assertEqual(card['visible_count'], 2)
        self.assertEqual(chart_card({}, [dict(group='ST1',unit='hours_per_person',value='12.2')])['maximum'],13)
        self.assertIsNone(chart_card({}, [dict(group='ST1',unit='score_5',value='6')])['rows'][0]['width'])
        self.assertFalse(chart_card({}, [dict(group='ST1',unit='percent',value='30'),dict(group='ST1',unit='percent',value='40')])['comparable'])

    def test_hidden_payload_not_projected_to_chart(self):
        card = dict(indicator='7.3-38',label='Test',dimension='',context='same',cutoff=None,form='F03',version='v1',rows=[
            dict(group='ST1',group_label='Test',unit='score_10',value='9.87654321',has_value=False,
                 status='suppressed',round='r1',run_id='1',numerator='PRIVATE-NUMERATOR')])
        with patch('apps.calculations.visualization.approved_cards', return_value=([card],0)):
            cards, _ = actual_cards(None, None, None)
        self.assertNotIn('9.87654321', str(cards))
        self.assertNotIn('PRIVATE-NUMERATOR', str(cards))
        self.assertIsNone(cards[0]['rows'][0]['value'])


class VisualizationDemoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        BackofficeTests.setUpTestData.__func__(cls)
        call_command('seed_demo_results',scope_id=cls.scope.pk,username=cls.admin.username,apply=True,stdout=io.StringIO())

    def setUp(self):
        self.client.force_login(self.admin)

    def url(self, name='home', scope=None):
        return reverse('visualization-'+name, args=[(scope or self.scope).pk])

    def test_modes_filters_native_labels_and_no_writes(self):
        before = (CalculationRun.objects.count(), ResultDecision.objects.count(), DemoSeries.objects.count())
        for mode in ['home','endlessloop','finereport']:
            page = self.client.get(self.url(mode), {'source':'demo','q':'7.3-38'})
            self.assertEqual(page.status_code,200)
            self.assertEqual(page.context['indicator_count'],1)
            self.assertEqual(page.context['group_count'],2)
            self.assertEqual(page.context['comparison_count'],1)
            self.assertContains(page,'ST1');self.assertContains(page,'ST2')
            self.assertContains(page,'ข้อมูลสาธิต · ไม่ใช่ผลจริง')
            self.assertContains(page,'ไม่ได้เชื่อมต่อซอฟต์แวร์ FineReport')
            self.assertIn('no-store',page['Cache-Control'])
        filtered = self.client.get(self.url('finereport'),{'source':'demo','group':'ST2','form':'F03','q':'7.3-38'})
        self.assertEqual(filtered.context['comparison_count'],0)
        self.assertEqual(filtered.context['group_count'],1)
        self.assertEqual(before,(CalculationRun.objects.count(),ResultDecision.objects.count(),DemoSeries.objects.count()))

    def test_reference_boards_and_indicator_selection(self):
        loop = self.client.get(self.url('endlessloop'), {'source':'demo'})
        self.assertContains(loop, 'loop-arc-value')
        self.assertEqual(sum(f['total'] for f in loop.context['form_summaries']), 198)
        report = self.client.get(self.url('finereport'), {'source':'demo','q':'7.3-38'})
        self.assertContains(report, 'fine-nested-rings')
        self.assertContains(report, 'fine-gauges')
        self.assertContains(report, 'viz-theme-report')
        self.assertEqual(report.context['focus_card']['indicator'], '7.3-38')
        self.assertEqual({r['group'] for r in report.context['focus_card']['rows']}, {'ST1','ST2'})
        self.assertEqual(sum(f['total'] for f in report.context['form_summaries']), 2)

    def test_csv_all_filtered_rows_and_formula_escaping(self):
        DemoSeries.objects.filter(dataset__scope=self.scope,indicator_code='7.3-38').update(indicator_label='=1+1',dimension_label='=1+1')
        response=self.client.get(self.url('export'),{'source':'demo'})
        rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual(len(rows),198)
        self.assertEqual({r['data_kind'] for r in rows},{'SYNTHETIC_DEMO_NOT_ACTUAL'})
        self.assertEqual({r['label'] for r in rows if r['indicator']=='7.3-38'},{'ระดับคะแนนความสุขของบุคลากร'})
        self.assertEqual({r['dimension'] for r in rows if r['indicator']=='7.3-38'},{"'=1+1"})
        self.assertIn('no-store',response['Cache-Control'])
        response=self.client.get(self.url('export'),{'source':'demo','form':'F03','group':'ST2','q':'7.3-38'})
        rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual(len(rows),1)

    def test_corrupt_demo_values_are_not_rendered_or_exported(self):
        row=DemoSeries.objects.filter(dataset__scope=self.scope).first()
        payload=dict(row.result);payload['value']='98765.4321'
        DemoSeries.objects.filter(pk=row.pk).update(result=payload)
        for name in ['finereport','endlessloop']:
            response=self.client.get(self.url(name),{'source':'demo'})
            self.assertEqual(response.context['error_count'],1)
            self.assertNotContains(response,'98765.4321')
        self.assertEqual(self.client.get(self.url('export'),{'source':'demo'}).status_code,409)
        self.assertEqual(self.client.get(reverse('insights-demo-export',args=[self.scope.pk])).status_code,409)

    def test_permissions_scope_read_only_and_unknown_source(self):
        for mode in ['home','endlessloop','finereport','export']:
            self.assertEqual(self.client.get(self.url(mode,self.other),{'source':'demo'}).status_code,403)
            self.assertEqual(self.client.post(self.url(mode),{}).status_code,405)
        self.assertEqual(self.client.get(self.url(),{'source':'untrusted'}).status_code,400)
        self.client.force_login(self.reader)
        for mode in ['home','endlessloop','finereport','export']:
            self.assertEqual(self.client.get(self.url(mode),{'source':'demo'}).status_code,403)
        self.assertNotContains(self.client.get(reverse('portal-catalog',args=[self.scope.pk])),self.url())

    def test_pagination_empty_state_and_sidebar_structure(self):
        response=self.client.get(self.url('finereport'),{'source':'demo'})
        self.assertEqual(len(response.context['cards']),8)
        self.assertTrue(response.context['cards'].has_next())
        self.assertContains(self.client.get(self.url(),{'q':'no-match'}),'ยังไม่มีข้อมูลที่ตรงกับตัวกรอง')
        self.assertEqual(self.client.get(self.url(),{'source':'actual'}).context['series_count'],0)
        class Parser(HTMLParser):
            def __init__(self):super().__init__();self.tags=[];self.locations={};self.styles=[]
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if tag=='a':self.locations.setdefault(attrs.get('href'),[]).append(tuple(self.tags))
                if tag=='link' and 'visualization.css' in attrs.get('href',''):self.styles.append(tuple(self.tags))
                if tag not in ['meta','link','img','input','br','hr']:self.tags.append(tag)
            def handle_endtag(self,tag):
                if tag in self.tags:self.tags=self.tags[:len(self.tags)-1-self.tags[::-1].index(tag)]
        p=Parser();p.feed(response.content.decode())
        self.assertTrue(any('aside' in location and 'nav' in location for location in p.locations[self.url()]))
        self.assertTrue(all('head' in location for location in p.styles))
        self.assertEqual(len(p.styles),1)


class VisualizationActualTests(TestCase):
    @classmethod
    def setUpTestData(cls):ResultsDashboardTests.setUpTestData.__func__(cls)
    make_run=ResultsDashboardTests.make_run
    request_review=ResultsDashboardTests.request_review
    approve=ResultsDashboardTests.approve
    def setUp(self):self.client.force_login(self.f.reviewer)
    def url(self,name):return reverse('visualization-'+name,args=[self.f.scope.pk])

    def test_approval_suppression_export_and_invalid_replay(self):
        run=self.make_run('not-approved')
        self.assertEqual(self.client.get(self.url('home')).context['series_count'],0)
        approved=self.approve('approved')
        for mode in ['home','endlessloop','finereport']:
            response=self.client.get(self.url(mode))
            self.assertEqual(response.status_code,200)
            self.assertGreater(response.context['series_count'],0)
            self.assertEqual(response.context['visible_count'],0)
            self.assertEqual(response.context['comparison_count'],0)
            self.assertNotContains(response,'PRIVATE-EXAMPLE-DO-NOT-DISCLOSE')
            self.assertNotContains(response,'staff-A')
        response=self.client.get(self.url('export'))
        rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
        self.assertTrue(rows)
        self.assertEqual({r['status'] for r in rows},{'suppressed'})
        self.assertEqual({r['value'] for r in rows},{''})
        self.assertEqual({r['run_id'] for r in rows},{str(approved)})
        self.assertEqual(self.client.get(self.url('home'),{'period':'bad'}).context['series_count'],0)
        self.assertEqual(self.client.get(self.url('home'),{'form':'F03'}).context['series_count'],0)
        with patch('apps.calculations.comparisons.review_summary',side_effect=ValidationError('Private failure')):
            response=self.client.get(self.url('home'))
            self.assertEqual(response.context['error_count'],1)
            self.assertEqual(response.context['series_count'],0)
            self.assertNotContains(response,'Private failure')
            self.assertEqual(self.client.get(self.url('export')).status_code,409)

    def test_superseded_approval_not_shown(self):
        old=self.approve('old-viz');new=self.approve('new-viz')
        rows=list(csv.DictReader(io.StringIO(self.client.get(self.url('export')).content.decode('utf-8-sig'))))
        self.assertEqual({r['run_id'] for r in rows},{str(new)})
