from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from apps.accounts.models import Organization, AccessScope, Membership, Role, RoleAssignment
from apps.auditlog.models import AuditEvent
from apps.auditlog.services import record_event, events_for_scope


class AuditTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Synthetic organization')
        self.scope = AccessScope.objects.create(organization=self.org, code='A', name='A')
        self.other = AccessScope.objects.create(organization=self.org, code='B', name='B')
        self.user = get_user_model().objects.create_user('synthetic-auditor')
        membership = Membership.objects.create(user=self.user, organization=self.org)
        role = Role.objects.create(code='audit-scope-A', permissions=['audit.read'])
        RoleAssignment.objects.create(membership=membership, role=role, scope=self.scope)

    def event(self, scope):
        return record_event(self.org, self.user, 'fixture.created', 'fixture', 'synthetic',
            metadata={'scope_id': str(scope.pk), 'token': 'not-a-real-token', 'raw_answer': 'excluded'})

    def test_sensitive_payload_is_not_copied(self):
        event = self.event(self.scope)
        self.assertEqual(event.metadata, {'scope_id': str(self.scope.pk)})
        with self.assertRaises(ValidationError):
            record_event(self.org, self.user, 'fixture', 'fixture', '1', metadata={'status': {'raw': 'x'}})

    def test_cross_scope_read_is_denied_and_sibling_events_hidden(self):
        own = self.event(self.scope)
        self.event(self.other)
        self.assertEqual(list(events_for_scope(self.user, self.scope)), [own])
        with self.assertRaises(PermissionDenied):
            events_for_scope(self.user, self.other)

    def test_history_cannot_be_rewritten_through_queryset_or_sql(self):
        event = self.event(self.scope)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AuditEvent.objects.filter(pk=event.pk).update(reason='rewritten')
        with self.assertRaises(IntegrityError), transaction.atomic():
            AuditEvent.objects.filter(pk=event.pk).delete()
        event.refresh_from_db()
        self.assertEqual(event.reason, '')

    def test_model_delete_is_denied(self):
        with self.assertRaises(ValidationError):
            self.event(self.scope).delete()
