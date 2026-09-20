"""Dry-run by default; purge only expired secrets and unapproved requests."""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from apps.governance.models import AccessRequest,AccessCode,Confirmation,RegistrationPolicy
class Command(BaseCommand):
    help='Preview expiry cleanup; --apply removes expired secrets and old unapproved requests. Approved account records are retained.'
    def add_arguments(self,parser):parser.add_argument('--apply',action='store_true')
    @transaction.atomic
    def handle(self,*args,**options):
        now=timezone.now();queries=[AccessCode.objects.filter(expires_at__lt=now),Confirmation.objects.filter(expires_at__lt=now)]
        for p in RegistrationPolicy.objects.all():queries.append(AccessRequest.objects.filter(scope=p.scope,account__isnull=True,state__in=['unverified','rejected'],created_at__lt=now-timedelta(days=p.retention_days)))
        for q in queries:
            self.stdout.write(q.model._meta.label+': '+str(q.count()))
            if options['apply']:q.delete()
        self.stdout.write('Applied' if options['apply'] else 'Preview only; use --apply after checking retention policy.')
