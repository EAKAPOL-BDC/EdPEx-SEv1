from io import StringIO
from uuid import uuid4
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, Client
from django.urls import reverse
from apps.accounts.models import Organization, AccessScope, Membership, Role, RoleAssignment
from apps.auditlog.models import AuditEvent


class PortalTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('operator', 'operator@example.test', 'long-test-password')
        self.user = get_user_model().objects.create_user('member', password='long-test-password')
        self.options = dict(organization_id=uuid4(), name='วิทยาลัยการศึกษา', username='operator', reason='Approved initial setup')

    def initialize(self):
        call_command('bootstrap_organization', **self.options, apply=True, stdout=StringIO())
        self.scope = AccessScope.objects.get(organization_id=self.options['organization_id'])
        self.url = reverse('portal-members', args=[self.scope.pk])

    def test_preview_writes_nothing_and_apply_is_idempotent(self):
        call_command('bootstrap_organization', **self.options, stdout=StringIO())
        self.assertEqual(Organization.objects.count(), 0)
        self.initialize()
        call_command('bootstrap_organization', **self.options, apply=True, stdout=StringIO())
        self.assertEqual(Organization.objects.count(), 1)
        self.assertEqual(RoleAssignment.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action='organization.bootstrapped').count(), 1)
        self.assertEqual(get_user_model().objects.count(), 2)

    def test_bootstrap_rejects_ordinary_user_and_existing_unmanaged_org(self):
        with self.assertRaises(CommandError):
            call_command('bootstrap_organization', **{**self.options, 'username': 'member'}, apply=True)
        Organization.objects.create(id=self.options['organization_id'], name=self.options['name'])
        with self.assertRaises(CommandError):
            call_command('bootstrap_organization', **self.options, apply=True)
        self.assertFalse(RoleAssignment.objects.exists())

    def test_home_login_logout_and_safe_next(self):
        self.assertContains(self.client.get('/'), 'ร่วมพัฒนาการศึกษา')
        self.assertRedirects(self.client.get('/workspace/'), '/login/?next=/workspace/')
        response = self.client.post('/login/?next=https://example.org/', {'username':'member', 'password':'long-test-password'})
        self.assertRedirects(response, '/workspace/')
        self.assertContains(self.client.get('/workspace/'), 'ยังไม่มีขอบเขตงาน')
        self.assertEqual(self.client.get('/logout/').status_code, 405)
        self.assertRedirects(self.client.post('/logout/'), '/')

    def test_no_implicit_superuser_access_or_foreign_scope_disclosure(self):
        self.initialize()
        other = Organization.objects.create(name='Other organization secret')
        foreign = AccessScope.objects.create(organization=other, code='root', name='Foreign secret')
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get('/workspace/'), 'Foreign secret')
        self.assertEqual(self.client.get(reverse('portal-members', args=[foreign.pk])).status_code, 403)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_add_member_grant_and_revoke_with_audit(self):
        self.initialize()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(self.url, {'operation':'member', 'username':'member'}).status_code,302)
        member = Membership.objects.get(user=self.user)
        role = Role.objects.get(code='catalog-reader-v1')
        self.assertEqual(self.client.post(self.url, {'operation':'grant', 'membership':member.pk, 'role':role.pk}).status_code,302)
        grant = RoleAssignment.objects.get(membership=member)
        self.client.force_login(self.user)
        self.assertContains(self.client.get('/workspace/'), self.scope.name)
        self.assertEqual(self.client.get(self.url).status_code,403)
        self.client.force_login(self.admin)
        revoke_url = reverse('portal-revoke',args=[self.scope.pk,grant.pk])
        self.assertEqual(self.client.get(revoke_url).status_code,405)
        self.assertEqual(self.client.post(revoke_url).status_code,302)
        self.client.force_login(self.user)
        self.assertContains(self.client.get('/workspace/'), 'ยังไม่มีขอบเขตงาน')
        self.assertTrue(AuditEvent.objects.filter(action='membership.created').exists())
        self.assertTrue(AuditEvent.objects.filter(action='role.revoked').exists())

    def test_foreign_membership_and_csrf_are_rejected(self):
        self.initialize()
        foreign = Organization.objects.create(name='Other')
        member = Membership.objects.create(user=self.user,organization=foreign)
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {'operation':'grant','membership':member.pk,'role':Role.objects.first().pk})
        self.assertEqual(response.status_code,200)
        self.assertFalse(RoleAssignment.objects.filter(membership=member).exists())
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.admin)
        self.assertEqual(browser.post(self.url,{'operation':'member','username':'member'}).status_code,403)

    def test_revoked_bootstrap_is_not_reinstated(self):
        from apps.accounts.services import revoke_role
        self.initialize()
        revoke_role(actor=self.admin, assignment=RoleAssignment.objects.get())
        with self.assertRaises(CommandError):
            call_command('bootstrap_organization', **self.options, apply=True,stdout=StringIO())
        self.assertEqual(RoleAssignment.objects.count(),1)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code,403)

    def test_web_cannot_delegate_more_permissions_than_actor(self):
        self.initialize()
        member = Membership.objects.create(user=self.user,organization=self.scope.organization)
        limited = Role.objects.create(code='limited',permissions=['role.manage'])
        RoleAssignment.objects.create(membership=member,scope=self.scope,role=limited)
        self.client.force_login(self.user)
        response = self.client.post(self.url,{'operation':'grant','membership':member.pk,
            'role':Role.objects.get(code='organization-manager-v1').pk})
        self.assertEqual(response.status_code,403)
        self.assertEqual(RoleAssignment.objects.filter(membership=member).count(),1)

    def test_language_switch_persists_without_granting_access(self):
        from apps.accounts.models import UserPreference
        self.assertContains(self.client.get('/', HTTP_ACCEPT_LANGUAGE='en'), 'ร่วมพัฒนาการศึกษา')
        self.assertEqual(self.client.post('/language/', {'language':'en'}).status_code,200)
        self.assertContains(self.client.get('/'), 'Working together for education')
        self.assertContains(self.client.get('/'), 'lang="en"')
        self.client.force_login(self.user)
        self.client.post('/language/', {'language':'en'})
        self.assertEqual(UserPreference.objects.get(user=self.user).preferred_locale,'en')
        self.assertContains(self.client.get('/workspace/'), 'No work scope has been assigned yet')
        self.assertFalse(RoleAssignment.objects.exists())
        self.assertEqual(self.client.post('/language/', {'language':'fr'}).status_code,400)
        self.assertEqual(UserPreference.objects.get(user=self.user).preferred_locale,'en')
        self.client.post('/language/', {'language':'th'})
        self.assertContains(self.client.get('/workspace/'), 'ยังไม่มีขอบเขตงาน')
