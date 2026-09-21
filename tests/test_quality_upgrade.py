import csv
import io
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError, ImproperlyConfigured
from django.db import DatabaseError
from django.test import TestCase, SimpleTestCase, Client
from django.urls import reverse
from apps.calculations.comparisons import compatibility_key
from apps.calculations.dashboard import presentation_rows
from apps.calculations.demo_dashboard import formatted
from apps.accounts.models import AccessScope
from apps.surveys.models import AccessThrottle
import tests.test_results_dashboard as results_fixture


class AccuracyUpgradeTests(SimpleTestCase):
    def test_rounding_agrees_across_dashboard_and_visualization(self):
        with patch('apps.calculations.dashboard.Indicator') as indicators, patch('apps.calculations.dashboard.Question') as questions:
            indicators.objects.filter.return_value.values_list.return_value=[]
            questions.objects.filter.return_value.values_list.return_value=[]
            row=dict(indicator='x',group='ST1',dimension='',unit='score_5',status='computed',value='2.345')
            result=presentation_rows([row],None,None)[0]
            self.assertEqual(result['display_value'],'2.35')
            self.assertEqual(result['display_value'],formatted('2.345'))
    def test_cutoff_requires_same_instant_not_same_day(self):
        run=NS(stored_source=NS(round_instrument=NS(instrument_version_id='v1',context='same')),collection_round=NS(period_id='p1'),cutoff=datetime(2026,9,1,8,tzinfo=timezone.utc))
        row=dict(indicator='x',dimension='',unit='percent',method='survey',formula={'key':'same'})
        key=compatibility_key(run,row)
        run.cutoff+=timedelta(hours=1)
        self.assertNotEqual(key,compatibility_key(run,row))
        run.cutoff-=timedelta(hours=1)
        run.cutoff=run.cutoff.astimezone(timezone(timedelta(hours=7)))
        self.assertEqual(key,compatibility_key(run,row))
    def test_reference_exactly_matches_63_catalog_codes(self):
        reference=json.loads((settings.BASE_DIR/'catalog/indicator_reference.json').read_text())
        catalog=json.loads((settings.BASE_DIR/'catalog/indicators.json').read_text())
        self.assertEqual(len(reference['indicators']),63)
        self.assertEqual({x['code'] for x in reference['indicators']},{x['code'] for x in catalog})
        self.assertTrue(all(x['pdf_pages'] for x in reference['indicators']))
    def test_weak_passwords_rejected(self):
        for password in ['abc','1234567890123456','password123']:
            with self.assertRaises(ValidationError):validate_password(password)
        validate_password('Orchid-Window-River-492!')


