"""User-defined quantitative F05: complete annual answers, zero inclusion and history."""
from copy import deepcopy
from decimal import Decimal
from django.test import TestCase,SimpleTestCase,Client,override_settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.urls import reverse
from apps.governance import f05_contract as legacy,f05_quantitative as current
from apps.governance.f05_reporting import pooled_result
from apps.surveys.schema import normalize,respondent_schema
from apps.surveys.forms import ResponseForm,SurveyRoundForm
from apps.surveys import services
from apps.surveys.models import AnonymousResponse,AnonymousSession
from apps.surveys.calculations import calculate
from apps.calculations.services import validate_run,replay_snapshot,encode_snapshot_spec,snapshot_engine
from apps.calculations.types import FormulaSpec,CalculationInputError
from apps.calculations.models import CalculationRun
from apps.calculations.review import request_review,review_summary
from apps.rounds.services import transition_round
from tests import test_governance as governance_tests
from tests.test_governance import publish


def answers(hours='0',yes=()):
    return {qid:{'status':'answered','value':hours if qid=='F05-Y01' else 'yes' if qid in yes else 'no'} for qid in current.QUESTIONS}


def payload(code,rows,eligible=10):
    key,qids,_=current.MAP[code]
    return {'contract':current.CONTRACT,'indicator':code,'eligible_count':eligible,
        'spec':encode_snapshot_spec(FormulaSpec(key,tuple(qids),current.VERSION,current.VERSION)),
        'rows':[{'unit_id':str(i),'answers':a} for i,a in enumerate(rows)]}


class QuantitativeFormulaTests(SimpleTestCase):
    def test_average_uses_every_respondent_including_zero_not_nonrespondents(self):
        r=replay_snapshot(payload('7.3-44',[answers('0'),answers('6'),answers('12'),answers('18'),answers('24')]))
        self.assertEqual(Decimal(r['value']),Decimal(12));self.assertEqual(r['numerator'],'60');self.assertEqual(r['denominator'],'5')
        self.assertEqual(r['counts']['not_responded'],5)
        self.assertIsNone(replay_snapshot(payload('7.3-44',[]))['value'])
        with self.assertRaises(CalculationInputError):replay_snapshot(payload('7.3-44',[{'F05-Y01':{'status':'skipped'}}]))

    def test_category_any_counts_each_person_once_and_keeps_breakdowns(self):
        rows=[answers('2',('F05-Y04','F05-Y05','F05-Y06')),answers('2',('F05-Y05',)),answers()]
        r=replay_snapshot(payload('7.3-47',rows));self.assertEqual(r['numerator'],'2');self.assertEqual(r['denominator'],'3')
        self.assertEqual([r['breakdown'][c]['numerator'] for c in ['T47S','T47H','T47E']],['1','2','1'])
        for code in ['7.3-45','7.3-46','7.3-48','7.3-49']:
            qid=current.MAP[code][1][0]
            r=replay_snapshot(payload(code,[answers('2',(qid,)),answers()]))
            self.assertEqual(r['value'],'50.0');self.assertEqual(r['denominator'],'2')

    def test_pool_is_weighted_and_refuses_hidden_duplicate_or_overlapping_groups(self):
        def row(group,num,den,run):return dict(form='F05',form_version=current.VERSION,group=group,numerator=str(num),denominator=str(den),run_id=run,unit='hours_per_person',suffix='ชั่วโมง/คน',has_value=True,status='computed')
        rows=[row('ST1',600,20,'a'),row('ST2',0,10,'b')];rosters={'a':set(range(20)),'b':set(range(20,30))}
        result=pooled_result(rows,rosters);self.assertEqual(result['value'],'20');self.assertEqual(result['denominator'],'30')
        self.assertFalse(pooled_result(rows+rows[:1],rosters)['available'])
        self.assertFalse(pooled_result(rows,{'a':{1},'b':{1}})['available'])
        rows[1]['status']='suppressed';self.assertFalse(pooled_result(rows,rosters)['available'])


