"""Authorization tests exercise denied operations and persisted revocation."""

from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    AccessScope, Membership, Organization, Role, RoleAssignment, UserPreference,
)
from apps.accounts.permissions import can_access, has_active_membership, require_permission
from apps.accounts.services import assign_role, read_profile, revoke_role, update_profile_locale
from apps.auditlog.models import AuditEvent


class ScopedPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="คณะต้นแบบ")
        cls.other_organization = Organization.objects.create(name="องค์กรอื่น")
        cls.scope = AccessScope.objects.create(organization=cls.organization, code="faculty", name="คณะ")
        cls.child = AccessScope.objects.create(organization=cls.organization, code="department", name="ภาควิชา", parent=cls.scope)
        cls.sibling = AccessScope.objects.create(organization=cls.organization, code="other-department", name="ภาควิชาอื่น", parent=cls.scope)
        cls.foreign_scope = AccessScope.objects.create(organization=cls.other_organization, code="faculty", name="องค์กรอื่น")
        cls.actor = get_user_model().objects.create_user(username="respondent")
        cls.other = get_user_model().objects.create_user(username="other")
        cls.administrator = get_user_model().objects.create_superuser(username="administrator", email="", password=None)
        cls.membership = Membership.objects.create(user=cls.actor, organization=cls.organization)
        cls.other_membership = Membership.objects.create(user=cls.other, organization=cls.organization)
        cls.admin_membership = Membership.objects.create(user=cls.administrator, organization=cls.organization)
        cls.role = Role.objects.create(code="respondent", permissions=["self.read", "self.write"])
        cls.manager_role = Role.objects.create(code="scope-manager", permissions=["catalog.edit", "role.manage"])

    def grant(self, **kwargs):
        values = {"membership": self.membership, "role": self.role, "scope": self.scope}
        values.update(kwargs)
        return RoleAssignment.objects.create(**values)

    def test_existing_django_user_model_is_preserved(self):
        self.assertEqual(settings.AUTH_USER_MODEL, "auth.User")
        self.assertEqual(Membership._meta.get_field("user").remote_field.model, get_user_model())

    def test_default_deny_includes_anonymous_staff_and_superuser(self):
        for actor in (AnonymousUser(), self.actor, self.administrator):
            with self.subTest(actor=str(actor)):
                self.assertFalse(can_access(actor, "catalog.edit", self.scope))
        self.assertFalse(can_access(self.actor, "unsupported.action", self.scope))

    def test_self_access_needs_explicit_grant_and_matching_owner(self):
        self.grant()
        self.assertTrue(can_access(self.actor, "self.read", self.scope, owner=self.actor))
        self.assertTrue(can_access(self.actor, "self.write", self.scope, owner=self.actor.pk))
        self.assertFalse(can_access(self.actor, "self.read", self.scope))
        self.assertFalse(can_access(self.actor, "self.write", self.scope, owner=self.other))
        self.assertFalse(can_access(self.other, "self.read", self.scope, owner=self.other))

    def test_superuser_with_self_grant_still_cannot_read_another_person(self):
        self.grant(membership=self.admin_membership)
        self.assertTrue(can_access(self.administrator, "self.read", self.scope, owner=self.administrator))
        self.assertFalse(can_access(self.administrator, "self.read", self.scope, owner=self.actor))
        self.assertFalse(can_access(self.administrator, "survey.raw.read", self.scope))

    def test_cross_scope_and_cross_organization_are_denied(self):
        self.grant(scope=self.child, role=self.manager_role)
        self.assertTrue(can_access(self.actor, "catalog.edit", self.child))
        for scope in (self.scope, self.sibling, self.foreign_scope):
            with self.subTest(scope=scope.code):
                self.assertFalse(can_access(self.actor, "catalog.edit", scope))

    def test_descendants_are_opt_in_and_never_include_parent(self):
        self.grant(role=self.manager_role)
        self.assertFalse(can_access(self.actor, "catalog.edit", self.child))
        self.grant(role=self.manager_role, include_descendants=True)
        self.assertTrue(can_access(self.actor, "catalog.edit", self.child))
        self.assertFalse(can_access(self.actor, "catalog.edit", self.foreign_scope))
        self.grant(membership=self.other_membership, role=self.manager_role, scope=self.child, include_descendants=True)
        self.assertFalse(can_access(self.other, "catalog.edit", self.scope))

    def test_membership_revocation_uses_persisted_state(self):
        self.grant()
        self.assertTrue(has_active_membership(self.actor, self.scope))
        Membership.objects.filter(pk=self.membership.pk).update(is_active=False)
        self.assertFalse(can_access(self.actor, "self.read", self.scope, owner=self.actor))
        self.assertFalse(has_active_membership(self.actor, self.scope))

    def test_disabled_user_is_denied_even_when_request_object_is_stale(self):
        self.grant()
        get_user_model().objects.filter(pk=self.actor.pk).update(is_active=False)
        self.assertTrue(self.actor.is_active)
        self.assertFalse(can_access(self.actor, "self.read", self.scope, owner=self.actor))

    def test_disabled_scope_or_ancestor_is_denied(self):
        self.grant(scope=self.child)
        AccessScope.objects.filter(pk=self.scope.pk).update(active=False)
        self.assertFalse(can_access(self.actor, "self.read", self.child, owner=self.actor))
        self.assertFalse(has_active_membership(self.actor, self.child))

    def test_grant_interval_includes_start_and_excludes_end(self):
        start = timezone.now()
        end = start + timedelta(hours=1)
        self.grant(active_from=start, active_until=end)
        for instant, expected in ((start - timedelta(seconds=1), False), (start, True), (end, False)):
            with self.subTest(instant=instant), patch("apps.accounts.permissions.timezone.now", return_value=instant):
                self.assertEqual(can_access(self.actor, "self.read", self.scope, owner=self.actor), expected)

    def test_assigned_roles_cannot_change_in_place_and_revocation_is_immediate(self):
        grant = self.grant()
        self.role.permissions = []
        with self.assertRaises(ValidationError):
            self.role.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Role.objects.filter(pk=self.role.pk).update(permissions=[])
        self.role.refresh_from_db()
        self.role.code = "renamed-role"
        with self.assertRaises(ValidationError):
            self.role.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Role.objects.filter(pk=self.role.pk).update(code="renamed-role")
        self.grant(role=self.manager_role)
        revoke_role(actor=self.actor, assignment=grant)
        self.assertFalse(can_access(self.actor, "self.read", self.scope, owner=self.actor))

    def test_malformed_and_nonexistent_scopes_fail_closed(self):
        self.grant()
        for scope in (None, "not-a-uuid", "00000000-0000-0000-0000-000000000000"):
            with self.subTest(scope=scope):
                self.assertFalse(can_access(self.actor, "self.read", scope, owner=self.actor))
        with self.assertRaises(PermissionDenied):
            require_permission(self.actor, "catalog.publish", self.scope)

    def test_database_rejects_cross_organization_grant_update(self):
        grant = self.grant(role=self.manager_role)
        with self.assertRaises(IntegrityError), transaction.atomic():
            RoleAssignment.objects.filter(pk=grant.pk).update(scope=self.foreign_scope)
        self.assertFalse(can_access(self.actor, "catalog.edit", self.foreign_scope))

    def test_profile_services_enforce_cross_user_denial_before_write(self):
        self.grant()
        self.assertEqual(read_profile(actor=self.actor, scope=self.scope, owner=self.actor)["preferred_locale"], "th")
        update_profile_locale(actor=self.actor, scope=self.scope, owner=self.actor, preferred_locale="en")
        self.assertEqual(UserPreference.objects.get(user=self.actor).preferred_locale, "en")
        with self.assertRaises(PermissionDenied):
            read_profile(actor=self.actor, scope=self.scope, owner=self.other)
        with self.assertRaises(PermissionDenied):
            update_profile_locale(actor=self.actor, scope=self.scope, owner=self.other, preferred_locale="en")
        self.assertFalse(UserPreference.objects.filter(user=self.other).exists())
        self.assertEqual(AuditEvent.objects.get().action, "profile.locale_changed")

    def test_profile_services_deny_wrong_scope_and_invalid_locale(self):
        self.grant()
        with self.assertRaises(PermissionDenied):
            update_profile_locale(actor=self.actor, scope=self.child, owner=self.actor, preferred_locale="en")
        with self.assertRaises(ValidationError):
            update_profile_locale(actor=self.actor, scope=self.scope, owner=self.actor, preferred_locale="fr")
        self.assertFalse(UserPreference.objects.filter(user=self.actor).exists())

    def test_role_service_requires_scope_permission(self):
        with self.assertRaises(PermissionDenied):
            assign_role(actor=self.actor, scope=self.scope, membership=self.other_membership, role=self.role)
        self.grant(role=self.manager_role)
        self.grant()
        grant = assign_role(actor=self.actor, scope=self.scope, membership=self.other_membership, role=self.role)
        self.assertTrue(can_access(self.other, "self.read", self.scope, owner=self.other))
        with self.assertRaises(PermissionDenied):
            assign_role(actor=self.actor, scope=self.sibling, membership=self.other_membership, role=self.role)
        revoke_role(actor=self.actor, assignment=grant)
        self.assertFalse(can_access(self.other, "self.read", self.scope, owner=self.other))
        self.assertTrue(RoleAssignment.objects.filter(pk=grant.pk, revoked_at__isnull=False).exists())
        self.assertEqual(set(AuditEvent.objects.values_list("action", flat=True)), {"role.assigned", "role.revoked"})

    def test_future_grant_can_be_revoked_without_rewriting_history(self):
        self.grant(role=self.manager_role)
        start = timezone.now() + timedelta(days=1)
        end = start + timedelta(days=30)
        grant = self.grant(membership=self.other_membership, active_from=start, active_until=end)
        revoked = revoke_role(actor=self.actor, assignment=grant)
        self.assertEqual(revoked.active_from, start)
        self.assertEqual(revoked.active_until, end)
        with patch("apps.accounts.permissions.timezone.now", return_value=start):
            self.assertFalse(can_access(self.other, "self.read", self.scope, owner=self.other))


    def test_role_manager_cannot_delegate_actions_it_does_not_hold(self):
        self.grant(role=self.manager_role)
        with self.assertRaises(PermissionDenied):
            assign_role(actor=self.actor, scope=self.scope, membership=self.other_membership, role=self.role)
        self.assertFalse(RoleAssignment.objects.filter(membership=self.other_membership).exists())

    def test_delegation_cannot_add_descendant_authority(self):
        self.grant(role=self.manager_role)
        with self.assertRaises(PermissionDenied):
            assign_role(actor=self.actor, scope=self.scope, membership=self.other_membership,
                        role=self.manager_role, include_descendants=True)
        self.grant(role=self.manager_role, include_descendants=True)
        assign_role(actor=self.actor, scope=self.child, membership=self.other_membership,
                    role=self.manager_role, include_descendants=True)
        self.assertTrue(can_access(self.other, "catalog.edit", self.child))
        self.assertFalse(can_access(self.other, "catalog.edit", self.sibling))

    def test_delegation_cannot_outlive_authorizing_grant(self):
        end = timezone.now() + timedelta(days=1)
        self.grant(role=self.manager_role, active_until=end)
        for active_until in (None, end + timedelta(seconds=1)):
            with self.subTest(active_until=active_until), self.assertRaises(PermissionDenied):
                assign_role(actor=self.actor, scope=self.scope, membership=self.other_membership,
                            role=self.manager_role, active_until=active_until)
        assign_role(actor=self.actor, scope=self.scope, membership=self.other_membership,
                    role=self.manager_role, active_until=end)

    def test_cross_organization_relationships_are_rejected(self):
        with self.assertRaises(ValidationError):
            self.grant(scope=self.foreign_scope)
        with self.assertRaises(ValidationError):
            AccessScope.objects.create(organization=self.other_organization, code="cross", name="Invalid", parent=self.scope)

    def test_parent_cycles_are_rejected(self):
        self.scope.parent = self.child
        with self.assertRaises(ValidationError):
            self.scope.save()
        self.scope.parent = self.scope
        with self.assertRaises(ValidationError):
            self.scope.save()

    def test_scope_and_membership_cannot_change_organization(self):
        self.scope.organization = self.other_organization
        with self.assertRaises(ValidationError):
            self.scope.save()
        self.membership.organization = self.other_organization
        with self.assertRaises(ValidationError):
            self.membership.save()

    def test_permissions_dates_timezone_and_locale_are_validated(self):
        for permissions in (["*"], ["survey.raw.read"], {"self.read": True}, ["self.read", "self.read"]):
            with self.subTest(permissions=permissions), self.assertRaises(ValidationError):
                Role.objects.create(code="invalid", permissions=permissions)
        now = timezone.now()
        with self.assertRaises(ValidationError):
            self.grant(active_from=now, active_until=now)
        with self.assertRaises(ValidationError):
            self.grant(active_from=now.replace(tzinfo=None))
        with self.assertRaises(ValidationError):
            Organization.objects.create(name="Invalid timezone", timezone="not/a-timezone")
        with self.assertRaises(ValidationError):
            UserPreference.objects.create(user=self.actor, preferred_locale="fr")

    def test_database_guards_scope_cycles_and_identity_changes(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccessScope.objects.filter(pk=self.scope.pk).update(parent=self.child)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccessScope.objects.filter(pk=self.scope.pk).update(organization=self.other_organization)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membership.objects.filter(pk=self.membership.pk).update(user=self.other)

    def test_database_guards_permission_allowlist_and_revocation_history(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Role.objects.filter(pk=self.role.pk).update(permissions=["*"])
        with self.assertRaises(IntegrityError), transaction.atomic():
            Role.objects.filter(pk=self.role.pk).update(permissions={"self.read": True})
        self.grant(role=self.manager_role)
        grant = self.grant(membership=self.other_membership)
        revoke_role(actor=self.actor, assignment=grant)
        with self.assertRaises(IntegrityError), transaction.atomic():
            RoleAssignment.objects.filter(pk=grant.pk).update(revoked_at=None)

    def test_grant_identity_scope_dates_and_descendants_are_immutable(self):
        grant = self.grant()
        for field, value in (
            ("membership", self.other_membership), ("role", self.manager_role),
            ("scope", self.child), ("include_descendants", True),
            ("active_from", grant.active_from - timedelta(days=1)),
            ("active_until", grant.active_from + timedelta(days=1)),
        ):
            with self.subTest(field=field):
                setattr(grant, field, value)
                with self.assertRaises(ValidationError):
                    grant.save()
                grant.refresh_from_db()
                with self.assertRaises(IntegrityError), transaction.atomic():
                    RoleAssignment.objects.filter(pk=grant.pk).update(**{field: value})
        with self.assertRaises(ValidationError):
            grant.delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            RoleAssignment.objects.filter(pk=grant.pk).delete()

    def test_unassigned_role_remains_editable_until_first_grant(self):
        self.role.permissions = ["self.read"]
        self.role.save()
        self.grant()
        self.assertTrue(can_access(self.actor, "self.read", self.scope, owner=self.actor))
        self.assertFalse(can_access(self.actor, "self.write", self.scope, owner=self.actor))
