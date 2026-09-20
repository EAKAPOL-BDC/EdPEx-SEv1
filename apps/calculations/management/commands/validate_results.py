"""Read-only replay. Explicit actor authorization is required even in the CLI."""
import json

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.calculations.services import validate_run
from apps.calculations.types import CalculationInputError


class Command(BaseCommand):
    help = "Validate a persisted calculation using its source snapshots; never prints raw answers."

    def add_arguments(self, parser):
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--actor-user-id", required=True, type=int)

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(pk=options["actor_user_id"])
            receipt = validate_run(actor, run_id=options["run_id"])
        except (ObjectDoesNotExist, PermissionDenied, ValidationError, CalculationInputError, ValueError, KeyError, TypeError) as exc:
            raise CommandError("Calculation validation failed; check permissions, snapshot integrity and engine version.") from exc
        self.stdout.write(json.dumps(receipt, sort_keys=True))
