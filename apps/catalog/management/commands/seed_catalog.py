import time
from django.db import connection
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
        parser.add_argument("--catalog-version", default="1.1")

    def handle(self, *args, **options):
        started = time.monotonic()
        last_report = started
        completed_queries = 0

        def report(message):
            self.stdout.write(f"[{time.monotonic() - started:.0f}s] {message}")
            self.stdout.flush()

        def observe(execute, sql, params, many, context):
            nonlocal last_report, completed_queries
            result = execute(sql, params, many, context)
            completed_queries += 1
            if time.monotonic() - last_report >= 10:
                report(f"Database operations completed: {completed_queries}; import not committed yet")
                last_report = time.monotonic()
            return result

        report("Starting import; checking scope and account")
        try:
            scope = AccessScope.objects.get(pk=options["scope_id"])
            actor = get_user_model().objects.get(pk=options["actor_user_id"])
            with connection.execute_wrapper(observe):
                result = seed_catalog(scope, actor, version=options["catalog_version"], progress=report)
        except (ValidationError, PermissionDenied, AccessScope.DoesNotExist, get_user_model().DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Created {result['created_instruments']} draft instrument versions; no content published."))