@override_settings(SURVEY_ALLOW_TEST_HTTP=True)
class QuantitativeIntakeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        governance_tests.GovernanceTests.setUpTestData.__func__(cls)
        cls.legacy_bundle=cls.bundles['F05']
        cls.version=current.prepare(cls.actor,cls.scope)
        cls.bundles['F05']=publish(cls.actor,cls.version)
    round=governance_tests.GovernanceTests.round

    def test_published_version_is_eight_numeric_items_and_old_schema_is_preserved(self):
        self.assertEqual(current.prepare(self.actor,self.scope).pk,self.version.pk)
        self.assertEqual(self.version.questions.count(),8)
        self.assertFalse(self.version.questions.filter(answer_type='text').exists())
        self.assertTrue(self.legacy_bundle.instrument_version.questions.filter(question_id='F05-Y09').exists())
        choices=SurveyRoundForm(scope=self.scope).fields['bundle'].queryset
        self.assertIn(self.bundles['F05'],choices);self.assertNotIn(self.legacy_bundle,choices)
        selected=self.round('F05');current.validate_version(selected.instrument_version)
        self.assertEqual(set(current.MAP),set(self.version.bindings.values_list('indicator__code',flat=True)))

    def test_submission_requires_all_answers_zero_is_explicit_and_hours_are_consistent(self):
        profile=self.round('F05').survey_profile
        normalized,status=normalize(profile,answers(),submitting=True);self.assertEqual(status,'complete')
        normalize(profile,answers('0',('F05-Y08',)),submitting=True)  # Study visits do not imply training hours.
        for bad in [{}, {**answers(),'F05-Y09':{'status':'answered','value':'personal details'}},answers('0',('F05-Y02',)),answers('-1'),answers('NaN'),answers('1.001')]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):normalize(profile,bad,submitting=True)
        bad=answers();bad['F05-Y03']={'status':'skipped'}
        with self.assertRaises(ValidationError):normalize(profile,bad,submitting=True)
        self.assertEqual(normalize(profile,{},submitting=False)[1],'partial')

    def test_http_form_no_evidence_text_or_skip_and_failed_submit_does_not_spend_invitation(self):
        selected=self.round('F05');profile=selected.survey_profile
        for locale in ['th','en']:
            schema=respondent_schema(profile,{},locale);self.assertTrue(schema['quantitative_f05']);self.assertEqual(len(schema['questions']),8)
            form=ResponseForm(profile,{},0,locale)
            for qid in current.QUESTIONS:
                if qid!='F05-Y01':self.assertEqual({v for v,_ in form.fields[qid].choices},{'value:yes','value:no'})
        member=selected.collection_round.population_snapshot.members.first()
        token=services.exchange(services.issue(self.actor,selected.pk,member.pk))
        client=Client();client.cookies['nexora_survey_session']=token
        page=client.get('/survey/answer/');self.assertEqual(page.status_code,200)
        self.assertNotContains(page,'type="file"');self.assertNotContains(page,'<textarea');self.assertNotContains(page,'value="draft"')
        response=client.post('/survey/answer/',{'revision':'0','action':'submit','confirm':'on','F05-Y01':'0'})
        self.assertEqual(response.status_code,422);self.assertEqual(AnonymousResponse.objects.count(),0)
        self.assertEqual(AnonymousSession.objects.get(secret_hash=services.token_hash(token)).draft,{})
        data={'revision':'0','action':'submit','confirm':'on',**{qid:('0' if qid=='F05-Y01' else 'value:no') for qid in current.QUESTIONS}}
        self.assertEqual(client.post('/survey/answer/',data).status_code,200)
        self.assertEqual(AnonymousResponse.objects.count(),1);self.assertFalse(AnonymousSession.objects.filter(secret_hash=services.token_hash(token)).exists())

    def test_full_calculation_replay_review_and_legacy_engine_remain_valid(self):
        self.bundles['F05']=self.legacy_bundle
        old=self.round('F05','ST2')
        for member in old.collection_round.population_snapshot.members.all():
            token=services.exchange(services.issue(self.actor,old.pk,member.pk));services.save(token,answers('12.50'),0,submit=True)
        transition_round(self.actor,old.collection_round,'closed',reason='Synthetic old collection finished')
        old_receipt=calculate(self.actor,old.pk,timezone.now(),'old-f05')
        old_run=CalculationRun.objects.get(pk=old_receipt['run_id']);old_hash=old_run.engine_hash
        self.version.refresh_from_db()
        self.bundles['F05']=self.version.translation_bundles.select_related('instrument_version__instrument').get()
        new=self.round('F05','ST1')
        for hours,member in zip(['0','6','12','18','24'],new.collection_round.population_snapshot.members.all()):
            token=services.exchange(services.issue(self.actor,new.pk,member.pk));services.save(token,answers(hours),0,submit=True)
        transition_round(self.actor,new.collection_round,'closed',reason='Synthetic quantitative collection finished')
        receipt=calculate(self.actor,new.pk,timezone.now(),'new-f05')
        run=CalculationRun.objects.get(pk=receipt['run_id']);self.assertEqual(validate_run(self.actor,run_id=run.pk)['status'],'verified')
        self.assertEqual(validate_run(self.actor,run_id=old_run.pk)['status'],'verified');self.assertNotEqual(old_hash,run.engine_hash)
        result=run.results.get(indicator_code='7.3-44').payload;self.assertEqual(result['value'],'12');self.assertEqual(result['denominator'],'5')
        request_review(self.actor,run_id=run.pk,reason='Synthetic quantitative review')
        packet=review_summary(self.actor,run_id=run.pk)
        row=next(r for r in packet['results'] if r['indicator']=='7.3-47');self.assertEqual(len(row['breakdown']),3)
        self.assertFalse(any('PRIVATE' in str(s.payload) for s in run.inputs.all()))
        self.assertEqual(snapshot_engine({legacy.CONTRACT})['hash'],old_hash)

    def test_approved_two_group_totals_render_and_export_only_disclosed_values(self):
        from django.contrib.auth import get_user_model
        from tests.m2_fixtures import grant
        from apps.accounts.models import ALLOWED_PERMISSIONS
        from apps.calculations.review import decide_results
        from apps.calculations.comparisons import approved_cards
        reviewer=get_user_model().objects.create_user(username='quantitative-reviewer')
        grant(reviewer,self.scope,sorted(ALLOWED_PERMISSIONS),'quantitative-reviewer-role')
        selecteds=[]
        for group,hours in [('ST1','20'),('ST2','0')]:
            selected=self.round('F05',group)
            for member in selected.collection_round.population_snapshot.members.all():
                secret=services.exchange(services.issue(self.actor,selected.pk,member.pk))
                services.save(secret,answers(hours),0,submit=True)
            transition_round(self.actor,selected.collection_round,'closed',reason='Synthetic finished')
            selecteds.append(selected)
        cutoff=timezone.now();runs=[]
        for selected in selecteds:
            receipt=calculate(self.actor,selected.pk,cutoff,'quantitative-'+selected.survey_profile.group_code)
            run=CalculationRun.objects.get(pk=receipt['run_id']);runs.append(run)
            review=request_review(self.actor,run_id=run.pk,reason='Synthetic review')
            decide_results(reviewer,run_id=run.pk,outcome='approved',reason='Synthetic independent approval',reviewed_token=review['review_token'])
        cards,errors=approved_cards(reviewer,self.scope,self.period,form='F05')
        self.assertEqual(errors,0)
        item=next(c for c in cards if c['indicator']=='7.3-44')
        self.assertTrue(item['combined']['available'],item['combined']);self.assertEqual(item['combined']['value'],'10')
        self.assertEqual(item['combined']['denominator'],'10')
        client=Client();client.force_login(reviewer)
        comparison=client.get(reverse('insights-compare',args=[self.scope.pk]),{'period':str(self.period.pk)})
        self.assertEqual(comparison.status_code,200);self.assertContains(comparison,'ST1 และ ST2');self.assertNotContains(comparison,'PRIVATE-')
        for run in runs:
            result=client.get(reverse('insights-detail',args=[self.scope.pk,run.pk]));self.assertEqual(result.status_code,200)
            exported=client.get(reverse('insights-export',args=[self.scope.pk,run.pk]))
            self.assertEqual(exported.status_code,200);self.assertContains(exported,'T47S');self.assertNotContains(exported,'PRIVATE-')
            import csv,io
            csv_rows=list(csv.reader(io.StringIO(exported.content.decode('utf-8-sig'))))
            self.assertTrue(all(len(row)==len(csv_rows[0]) for row in csv_rows))
