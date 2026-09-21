"""Write synthetic sources and calculated results to dedicated demo tables only."""
import uuid
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction
from apps.accounts.models import AccessScope
from apps.accounts.permissions import require_permission
from apps.auditlog.services import record_event
from apps.calculations.models import DemoDataset, DemoSeries
from apps.calculations.demo_data import build_series, DEMO_KEY
from apps.calculations.codec import digest

class Command(BaseCommand):
    help = 'Create the complete DEMO-2569 dataset, isolated from actual responses and approvals.'
    def add_arguments(self, parser):
        parser.add_argument('--scope-id',required=True,type=uuid.UUID)
        parser.add_argument('--username',required=True)
        parser.add_argument('--apply',action='store_true')
    @transaction.atomic
    def handle(self,*args,**options):
        scope=AccessScope.objects.select_for_update().get(pk=options['scope_id'],active=True)
        actor=get_user_model().objects.get(username=options['username'],is_active=True)
        for action in ['source.manage','calculation.run','result.review']:
            require_permission(actor,action,scope)
        from apps.governance.models import WorkspaceRefresh
        if WorkspaceRefresh.objects.filter(scope=scope,status='completed').exists():
            raise CommandError('พื้นที่นี้ใช้ข้อมูลสมมุติปี 2565–2567 จากกระบวนการปัจจุบันแล้ว ไม่สร้างชุดสาธิต 2569 รุ่นเดิมซ้ำ / Legacy demo seeding is disabled after workspace refresh.')
        rows=build_series()
        fingerprint=digest(rows)
        count=len({r['indicator_code'] for r in rows})
        self.stdout.write(f'DEMO ONLY: {count} indicators, {len(rows)} group/dimension series, {len({r["group_code"] for r in rows})} groups. No real responses or approvals are changed.')
        existing=DemoDataset.objects.filter(scope=scope,key=DEMO_KEY).first()
        if existing:
            saved=list(existing.series.values(*rows[0].keys()))
            ordered=lambda values:sorted(values,key=lambda r:(r['indicator_code'],r['group_code'],r['dimension']))
            if existing.catalog_hash != fingerprint or digest(ordered(saved)) != digest(ordered(rows)):
                raise CommandError('Existing demo differs. No overwrite performed; use a reviewed new demo version.')
            self.stdout.write('DEMO_READY (existing; no duplicate records)');return
        if not options['apply']:
            self.stdout.write('PREVIEW ONLY: --apply writes the demo dataset.');return
        dataset=DemoDataset.objects.create(scope=scope,key=DEMO_KEY,created_by=actor,catalog_hash=fingerprint)
        DemoSeries.objects.bulk_create([DemoSeries(dataset=dataset,**row) for row in rows])
        record_event(scope.organization,actor,'demo.dataset_created','DemoDataset',dataset.pk,
            reason='User-authorized synthetic dataset for dashboard demonstration; not actual performance.',
            metadata={'scope_id':str(scope.pk),'count':len(rows),'checksum':fingerprint})
        self.stdout.write(self.style.SUCCESS('DEMO_READY: synthetic sources and results saved.'))