class SecurityUpgradeTests(TestCase):
    def test_login_throttle_shared_database_and_expiry(self):
        for _ in range(12):
            self.assertEqual(self.client.post(reverse('login'),{'username':'unknown-account','password':'bad'}).status_code,200)
        response=self.client.post(reverse('login'),{'username':'unknown-account','password':'bad'})
        self.assertEqual(response.status_code,429)
        self.assertEqual(response['Retry-After'],'600')
        self.assertNotContains(response,'unknown-account',status_code=429)
        self.assertEqual(AccessThrottle.objects.count(),2)
        self.assertFalse(any('unknown-account' in r.key for r in AccessThrottle.objects.all()))
        from django.utils import timezone as tz
        AccessThrottle.objects.update(window_start=tz.now()-timedelta(minutes=11))
        self.assertEqual(self.client.post(reverse('login'),{'username':'unknown-account','password':'bad'}).status_code,200)
    def test_admin_login_uses_same_guard_and_failed_dependency_is_generic(self):
        with patch('apps.surveys.services.throttle',return_value=False) as throttle:
            response=self.client.post('/admin/login/',{'username':'x','password':'secret'})
            self.assertEqual(response.status_code,429)
            self.assertEqual(throttle.call_count, 1)
        with patch('apps.surveys.services.throttle',side_effect=DatabaseError('DO-NOT-EXPOSE-CONNECTION')):
            response=self.client.post(reverse('login'),{'username':'x','password':'secret'})
            self.assertEqual(response.status_code,503)
            self.assertNotContains(response,'DO-NOT-EXPOSE-CONNECTION',status_code=503)
    def test_health_probes_and_security_headers(self):
        self.assertEqual(self.client.get('/health/live/').json(),{'status':'ok'})
        self.assertEqual(self.client.get('/health/ready/').status_code,200)
        self.assertEqual(self.client.post('/health/ready/').status_code,405)
        with patch('apps.accounts.security.connection.cursor',side_effect=DatabaseError('PRIVATE')):
            r=self.client.get('/health/ready/')
            self.assertEqual(r.status_code,503);self.assertEqual(r.json(),{'status':'unavailable'})
        user=get_user_model().objects.create_user(username='header-test')
        self.client.force_login(user)
        r=self.client.get(reverse('workspace'))
        self.assertIn('no-store',r['Cache-Control'])
        self.assertIn("script-src 'self'",r['Content-Security-Policy'])
        self.assertEqual(r['X-Frame-Options'],'DENY')
        self.assertContains(r,'portal/design-system.css')
        self.assertContains(r,'portal/usability.js')
    def test_csrf_is_checked_before_login_attempt(self):
        client=Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse('login'),{'username':'x','password':'x'}).status_code,403)
        self.assertEqual(AccessThrottle.objects.count(),0)

    def test_readiness_rejects_pending_database_migrations(self):
        with patch('apps.accounts.security.MigrationExecutor') as executor:
            executor.return_value.migration_plan.return_value = [('pending', False)]
            response = self.client.get('/health/ready/')
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json(), {'status': 'unavailable'})
            self.assertEqual(self.client.get('/health/live/').status_code, 200)


class QualityHubTests(TestCase):
    @classmethod
    def setUpTestData(cls): results_fixture.ResultsDashboardTests.setUpTestData.__func__(cls)
    make_run=results_fixture.ResultsDashboardTests.make_run
    request_review=results_fixture.ResultsDashboardTests.request_review
    approve=results_fixture.ResultsDashboardTests.approve
    def setUp(self): self.client.force_login(self.f.reviewer)
    def url(self,export=False,scope=None):return reverse('quality-export' if export else 'quality-home',args=[(scope or self.f.scope).pk])
    def test_empty_approved_and_restricted_results_are_distinct(self):
        response=self.client.get(self.url())
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['valid_sets'],0)
        self.assertEqual(response.context['available_count'],0)
        self.approve('quality')
        response=self.client.get(self.url())
        self.assertEqual(response.context['valid_sets'],1)
        self.assertGreater(response.context['restricted_count'],0)
        self.assertEqual(response.context['available_count'],0)
        self.assertNotContains(response,'PRIVATE-EXAMPLE-DO-NOT-DISCLOSE')
        self.assertNotContains(response,'staff-A')
        rows=list(csv.DictReader(io.StringIO(self.client.get(self.url(True)).content.decode('utf-8-sig'))))
        self.assertEqual(len(rows),63)
        self.assertNotIn('value',rows[0])
        self.assertEqual(self.client.post(self.url(),{}).status_code,405)
    def test_invalid_set_not_counted_and_scope_is_enforced(self):
        self.approve('invalid-quality')
        with patch('apps.calculations.quality.review_summary',side_effect=ValidationError('PRIVATE')):
            r=self.client.get(self.url())
            self.assertEqual(r.context['invalid_sets'],1)
            self.assertEqual(r.context['valid_sets'],0)
            self.assertNotContains(r,'PRIVATE')
        other=AccessScope.objects.create(organization=self.f.scope.organization,code='QUALITY-OTHER',name='Other')
        self.assertEqual(self.client.get(self.url(scope=other)).status_code,403)
        self.client.force_login(self.f.staff)
        self.assertEqual(self.client.get(self.url()).status_code,403)
    def test_filters_and_invalid_period_have_no_silent_fallback(self):
        self.approve('filter-quality')
        r=self.client.get(self.url(),{'period':'bad','q':'7.3-38'})
        self.assertIsNone(r.context['selected_period'])
        self.assertEqual(len(r.context['rows']),1)
        self.assertEqual(r.context['valid_sets'],0)

