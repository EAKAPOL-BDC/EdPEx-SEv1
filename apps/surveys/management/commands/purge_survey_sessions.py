from django.core.management.base import BaseCommand
from apps.surveys.services import cleanup
class Command(BaseCommand):
    help='Delete expired transient anonymous drafts and access-throttle buckets.'
    def handle(self,*args,**options):
        cleanup()
        self.stdout.write('Expired anonymous sessions removed.')
