import io,json
from django.test import TestCase,SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.core.exceptions import ValidationError,PermissionDenied
from django.core.management import call_command
from django.core.management.base import OutputWrapper
from django.db import connection
from django.utils import timezone
from apps.accounts.models import ALLOWED_PERMISSIONS
from apps.catalog.services import clone_instrument_version,approve_translation,translation_review_snapshot,publish_bundle
from apps.catalog.management_services import prepare_translations
from apps.auditlog.models import AuditEvent
from apps.governance.models import WorkspaceRefresh
from apps.governance.simulation_review import review_simulation_bundle
from apps.governance.refresh_progress import RefreshProgress
from tests.test_m1_catalog import CatalogFixtures


class SimulationReviewTests(CatalogFixtures,TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from tests.m2_fixtures import grant
        grant(cls.actor,cls.scope,sorted(ALLOWED_PERMISSIONS),'simulation-review-test')

    def copies(self):
        source,_,original_bundle=self.instrument()
        run=WorkspaceRefresh.objects.create(scope=self.scope,actor=self.actor,plan_hash='a'*64,manifest={},revision='test',reason='Simulation test')
        if connection.vendor=='postgresql':
            with connection.cursor() as cursor:
                cursor.execute('SELECT txid_current()');run.database_transaction=cursor.fetchone()[0]
            run.save(update_fields=['database_transaction'])
        versions=[]
        for name in ['test-sim-a','test-sim-b']:
            v=clone_instrument_version(self.actor,source,name)
            v.source_metadata={'synthetic_only':True,'simulation_source':str(source.pk)};v.save()
            versions.append(prepare_translations(self.actor,v.pk))
        return original_bundle,*versions

    def test_same_pair_results_and_audit_with_fewer_database_round_trips(self):
        source,ordinary,optimized=self.copies()
        with CaptureQueriesContext(connection) as previous:
            for e in ordinary.translations.all():
                e.source_metadata={**e.source_metadata,'review_mode':'simulation_only'};e.save()
                approve_translation(self.actor,e,reviewed_token=translation_review_snapshot(self.actor,e)['reviewed_token'])
        before=AuditEvent.objects.filter(action='catalog.translation_approved').count()
        progress=[]
        with CaptureQueriesContext(connection) as current:
            review_simulation_bundle(self.actor,optimized,progress.append)
        fields=('content_key','locale','text','status','source_hash','reviewed_by_id','source_metadata')
        self.assertEqual(list(ordinary.translations.order_by('content_key','locale').values_list(*fields)),list(optimized.translations.order_by('content_key','locale').values_list(*fields)))
        self.assertEqual(AuditEvent.objects.filter(action='catalog.translation_approved').count()-before,optimized.translations.count())
        self.assertFalse(source.translations.filter(status='approved').exists())
        self.assertTrue(progress)
        self.assertLess(len(current),len(previous)*0.7)
        print(f'SIMULATION_REVIEW_QUERIES previous={len(previous)} current={len(current)} pairs={optimized.translations.count()}')
        publish_bundle(self.actor,optimized)

    def test_real_forms_and_other_scope_cannot_use_simulation_review(self):
        original,_,copy=self.copies()
        with self.assertRaises(ValidationError):review_simulation_bundle(self.actor,original)
        with self.assertRaises(PermissionDenied):review_simulation_bundle(self.other,copy)
        self.assertFalse(original.translations.filter(status='approved').exists())

    def test_blank_stale_hash_and_changed_thai_rollback_whole_batch(self):
        _,_,bundle=self.copies()
        for fields in ({'text':''},{'status':'stale'},{'source_hash':'0'*64},{'text':'Changed Thai'}):
            with self.subTest(fields=fields):
                entry=bundle.translations.filter(locale='th').last()
                old={key:getattr(entry,key) for key in fields}
                for key,value in fields.items():setattr(entry,key,value)
                entry.save()
                with self.assertRaises(ValidationError):review_simulation_bundle(self.actor,bundle)
                self.assertFalse(bundle.translations.filter(status='approved').exists())
                entry.refresh_from_db()
                for key,value in old.items():setattr(entry,key,value)
                entry.save()

    def test_completed_refresh_cannot_auto_review_and_status_is_read_only(self):
        _,_,bundle=self.copies()
        run=WorkspaceRefresh.objects.get(scope=self.scope)
        run.status='completed';run.completed_at=timezone.now();run.save(update_fields=['status','completed_at'])
        with self.assertRaises(ValidationError):review_simulation_bundle(self.actor,bundle)
        # A separate status lookup performs no cleanup, migration or seeding.
        out=io.StringIO()
        with CaptureQueriesContext(connection) as queries:
            call_command('refresh_workspace',actor=self.actor.username,scope=str(self.scope.pk),status=True,stdout=out)
        self.assertEqual(json.loads(out.getvalue())['status'],'completed')
        self.assertFalse(any(q['sql'].lstrip().split()[0].upper() in {'INSERT','UPDATE','DELETE','ALTER','CREATE'} for q in queries))


class ProgressTests(SimpleTestCase):
    def test_progress_measures_completed_calls_without_sql_or_answers(self):
        out=io.StringIO();p=RefreshProgress(OutputWrapper(out))
        p('F01: ตรวจคำแปล 25/100')
        p.query(lambda *a:1,'SECRET SQL',['PRIVATE ANSWER'],False,{})
        p.report()
        self.assertEqual(p.completed,1)
        self.assertIn('25/100',out.getvalue());self.assertIn('จบแล้ว 1',out.getvalue())
        self.assertNotIn('SECRET',out.getvalue());self.assertNotIn('PRIVATE',out.getvalue())
        def broken(*a):raise ValueError('failed')
        with self.assertRaises(ValueError):p.query(broken,'SECRET',[],False,{})
        self.assertEqual(p.completed,1);self.assertIsNone(p.query_started)
