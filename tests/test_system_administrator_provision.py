from io import StringIO
from django.test import TestCase
from django.core.management import call_command
from django.core.management.base import CommandError
from django.contrib.auth import get_user_model
from apps.accounts.models import Organization, AccessScope, Membership, Role, RoleAssignment
from apps.accounts.permissions import can_access
from apps.auditlog.models import AuditEvent

class SystemAdministratorProvisionTests(TestCase):
    def setUp(self):
        org=Organization.objects.create(name='Synthetic provision')
        self.scope=AccessScope.objects.create(organization=org,code='ORG',name='Test')
        self.child=AccessScope.objects.create(organization=org,code='CHILD',name='Child',parent=self.scope)
        self.user=get_user_model().objects.create_superuser('provision-admin','test@example.invalid','synthetic')
        self.member=Membership.objects.create(user=self.user,organization=org)
        role=Role.objects.create(code='test-manager',permissions=['role.manage'])
        RoleAssignment.objects.create(membership=self.member,scope=self.scope,role=role)
    def run_command(self,apply=False):
        call_command('provision_system_administrator',scope_id=self.scope.pk,username=self.user.username,
                     reason='Explicit synthetic authorization',apply=apply,stdout=StringIO())
    def test_preview_does_not_write(self):
        self.run_command()
        self.assertEqual(RoleAssignment.objects.count(),1)
        self.assertFalse(Role.objects.filter(code='system-administrator-v1').exists())
    def test_apply_is_narrow_audited_and_idempotent(self):
        self.run_command(True);self.run_command(True)
        self.assertEqual(RoleAssignment.objects.count(),2)
        from apps.accounts.models import ALLOWED_PERMISSIONS
        for action in ALLOWED_PERMISSIONS:
            self.assertTrue(can_access(self.user,action,self.scope,owner=self.user),action)
            self.assertTrue(can_access(self.user,action,self.child,owner=self.user),action)
        other=AccessScope.objects.create(organization=self.scope.organization,code='OTHER',name='Other')
        for action in ALLOWED_PERMISSIONS:
            self.assertFalse(can_access(self.user,action,other,owner=self.user),action)
        self.assertEqual(set(Role.objects.get(code='system-administrator-v1').permissions),ALLOWED_PERMISSIONS)
        self.assertEqual(AuditEvent.objects.filter(action='system.administrator_provisioned').count(),1)
    def test_non_superuser_rejected(self):
        self.user.is_superuser=False;self.user.save()
        with self.assertRaises(CommandError):self.run_command(True)
        self.assertEqual(RoleAssignment.objects.count(),1)
    def test_mismatched_role_rejected(self):
        Role.objects.create(code='system-administrator-v1',permissions=['result.approve'])
        with self.assertRaises(CommandError):self.run_command(True)
        self.assertEqual(RoleAssignment.objects.count(),1)
    def test_missing_scoped_authority_rejected(self):
        grant=RoleAssignment.objects.get(membership=self.member)
        from django.utils import timezone
        grant.revoked_at=timezone.now();grant.save()
        with self.assertRaises(CommandError):self.run_command(True)