class DemoIntegrityTests(SimpleTestCase):
    def test_corrupt_demo_result_and_source_are_excluded(self):
        from copy import deepcopy
        from apps.calculations.demo_data import build_series, validated_series
        rows=build_series()[:2]
        valid,errors=validated_series([NS(**r) for r in rows])
        self.assertEqual((len(valid),errors),(2,0))
        corrupt=deepcopy(rows)
        corrupt[0]['result']['value']='999'
        corrupt[1]['source_hash']='0'*64
        valid,errors=validated_series([NS(**r) for r in corrupt])
        self.assertEqual((valid,errors),([],2))

class ProductionConfigurationTests(SimpleTestCase):
    def settings_process(self, extra):
        import os, subprocess, sys
        env=os.environ.copy();env.update(NEXORA_ENVIRONMENT='production',DJANGO_DEBUG='false',DJANGO_ALLOWED_HOSTS='nexora.example.test',DJANGO_SECRET_KEY='Synthetic-Configuration-Test-Key-Only-Do-Not-Use-In-Production-9381!')
        env.update(extra)
        return subprocess.run([sys.executable,'-c',"import edpex.settings as s; assert s.SESSION_COOKIE_SECURE and s.CSRF_COOKIE_SECURE and s.SECURE_SSL_REDIRECT; print('configured')"],env=env,capture_output=True,text=True,cwd=settings.BASE_DIR)
    def test_production_requires_secret_debug_off_and_explicit_hosts(self):
        self.assertEqual(self.settings_process({}).returncode,0)
        for extra in [{'DJANGO_SECRET_KEY':'development-only-not-for-production'},{'DJANGO_DEBUG':'true'},{'DJANGO_ALLOWED_HOSTS':'*'}]:
            self.assertNotEqual(self.settings_process(extra).returncode,0)


class BackupUtilityTests(SimpleTestCase):
    def test_missing_database_environment_is_rejected(self):
        import tempfile, os
        from pathlib import Path
        from scripts.backup_database import main
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'backup.dump'
            with patch.dict(os.environ, {}, clear=True), patch('sys.argv', ['backup_database.py', '--output', str(target)]), patch('scripts.backup_database.shutil.which', return_value='/test/pg_dump'):
                with self.assertRaises(SystemExit) as error:
                    main()
            self.assertEqual(error.exception.code, 2)
            self.assertFalse(target.exists())

    def test_backup_checksum_and_no_password_on_command_line(self):
        import tempfile,hashlib
        from pathlib import Path
        from scripts.backup_database import main
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'backup.dump'
            def dump(args,**kwargs):
                self.assertEqual(args,['/test/pg_dump','--format=custom','--no-password'])
                self.assertIn('PGPASSWORD',kwargs['env'])
                kwargs['stdout'].write(b'SYNTHETIC-ARCHIVE')
                return NS(returncode=0)
            with patch('sys.argv',['backup_database.py','--output',str(target)]),patch('scripts.backup_database.shutil.which',return_value='/test/pg_dump'),patch('scripts.backup_database.subprocess.run',side_effect=dump):
                self.assertEqual(main(),0)
            metadata=json.loads(target.with_suffix('.dump.json').read_text())
            self.assertEqual(metadata['sha256'],hashlib.sha256(target.read_bytes()).hexdigest())
            self.assertFalse(metadata['restore_tested'])
            self.assertNotIn('password',str(metadata))
    def test_preexisting_partial_is_not_deleted_on_failure(self):
        import tempfile
        from pathlib import Path
        from scripts.backup_database import main
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'backup.dump';partial=target.with_suffix('.dump.partial');partial.write_bytes(b'ANOTHER-TASK')
            with patch('sys.argv',['backup_database.py','--output',str(target)]),patch('scripts.backup_database.shutil.which',return_value='/test/pg_dump'):
                self.assertEqual(main(),1)
            self.assertEqual(partial.read_bytes(),b'ANOTHER-TASK')
            self.assertFalse(target.exists())
