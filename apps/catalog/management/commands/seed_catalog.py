from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import AccessScope
from apps.catalog.seeding import seed_catalog


class Command(BaseCommand):
    help = "Explicitly seed checked M0 definitions as drafts in an authorized scope. Never publishes."

    def add_arguments(self, parser):
        parser.add_argument("--scope-id", required=True)
        parser.add_argument("--actor-user-id", required=True, type=int)
        parser.add_argument("--version", default="1.1")

    def handle(self, *args, **options):
        try:
            scope = AccessScope.objects.get(pk=options["scope_id"])
            actor = get_user_model().objects.get(pk=options["actor_user_id"])
            result = seed_catalog(scope, actor, version=options["version"])
        except (ValidationError, PermissionDenied, AccessScope.DoesNotExist, get_user_model().DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Created {result['created_instruments']} draft instrument versions; no content published."))
