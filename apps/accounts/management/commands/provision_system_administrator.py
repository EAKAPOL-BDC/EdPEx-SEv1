"""Explicit local administrator provisioning; never invoked by a web request."""
import uuid
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from apps.accounts.models import AccessScope, Membership, Role, RoleAssignment
from apps.accounts.permissions import can_access
from apps.auditlog.services import record_event

ROLE = 'system-administrator-v1'
# Fixed, reviewable snapshot. Future permissions require a new explicit release.
PERMISSIONS = sorted({
    'catalog.read', 'catalog.edit', 'catalog.publish', 'catalog.archive', 'translation.review',
    'calendar.manage', 'round.manage', 'population.manage', 'responsibility.manage',
    'source.manage', 'audit.read', 'self.read', 'self.write', 'role.manage',
    'calculation.run', 'calculation.source', 'calculation.validate',
    'selfassessment.assign', 'result.submit', 'result.review', 'result.approve',
})

class Command(BaseCommand):
    help = 'Preview a full supported permission grant to an existing scoped superuser; --apply writes.'

    def add_arguments(self, parser):
        parser.add_argument('--scope-id', required=True, type=uuid.UUID)
        parser.add_argument('--username', required=True)
        parser.add_argument('--reason', required=True)
        parser.add_argument('--apply', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        reason = options['reason'].strip()
        if not reason or len(reason) > 500:
            raise CommandError('Provide an authorization reason (1-500 characters).')
        scope = AccessScope.objects.select_for_update().filter(pk=options['scope_id'], active=True).first()
        user = get_user_model().objects.filter(username=options['username'], is_active=True, is_superuser=True).first()
        if scope is None or user is None:
            raise CommandError('An active scope and existing active Django superuser are required.')
        member = Membership.objects.filter(user=user, organization=scope.organization, is_active=True).first()
        if member is None or not can_access(user, 'role.manage', scope):
            raise CommandError('The named user must already be an active member with role.manage in this scope.')
        role = Role.objects.filter(code=ROLE).first()
        if role and role.permissions != PERMISSIONS:
            raise CommandError('Existing role differs; no changes made.')
        self.stdout.write(f'User: {user.username}; scope: {scope.pk} ({scope.name}); permissions: {", ".join(PERMISSIONS)}; descendants: yes; expiry: none')
        if RoleAssignment.objects.filter(membership=member, scope=scope, role=role, revoked_at__isnull=True,
                active_from__lte=timezone.now(), active_until__isnull=True, include_descendants=True).exists():
            self.stdout.write('Already provisioned; no changes made.')
            return
        if not options['apply']:
            self.stdout.write('PREVIEW ONLY. Repeat with --apply to write.')
            return
        if role is None:
            role = Role.objects.create(code=ROLE, permissions=PERMISSIONS)
        grant = RoleAssignment.objects.create(membership=member, scope=scope, role=role, include_descendants=True)
        record_event(scope.organization, user, 'system.administrator_provisioned', 'RoleAssignment', grant.pk,
                     reason=reason, metadata={'scope_id':str(scope.pk), 'membership_id':str(member.pk),
                                             'role_id':str(role.pk), 'permissions':PERMISSIONS,
                                             'authorization_channel':'local_admin_command'})
        self.stdout.write(self.style.SUCCESS('Administrator permissions provisioned. Existing result self-approval restrictions remain enforced.'))
