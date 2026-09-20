"""Explicit local administrator provisioning; never invoked by a web request."""
import uuid
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from apps.accounts.models import AccessScope, Membership, Role, RoleAssignment
from apps.accounts.permissions import can_access
from apps.auditlog.services import record_event

ROLE = 'result-submitter-v1'

class Command(BaseCommand):
    help = 'Preview a result.submit + calculation.validate grant to an existing scoped superuser; --apply writes.'

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
        if role and role.permissions != ['calculation.validate', 'result.submit']:
            raise CommandError('Existing role differs; no changes made.')
        self.stdout.write(f'User: {user.username}; scope: {scope.pk} ({scope.name}); permissions: result.submit, calculation.validate; descendants: no; expiry: none')
        if RoleAssignment.objects.filter(membership=member, scope=scope, role=role, revoked_at__isnull=True,
                active_from__lte=timezone.now(), active_until__isnull=True, include_descendants=False).exists():
            self.stdout.write('Already provisioned; no changes made.')
            return
        if not options['apply']:
            self.stdout.write('PREVIEW ONLY. Repeat with --apply to write.')
            return
        if role is None:
            role = Role.objects.create(code=ROLE, permissions=['calculation.validate', 'result.submit'])
        grant = RoleAssignment.objects.create(membership=member, scope=scope, role=role, include_descendants=False)
        record_event(scope.organization, user, 'result.submitter_provisioned', 'RoleAssignment', grant.pk,
                     reason=reason, metadata={'scope_id':str(scope.pk), 'membership_id':str(member.pk),
                                             'role_id':str(role.pk), 'permissions':['calculation.validate', 'result.submit'],
                                             'authorization_channel':'local_admin_command'})
        self.stdout.write(self.style.SUCCESS('Submission permissions provisioned. Refresh the calculated result set.'))
