from django.test import TestCase,Client,override_settings
from django.core.exceptions import ValidationError,PermissionDenied
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.governance import refresh
from apps.governance.models import WorkspaceRefresh
from apps.rounds.models import CollectionRound
from apps.surveys.models import AnonymousResponse
from apps.calculations.models import CalculationRun,ResultDecision
from apps.calculations.services import validate_run
from tests import test_governance as fixture

@override_settings(SURVEY_ALLOW_TEST_HTTP=True)
class WorkspaceRefreshTests(TestCase):
    @classmethod
    def setUpTestData(cls):fixture.GovernanceTests.setUpTestData.__func__(cls)
    round=fixture.GovernanceTests.round

    def test_plan_is_read_only_permission_checked_and_stale_safe(self):
        binding=self.round('F06');p=refresh.plan(self.actor,self.scope)
        self.assertTrue(CollectionRound.objects.filter(pk=binding.collection_round_id).exists())
        with self.assertRaises(PermissionDenied):refresh.plan(self.actor,self.foreign)
        with self.assertRaises(ValidationError):refresh.execute(self.actor,self.scope,expected_hash=p['hash'],confirmation='RESET OTHER',reason='test',seed=lambda *a:{})
        self.round('F06','ST2')
        with self.assertRaises(ValidationError):refresh.execute(self.actor,self.scope,expected_hash=p['hash'],confirmation='RESET NEW',reason='test',seed=lambda *a:{})
        self.assertEqual(WorkspaceRefresh.objects.count(),0)

    def test_seed_failure_rolls_back_deleted_rows(self):
        binding=self.round('F06');p=refresh.plan(self.actor,self.scope)
        def broken(*a):raise ValidationError('Simulated failure')
        with self.assertRaises(ValidationError):refresh.execute(self.actor,self.scope,expected_hash=p['hash'],confirmation='RESET NEW',reason='test',seed=broken)
        self.assertTrue(CollectionRound.objects.filter(pk=binding.collection_round_id).exists());self.assertEqual(WorkspaceRefresh.objects.count(),0)

    def test_full_replacement_preserves_accounts_and_creates_current_workflows(self):
        old=self.round('F06');user_count=get_user_model().objects.count()
        p=refresh.plan(self.actor,self.scope)
        done=refresh.execute(self.actor,self.scope,expected_hash=p['hash'],confirmation='RESET NEW',reason='User requested replacement')
        self.assertEqual(done.status,'completed');self.assertFalse(CollectionRound.objects.filter(pk=old.collection_round_id).exists())
        self.assertEqual(get_user_model().objects.count(),user_count)
        rounds=CollectionRound.objects.filter(scope=self.scope)
        self.assertEqual(set(rounds.filter(data_kind='synthetic').values_list('period__reporting_year_be',flat=True)),{2565,2566,2567})
        pending=rounds.filter(period__reporting_year_be=2568)
        self.assertTrue(pending.exists());self.assertFalse(pending.exclude(status='draft').exists());self.assertFalse(pending.filter(schedule_confirmed=True).exists())
        self.assertFalse(AnonymousResponse.objects.filter(binding__collection_round__in=pending).exists())
        self.assertFalse(CalculationRun.objects.filter(collection_round__in=pending).exists())
        self.assertEqual(ResultDecision.objects.count(),rounds.filter(data_kind='synthetic').count())
        for run in CalculationRun.objects.select_related('collection_round').all():validate_run(self.actor,run_id=run.pk)
        from apps.rounds.services import transition_round
        with self.assertRaises(ValidationError):transition_round(self.actor,pending.first(),'ready')
        from apps.catalog.models import InstrumentVersion
        self.assertTrue(InstrumentVersion.objects.filter(source_metadata__synthetic_only=True,status='published').exists())
        self.assertFalse(InstrumentVersion.objects.filter(pk__in=done.summary['created']['real_form_versions'].values(),source_metadata__synthetic_only=True).exists())
        # Optional local fixture export for PostgreSQL trigger integration checks.
        import os,json
        if os.environ.get('NEXORA_REFRESH_EXPORT'):
            from django.apps import apps
            from django.db.models import JSONField
            from pathlib import Path
            fixture_rows=[]
            for model in apps.get_models(include_auto_created=True):
                fixture_rows.append({'table':model._meta.db_table,'json_fields':[f.column for f in model._meta.local_fields if isinstance(f,JSONField)],
                    'rows':[{f.column:getattr(obj,f.attname) for f in model._meta.local_fields} for obj in model._base_manager.all()]})
            Path(os.environ['NEXORA_REFRESH_EXPORT']).write_text(json.dumps(fixture_rows,default=str),encoding='utf-8')

        # Every portal entry uses the current anonymous path; simulation copies
        # stay off real-data selectors, and all 2568 drafts are editable.
        client=Client();client.force_login(self.actor)
        for route in ['workspace','portal-catalog','assessment-preview-list','indicator-alignment','survey-list','round-list','workspace-refresh','annual-policy','insights-list','visualization-home','quality-home','backoffice-home']:
            url=reverse(route,args=[] if route=='workspace' else [self.scope.pk])
            response=client.get(url)
            self.assertEqual(response.status_code,200,(route,response.status_code))
            self.assertNotContains(response,reverse('activity-list',args=[self.scope.pk]))
            self.assertNotContains(response,reverse('operator-list',args=[self.scope.pk]))
        from apps.catalog.current import visible_versions
        self.assertEqual(visible_versions(self.scope).count(),6)
        from apps.surveys.forms import SurveyRoundForm
        self.assertFalse(SurveyRoundForm(scope=self.scope).fields['bundle'].queryset.filter(instrument_version__source_metadata__synthetic_only=True).exists())
        from apps.surveys.operator import PROFILE_FIELDS
        for r in pending:
            selected=r.round_instruments.get()
            response=client.get(reverse('survey-collection',args=[self.scope.pk,selected.pk]))
            self.assertEqual(response.status_code,200)
            data={k:getattr(r,k) for k in ('code','period','owner','open_at','due_at','close_at','privacy_notice')}
            data.update(bundle=selected.translation_bundle,context_checked=True,reason='Confirm real schedule',**{k:getattr(selected.survey_profile,k) for k in PROFILE_FIELDS})
            form=SurveyRoundForm(data={k:getattr(v,'pk',v) for k,v in data.items()},initial=data,scope=self.scope,editing=True)
            self.assertTrue(form.is_valid(),form.errors)
        run=CalculationRun.objects.filter(stored_source__round_instrument__instrument_version__instrument__code='F05').first()
        response=client.get(reverse('insights-export',args=[self.scope.pk,run.pk]))
        self.assertEqual(response.status_code,200)
        self.assertIn('data_kind',response.content.decode());self.assertIn('synthetic',response.content.decode())
        from apps.calculations.quality import audit_quality
        from apps.rounds.models import ReportingPeriod
        codes=set()
        for period in ReportingPeriod.objects.filter(calendar__scope=self.scope,reporting_year_be=2567):
            report=audit_quality(self.actor,self.scope,period)
            self.assertEqual(report['invalid_sets'],0)
            codes.update(row['code'] for row in report['rows'] if row['status'] in {'available','restricted'})
        self.assertEqual(len(codes),63)
