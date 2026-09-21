"""A separate instruction sign-off must not erase reviewed unchanged wording."""
from importlib import import_module
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, transaction, IntegrityError
from django.test import Client, TestCase
from django.urls import reverse
from apps.accounts.models import Organization, AccessScope, Membership, Role, RoleAssignment, ALLOWED_PERMISSIONS
from apps.catalog.models import Instrument, InstrumentVersion, InstrumentContent, Question
from apps.catalog.management_services import prepare_translations, bundle_readiness
from apps.catalog.services import edit_translation, translation_review_snapshot, approve_translation, publish_bundle


class InstructionCurationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        org = Organization.objects.create(name='Synthetic F03 curation')
        cls.scope = AccessScope.objects.create(organization=org, code='CURATION', name='Synthetic scope')
        cls.actor = get_user_model().objects.create_user(username='curation-editor')
        cls.reader = get_user_model().objects.create_user(username='curation-reader')
        for user, permissions in [(cls.actor, sorted(ALLOWED_PERMISSIONS)), (cls.reader, ['catalog.read'])]:
            role = Role.objects.create(code=user.username, permissions=permissions)
            RoleAssignment.objects.create(membership=Membership.objects.create(user=user, organization=org), role=role, scope=cls.scope)
        cls.version = InstrumentVersion.objects.create(instrument=Instrument.objects.create(scope=cls.scope, code='F03'),
            version='curation-test', title_th='Synthetic F03', assessment_method='survey', group_codes=['ST1','ST2'])
        InstrumentContent.objects.create(version=cls.version, content_key='F03.title', kind='title', audience='respondent', text_th=cls.version.title_th)
        InstrumentContent.objects.create(version=cls.version, content_key='F03.instruction', kind='instruction', audience='respondent', text_th='Synthetic respondent instructions')
        Question.objects.create(version=cls.version, question_id='F03-O01', text_th='Synthetic open comment', answer_type='text', group_codes=['ST1','ST2'])
        cls.bundle = prepare_translations(cls.actor, cls.version.pk)
        for entry in cls.bundle.translations.order_by('content_key', 'locale'):
            if entry.locale == 'en':
                entry = edit_translation(cls.actor, entry, 'Synthetic English '+entry.content_key)
            snapshot = translation_review_snapshot(cls.actor, entry)
            approve_translation(cls.actor, entry, reviewed_token=snapshot['reviewed_token'])

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.actor)
        self.version.refresh_from_db()

    def url(self, name):
        return reverse('portal-catalog-'+name, kwargs={'scope_id':self.scope.pk, 'version_id':self.version.pk})

    def post(self, url, data):
        return self.client.post(url, {**data, 'csrfmiddlewaretoken':self.client.cookies['csrftoken'].value})

    def editor_payload(self, **changes):
        page = self.client.get(self.url('edit'))
        form = page.context['form']
        data = {name:form[name].value() for name in ('snapshot', 'title_th', 'instruction')}
        return {**data, 'instructions_curated':'on', **changes}

    def rows(self):
        return list(self.bundle.translations.order_by('pk').values_list('pk','text','source_hash','status','reviewed_by_id','reviewed_at','review_revision'))

    def test_reviewed_f03_can_be_curated_and_published_without_losing_approvals(self):
        before = self.rows()
        self.assertFalse(bundle_readiness(self.version, self.bundle)['curated'])
        page = self.client.get(self.url('publish'))
        self.assertContains(page, self.url('edit'))
        blocked = self.post(self.url('publish'), {'bundle':self.bundle.pk,'confirm':'on'})
        self.assertContains(blocked, 'ยังไม่ได้รับรองคำชี้แจง', status_code=422)
        result = self.post(self.url('edit'), self.editor_payload())
        self.assertEqual(result.status_code,302)
        self.assertEqual(self.rows(), before)
        self.version.refresh_from_db()
        self.assertTrue(bundle_readiness(self.version,self.bundle)['ready'])
        self.client.get(self.url('publish'))
        result = self.post(self.url('publish'), {'bundle':self.bundle.pk,'confirm':'on'})
        self.assertEqual(result.status_code,302,result.content.decode())
        self.version.refresh_from_db(); self.bundle.refresh_from_db()
        self.assertEqual(self.version.status,'published')
        self.assertEqual(self.bundle.status,'published')

    def test_changed_instruction_with_signoff_still_requires_translation_review(self):
        data = self.editor_payload(instruction='Changed synthetic instruction')
        result = self.post(self.url('edit'),data)
        self.assertEqual(result.status_code,302)
        self.assertFalse(self.bundle.translations.filter(status='approved').exists())
        self.assertTrue(self.bundle.translations.filter(status='stale').exists())
        self.version.refresh_from_db()
        self.assertFalse(bundle_readiness(self.version,self.bundle)['ready'])
        self.client.get(self.url('publish'))
        self.assertEqual(self.post(self.url('publish'),{'bundle':self.bundle.pk,'confirm':'on'}).status_code,422)

    def test_metadata_signoff_does_not_approve_pending_translation(self):
        entry=self.bundle.translations.filter(locale='en').first()
        edit_translation(self.actor,entry,'Changed English pending review')
        before=self.rows()
        self.assertEqual(self.post(self.url('edit'),self.editor_payload()).status_code,302)
        self.assertEqual(self.rows(),before)
        self.version.refresh_from_db()
        self.assertGreater(bundle_readiness(self.version,self.bundle)['remaining'],0)

    def test_migration_and_direct_sql_signoff_preserve_rows_but_false_gate_blocks_publication(self):
        before=self.rows()
        migration=import_module('apps.catalog.migrations.0004_instruction_curation_metadata')
        with connection.cursor() as cursor:
            cursor.execute(migration.ORIGINAL)
            cursor.execute(migration.UPDATED)
            cursor.execute('UPDATE catalog_instrumentversion SET instructions_curated=true WHERE id=%s',[self.version.pk])
        self.assertEqual(self.rows(),before)
        with connection.cursor() as cursor:
            cursor.execute('UPDATE catalog_instrumentversion SET instructions_curated=false WHERE id=%s',[self.version.pk])
        self.assertEqual(self.rows(),before)
        self.version.refresh_from_db()
        self.assertFalse(bundle_readiness(self.version,self.bundle)['ready'])
        with self.assertRaises(ValidationError) as error:
            with transaction.atomic(): publish_bundle(self.actor,self.bundle)
        self.assertIn('instruction',str(error.exception).lower())

    def test_direct_sql_content_change_with_signoff_invalidates_approvals(self):
        with connection.cursor() as cursor:
            cursor.execute('UPDATE catalog_instrumentversion SET title_th=%s,instructions_curated=true WHERE id=%s',['Changed synthetic title',self.version.pk])
        self.assertFalse(self.bundle.translations.filter(status='approved').exists())
        self.assertTrue(self.bundle.translations.filter(status='stale').exists())

    def test_published_curation_remains_immutable(self):
        self.post(self.url('edit'),self.editor_payload())
        self.client.get(self.url('publish'))
        self.assertEqual(self.post(self.url('publish'),{'bundle':self.bundle.pk,'confirm':'on'}).status_code,302)
        with self.assertRaises(IntegrityError):
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute('UPDATE catalog_instrumentversion SET instructions_curated=false WHERE id=%s',[self.version.pk])

    def test_readonly_user_cannot_curate(self):
        payload=self.editor_payload()
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(self.url('edit')).status_code,403)
        self.assertEqual(self.post(self.url('edit'),payload).status_code,403)
        self.version.refresh_from_db()
        self.assertFalse(self.version.instructions_curated)
