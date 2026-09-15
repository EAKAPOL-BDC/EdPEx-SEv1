"""Explicit operator-only first grant. Dry run by default; never called by a view."""
import uuid
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction, connection
from apps.accounts.models import Organization, AccessScope, Membership, Role, RoleAssignment
from apps.auditlog.models import AuditEvent
from apps.auditlog.services import record_event


# Stable initial administrative permissions. Adding an application action must
# never silently grant source access or result approval to new administrators.
BOOTSTRAP_PERMISSIONS = frozenset({
    'catalog.read', 'catalog.edit', 'catalog.publish', 'catalog.archive', 'translation.review',
    'calendar.manage', 'round.manage', 'population.manage', 'responsibility.manage',
    'source.manage', 'audit.read', 'self.read', 'self.write', 'role.manage',
})


class Command(BaseCommand):
    help = "Preview/create the first organization and administrator grant; requires --apply to write."

    def add_arguments(self, parser):
        parser.add_argument('--organization-id', required=True, type=uuid.UUID)
        parser.add_argument('--name', required=True)
        parser.add_argument('--username', required=True)
        parser.add_argument('--reason', required=True)
        parser.add_argument('--apply', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        # Serialize competing bootstraps of the same organization on PostgreSQL.
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(%s)', [578344221877])
        actor = get_user_model().objects.filter(username=options['username'], is_active=True, is_superuser=True).first()
        if actor is None:
            raise CommandError('An existing active Django superuser must be explicitly named.')
        if not options['name'].strip() or not options['reason'].strip() or len(options['reason']) > 500:
            raise CommandError('Organization name and authorization reason must not be blank.')
        org = Organization.objects.filter(pk=options['organization_id']).first()
        if org:
            if org.name != options['name']:
                raise CommandError('Organization ID already exists with a different name.')
            event = AuditEvent.objects.filter(organization=org, action='organization.bootstrapped', actor=actor).first()
            if event:
                grant = RoleAssignment.objects.filter(pk=event.object_id, membership__user=actor,
                    membership__is_active=True, revoked_at__isnull=True, active_until__isnull=True,
                    scope__active=True).first()
                if grant:
                    self.stdout.write('Already initialized; no changes made.')
                    return
            raise CommandError('Existing organization is not eligible for bootstrap. Use normal scoped delegation.')
        if Organization.objects.filter(name=options['name']).exists():
            raise CommandError('Name already exists. Reuse the original organization ID; do not create a duplicate.')
        self.stdout.write(f"Organization: {options['name']} / {options['organization_id']}")
        self.stdout.write(f"Initial administrator: {actor.get_username()}; scope: organization; descendants: yes")
        self.stdout.write('Permissions: ' + ', '.join(sorted(BOOTSTRAP_PERMISSIONS)))
        if not options['apply']:
            self.stdout.write('PREVIEW ONLY. No data written. Review and repeat with --apply to initialize.')
            return
        org = Organization.objects.create(id=options['organization_id'], name=options['name'])
        scope = AccessScope.objects.create(organization=org, code='organization', name=org.name)
        member = Membership.objects.create(user=actor, organization=org)
        presets = {'organization-manager-v1': sorted(BOOTSTRAP_PERMISSIONS),
                   'catalog-reader-v1': ['catalog.read'],
                   'self-service-v1': ['self.read', 'self.write']}
        roles = {}
        for code, permissions in presets.items():
            role, _ = Role.objects.get_or_create(code=code, defaults={'permissions': permissions})
            if role.permissions != permissions:
                raise CommandError('Existing role definition differs; initialization rolled back.')
            roles[code] = role
        grant = RoleAssignment.objects.create(membership=member, scope=scope,
            role=roles['organization-manager-v1'], include_descendants=True)
        record_event(org, actor, 'organization.bootstrapped', 'RoleAssignment', grant.pk,
            reason=options['reason'], metadata={'scope_id': str(scope.pk), 'membership_id': str(member.pk),
                'role_id': str(grant.role_id)})
        self.stdout.write(self.style.SUCCESS('Organization initialized. Open /workspace/.'))
