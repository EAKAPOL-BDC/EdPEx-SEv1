"""Local-only bootstrap for the explicitly isolated public demonstration database."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from apps.accounts.models import AccessScope, Membership, Role, RoleAssignment
from apps.accounts.management.commands.provision_system_administrator import PERMISSIONS, ROLE
from apps.auditlog.services import record_event


class Command(BaseCommand):
    help = 'Prepare a password-disabled administrator in the isolated public preview. Never resets an existing password.'

    def add_arguments(self, parser):
        parser.add_argument('--username', required=True)
        parser.add_argument('--reason', required=True)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        db = settings.DATABASES['default']
        if not (settings.SETTINGS_MODULE == 'edpex.public_demo' and db['NAME'] == 'edpex_m1_public_ui'
                and str(db['PORT']) == '55469' and db['HOST'] == '127.0.0.1'
                and not getattr(settings, 'NEXORA_PARTICIPATION_ALLOW_LIVE', False)):
            raise CommandError('Only the isolated public preview is allowed.')
        if not options['reason'].strip() or len(options['reason']) > 500:
            raise CommandError('A recorded authorization reason is required (1–500 characters).')
        user = get_user_model().objects.filter(username=options['username']).first()
        if user and (not user.is_active or not user.is_superuser):
            raise CommandError('Existing account is not an active administrator; no changes made.')
        scopes = list(AccessScope.objects.filter(active=True).order_by('pk'))
        self.stdout.write(f"Account: {options['username']}; active scopes: {len(scopes)}; permissions: {len(PERMISSIONS)}")
        if not options['apply']:
            self.stdout.write('Preview only. A new account has no usable password until its owner sets one locally.')
            return
        with transaction.atomic():
            if not user:
                user = get_user_model()(username=options['username'], is_active=True, is_staff=True, is_superuser=True)
                user.set_unusable_password()
                user.full_clean()
                user.save()
            role, _ = Role.objects.get_or_create(code=ROLE, defaults={'permissions':PERMISSIONS})
            if role.permissions != PERMISSIONS:
                raise CommandError('Administrator permission definition differs; transaction rolled back.')
            for scope in scopes:
                member, _ = Membership.objects.get_or_create(user=user, organization=scope.organization)
                if not member.is_active:
                    raise CommandError('Existing membership is suspended; transaction rolled back.')
                from django.utils import timezone
                existing = RoleAssignment.objects.filter(membership=member, scope=scope, role=role,
                    include_descendants=True, revoked_at__isnull=True, active_until__isnull=True,
                    active_from__lte=timezone.now()).exists()
                if not existing:
                    grant = RoleAssignment.objects.create(membership=member, scope=scope, role=role, include_descendants=True)
                    record_event(scope.organization, user, 'system.administrator_provisioned', 'RoleAssignment', grant.pk,
                        reason=options['reason'], metadata={'scope_id':str(scope.pk), 'authorization_channel':'local_preview_command',
                                                          'permissions':PERMISSIONS})
            self.stdout.write('Prepared. Existing passwords unchanged. Self-approval restrictions remain enforced.')
            if not user.has_usable_password():
                self.stdout.write('Owner must run: python manage.py changepassword '+user.username+' --settings=edpex.public_demo')
