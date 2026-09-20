import json
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand,CommandError
from django.core.exceptions import ValidationError,PermissionDenied
from django.db import connection
from apps.accounts.models import AccessScope
from apps.governance.refresh import plan,execute,REVISION
from apps.governance.models import WorkspaceRefresh

class Command(BaseCommand):
    help='Preview scoped removal of collection data; explicitly apply and seed fictional 2565–2567, leaving 2568 empty.'
    def add_arguments(self,p):
        p.add_argument('--scope',help='Exact scope UUID')
        p.add_argument('--list-scopes',action='store_true')
        p.add_argument('--status',action='store_true',help='Read committed refresh status only; never clear or seed data.')
        p.add_argument('--actor',required=True,help='Existing authorized administrator username')
        p.add_argument('--apply',action='store_true')
        p.add_argument('--plan-hash',default='')
        p.add_argument('--confirm',default='')
        p.add_argument('--reason',default='')
        p.add_argument('--repeat',action='store_true',help='Explicitly replace a previous completed simulation seed')
    def handle(self,*args,**o):
        try:
            actor=get_user_model().objects.get(username=o['actor'],is_active=True)
            if o['list_scopes']:
                from apps.accounts.permissions import can_access
                from apps.governance.refresh import PERMISSIONS
                items=[{'id':str(s.pk),'code':s.code,'name':s.name} for s in AccessScope.objects.filter(active=True) if all(can_access(actor,p,s) for p in PERMISSIONS)]
                self.stdout.write(json.dumps(items,ensure_ascii=False));return
            if not o['scope']:raise CommandError('--scope is required')
            scope=AccessScope.objects.get(pk=o['scope'],active=True)
            if o['status']:
                from apps.governance.refresh import authorize
                authorize(actor,scope)
                latest=WorkspaceRefresh.objects.filter(scope=scope,status='completed').order_by('-completed_at').first()
                self.stdout.write(json.dumps({'scope':scope.code,'status':'completed' if latest else 'no_committed_refresh',
                    'completed_at':latest.completed_at.isoformat() if latest else None,
                    'summary':latest.summary if latest else None,
                    'note':'Read-only. An unfinished transaction is not visible here.'},ensure_ascii=False,indent=2))
                return
            current=plan(actor,scope)
            self.stdout.write(json.dumps({k:v for k,v in current.items() if k!='manifest'},ensure_ascii=False,indent=2)) if not o['apply'] else None
            if not o['apply']:
                self.stdout.write('PREVIEW ONLY: accounts, roles, catalog, annual registers and audit history are retained. No data changed.')
                return
            if WorkspaceRefresh.objects.filter(scope=scope,revision=REVISION,status='completed').exists() and not o['repeat']:
                raise CommandError('Already refreshed. Nothing changed. A deliberate new reset requires --repeat and a fresh plan hash.')
            from apps.governance.simulation import seed_workspace
            from apps.governance.refresh_progress import RefreshProgress
            if connection.vendor=='postgresql':
                with connection.cursor() as cursor:
                    cursor.execute("SELECT set_config('application_name',%s,false),pg_backend_pid()",['nexora-refresh:'+str(scope.pk)[:8]])
                    self.stderr.write('Database session PID: '+str(cursor.fetchone()[1]))
            with RefreshProgress(self.stderr) as progress,connection.execute_wrapper(progress.query):
                progress('ตรวจแผนและล้างข้อมูลตามรายการที่ยืนยัน')
                run=execute(actor,scope,seed=lambda a,s:seed_workspace(a,s,progress=progress),expected_hash=o['plan_hash'],confirmation=o['confirm'],reason=o['reason'])
                progress('ฐานข้อมูลบันทึกสำเร็จแล้ว')
            self.stdout.write(json.dumps({'status':run.status,'refresh_id':str(run.pk),'summary':run.summary},ensure_ascii=False,indent=2))
        except (ValidationError,PermissionDenied,AccessScope.DoesNotExist,get_user_model().DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc
