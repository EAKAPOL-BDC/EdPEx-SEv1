from unittest.mock import patch
from django.test import TestCase, Client
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import connection, transaction, IntegrityError
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import AccessScope, Role, RoleAssignment, Membership
from apps.accounts.management.commands.provision_system_administrator import PERMISSIONS
from apps.calculations.admin_review import can_self_review, PREFIX
from apps.calculations.models import ResultDecision
from apps.calculations.review import decide_results
from tests.test_operator_web import OperatorResultTests

class AdminSelfReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        original=AccessScope.objects.create
        def create(**kw):
            if kw.get('code')=='SYNTHETIC':kw['id']='fc064809-6564-4f74-b303-c32026f82511'
            return original(**kw)
        with patch.object(AccessScope.objects,'create',side_effect=create):
            OperatorResultTests.setUpTestData.__func__(cls)
        cls.user=cls.f.analyst
        cls.user.username='edpexadmin';cls.user.is_superuser=True;cls.user.save()
        role=Role.objects.create(code='system-administrator-v1',permissions=PERMISSIONS)
        cls.grant=RoleAssignment.objects.create(role=role,scope=cls.f.scope,
            membership=Membership.objects.get(user=cls.user,organization=cls.f.scope.organization))
    make_run=OperatorResultTests.make_run
    request_review=OperatorResultTests.request_review
    def test_admin_self_review_ui_service_and_audit(self):
        run=self.make_run();review=self.request_review(run)
        client=Client();client.force_login(self.user)
        response=client.get(reverse('operator-run',kwargs={'scope_id':self.f.scope.pk,'run_id':run}))
        self.assertTrue(response.context['can_decide'])
        self.assertContains(response,'ใช้ข้อยกเว้นผู้ดูแลระบบ')
        result=decide_results(self.user,run_id=run,outcome='approved',reason='System recovery',reviewed_token=review['review_token'])
        self.assertEqual(result['status'],'approved')
        self.assertTrue(ResultDecision.objects.get().reason.startswith(PREFIX))
        self.assertTrue(decide_results(self.user,run_id=run,outcome='approved',reason='System recovery',reviewed_token=review['review_token'])['reused'])
        from apps.auditlog.models import AuditEvent
        self.assertTrue(AuditEvent.objects.filter(action='result.approved',metadata__administrator_self_review=True).exists())
    def test_revoked_and_other_users_are_not_exempt(self):
        self.assertTrue(can_self_review(self.user,self.f.scope))
        self.assertFalse(can_self_review(self.f.actor,self.f.scope))
        self.grant.revoked_at=timezone.now();self.grant.save()
        self.assertFalse(can_self_review(self.user,self.f.scope))
        run=self.make_run();review=self.request_review(run)
        with self.assertRaises((ValidationError, PermissionDenied)):
            decide_results(self.user,run_id=run,outcome='approved',reason='Not authorized',reviewed_token=review['review_token'])
    def test_database_rejects_self_review_without_marker_and_wrong_token(self):
        run=self.make_run();review=self.request_review(run)
        from apps.calculations.models import ResultReviewRequest
        rr=ResultReviewRequest.objects.get(run_id=run)
        for reason, token in [('Missing marker',review['review_token']),(PREFIX+'Recovery','0'*64)]:
            with self.assertRaises(IntegrityError),transaction.atomic():
                import uuid
                with connection.cursor() as cursor:
                    cursor.execute("INSERT INTO calculations_resultdecision (id, created_at, review_id, actor_id, outcome, reason, reviewed_token, previous_approval_id) VALUES (%s, %s, %s, %s, 'approved', %s, %s, NULL)",[uuid.uuid4(),timezone.now(),rr.pk,self.user.pk,reason,token])
