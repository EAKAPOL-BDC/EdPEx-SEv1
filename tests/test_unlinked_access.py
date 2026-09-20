import json
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, TransactionTestCase, Client, override_settings
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction, connections, close_old_connections
from django.utils import timezone
from apps.participation import admission, services as proofs
from apps.participation.models import AccessPool, AccessPass, AccessSession, ParticipationReceipt
from apps.surveys import services as surveys
from apps.surveys.models import Invitation, AnonymousResponse
from apps.surveys.web import COOKIE
from apps.auditlog.models import AuditEvent
from tests.test_surveys import setup_surveys


def fixture():
    f=setup_surveys(only={'F01'},data_kind='synthetic')
    f.binding=f.selected['F01']
    proofs.configure_policy(f.actor,f.binding.pk,activity_code='unlinked-test',label_th='ทดสอบ',label_en='Test',expires_at=timezone.now()+timedelta(days=30),workload=True)
    admission.configure(f.actor,f.binding.pk,5)
    f.payload=dict(f.answers['F01'])
    f.payload['F01-P03']={'status':'answered','value':'option_1'}
    f.payload['F01-C02']={'status':'answered','value':['option_3']}
    return f


@override_settings(NEXORA_PARTICIPATION_ENABLED=True,NEXORA_UNLINKED_ACCESS_ENABLED=True,SURVEY_ALLOW_TEST_HTTP=True)
class UnlinkedAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):cls.f=fixture()

    def issue(self):
        raw=admission.mint(self.f.actor,self.f.binding.pk,1)[0]
        secret=admission.exchange(raw)
        return raw,secret,proofs.prepare(secret)

    def test_no_recipient_fields_or_raw_secrets_and_no_legacy_invitation(self):
        raw,secret,candidate=self.issue()
        self.assertFalse(Invitation.objects.exists())
        self.assertEqual({f.name for f in AccessPass._meta.fields},{'id','binding','token_hash','expires_at','spent','revoked'})
        self.assertEqual({f.name for f in AccessSession._meta.fields},{'id','invitation','secret_hash','expires_at','revision'})
        audit=json.dumps(list(AuditEvent.objects.values()),default=str)
        for value in [raw,secret,candidate['receipt_token'],str(AccessPass.objects.get().pk)]:self.assertNotIn(value,audit)
        stored=json.dumps(list(AccessPass.objects.values())+list(AccessSession.objects.values()),default=str)
        self.assertNotIn(raw,stored);self.assertNotIn(secret,stored)

    def test_atomic_issue_spend_and_receipt_then_reuse_rejected(self):
        raw,secret,candidate=self.issue()
        result=proofs.submit(secret,self.f.payload,0,candidate['issuance_ticket'])
        self.assertEqual(result['status'],'issued');self.assertEqual(proofs.holder_status(candidate['receipt_token'])['status'],'issued')
        self.assertEqual(AnonymousResponse.objects.count(),1);self.assertEqual(ParticipationReceipt.objects.count(),1)
        self.assertTrue(AccessPass.objects.get().spent);self.assertFalse(AccessSession.objects.exists())
        self.assertFalse(Invitation.objects.exists())
        with self.assertRaises(surveys.SurveyConflict):admission.exchange(raw)
        with self.assertRaises(surveys.SurveyConflict):proofs.submit(secret,self.f.payload,0,candidate['issuance_ticket'])

    def test_receipt_failure_rolls_back_pass_and_response(self):
        raw,secret,candidate=self.issue()
        with patch('apps.participation.services.ParticipationReceipt.objects.create',side_effect=IntegrityError('synthetic')):
            with self.assertRaises(IntegrityError):proofs.submit(secret,self.f.payload,0,candidate['issuance_ticket'])
        self.assertFalse(AccessPass.objects.get().spent);self.assertFalse(AnonymousResponse.objects.exists())
        self.assertTrue(AccessSession.objects.exists());self.assertEqual(proofs.holder_status(candidate['receipt_token'])['status'],'not_confirmed')

    def test_missing_or_changed_context_does_not_spend(self):
        _,secret,candidate=self.issue()
        for payload in ({},dict(self.f.payload,**{'F01-P01':{'status':'answered','value':'C2'}})):
            from django.core.exceptions import ValidationError
            with self.assertRaises((proofs.ReceiptError,ValidationError)):proofs.submit(secret,payload,0,candidate['issuance_ticket'])
        self.assertFalse(AccessPass.objects.get().spent)

    def test_session_rotation_disable_and_feature_gate(self):
        raw,old,_=self.issue();new=admission.exchange(raw)
        with self.assertRaises(surveys.SurveyConflict):surveys.read_session(old)
        self.assertEqual(surveys.read_session(new).invitation.binding_id,self.f.binding.pk)
        admission.set_enabled(self.f.actor,self.f.binding.pk,False)
        with self.assertRaises(surveys.SurveyConflict):admission.exchange(raw)
        self.assertFalse(AccessSession.objects.exists())
        with override_settings(NEXORA_UNLINKED_ACCESS_ENABLED=False):
            with self.assertRaises(proofs.ReceiptError):admission.mint(self.f.actor,self.f.binding.pk,1)

    def test_scope_capacity_and_legacy_interoperability(self):
        with self.assertRaises(PermissionDenied):admission.mint(self.f.other,self.f.binding.pk,1)
        with self.assertRaises(proofs.ReceiptError):admission.mint(self.f.actor,self.f.binding.pk,6)
        surveys.issue(self.f.actor,self.f.binding.pk,self.f.members['F01'][0].pk)
        admission.mint(self.f.actor,self.f.binding.pk,4)
        with self.assertRaises(proofs.ReceiptError):admission.mint(self.f.actor,self.f.binding.pk,1)
        with self.assertRaises(IntegrityError),transaction.atomic():surveys.issue(self.f.actor,self.f.binding.pk,self.f.members['F01'][1].pk)
        self.assertEqual(AccessPass.objects.count(),4)

    def test_database_blocks_unbalanced_spend_and_rewriting(self):
        self.issue()
        with self.assertRaises(IntegrityError),transaction.atomic():AccessPass.objects.update(token_hash='b'*64)
        with self.assertRaises(IntegrityError),transaction.atomic():AccessPool.objects.update(capacity=20)
        with self.assertRaises(IntegrityError),transaction.atomic():
            AccessPass.objects.update(spent=True)
            with connections['default'].cursor() as cursor:cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
        self.assertFalse(AccessPass.objects.get().spent)

    def test_aggregate_population_can_open_without_any_recipient_roster(self):
        from apps.surveys.operator import save_round
        from apps.rounds.services import transition_round
        b=self.f.binding;r=b.collection_round;p=b.survey_profile
        data={key:getattr(r,key) for key in ('owner','open_at','due_at','close_at','period')}
        data.update(code='Aggregate-only synthetic',bundle=b.translation_bundle,privacy_notice='Synthetic privacy notice',
                    group_code='C1',counting_unit='person',context_th='บริบทสมมุติ',context_en='Synthetic context',assessor_role='',study_options=p.study_options)
        new=save_round(self.f.actor,self.f.scope,data,data_kind='synthetic')
        snapshot=admission.prepare_population(self.f.actor,new.pk,3,source_title='Synthetic aggregate count',source_reference='Synthetic count only')
        self.assertEqual(snapshot.members.count(),0)
        proofs.configure_policy(self.f.actor,new.pk,activity_code='aggregate-only',label_th='ทดสอบ',label_en='Test',expires_at=timezone.now()+timedelta(days=30),workload=True)
        admission.configure(self.f.actor,new.pk,3)
        ready=transition_round(self.f.actor,new.collection_round,'ready')
        with self.assertRaises(IntegrityError),transaction.atomic():
            transition_round(self.f.actor,ready,'draft',reason='Synthetic attempt to reopen pinned context')
        transition_round(self.f.actor,ready,'open')
        raw=admission.mint(self.f.actor,new.pk,1)[0];secret=admission.exchange(raw);candidate=proofs.prepare(secret)
        self.assertEqual(proofs.submit(secret,self.f.payload,0,candidate['issuance_ticket'])['status'],'issued')
        self.assertFalse(Invitation.objects.filter(binding=new).exists())
        self.assertEqual(snapshot.members.count(),0)

    def test_http_entry_csrf_no_pii_and_legacy_route_cannot_bypass(self):
        raw=admission.mint(self.f.actor,self.f.binding.pk,1)[0]
        c=Client(enforce_csrf_checks=True);page=c.get('/survey/entry/')
        self.assertEqual(page.status_code,200);self.assertNotIn(raw.encode(),page.content)
        import re
        data=json.loads(re.search(r'id="preview-data" type="application/json">(.*?)</script>',page.content.decode(),re.S)[1])
        def post(payload,csrf=True):return c.post('/survey/participation/enter/',json.dumps(payload),content_type='application/json',**({'HTTP_X_CSRFTOKEN':data['runtime']['csrf']} if csrf else {}))
        self.assertEqual(post({'invitation_code':raw},False).status_code,403)
        self.assertEqual(post({'invitation_code':raw,'name':'unwanted'}).status_code,422)
        result=post({'invitation_code':raw});self.assertEqual(result.status_code,200)
        self.assertNotIn(raw,result.content.decode());self.assertTrue(result.cookies[COOKIE]['httponly'])
        form=c.get('/survey/participation/form/?lang=en');self.assertEqual(form.status_code,200)
        self.assertNotIn(raw.encode(),form.content);self.assertNotIn(b'PRIVATE-',form.content)
        config=json.loads(re.search(r'id="preview-data" type="application/json">(.*?)</script>',form.content.decode(),re.S)[1])['runtime']
        self.assertTrue(config['unlinked']);self.assertEqual(config['locale'],'en')
        self.assertRedirects(c.get('/survey/answer/'),'/survey/participation/form/',fetch_redirect_response=False)


@override_settings(NEXORA_PARTICIPATION_ENABLED=True,NEXORA_UNLINKED_ACCESS_ENABLED=True)
class UnlinkedRaceTests(TransactionTestCase):
    def test_simultaneous_submissions_and_mints(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        f=fixture();raw=admission.mint(f.actor,f.binding.pk,1)[0];secret=admission.exchange(raw);candidate=proofs.prepare(secret)
        def race(callback):
            barrier=Barrier(2)
            def worker():
                close_old_connections()
                try:
                    with connections['default'].cursor() as cur:cur.execute("SET statement_timeout = '15s'")
                    barrier.wait(timeout=10)
                    try:return callback()
                    except (proofs.ReceiptError,surveys.SurveyConflict):return None
                finally:connections['default'].close()
            with ThreadPoolExecutor(max_workers=2) as pool:
                pending=[pool.submit(worker) for _ in range(2)]
                return [x.result(timeout=35) for x in pending]
        outcomes=race(lambda:proofs.submit(secret,f.payload,0,candidate['issuance_ticket']))
        self.assertEqual(sum(x is not None for x in outcomes),1)
        self.assertEqual(AnonymousResponse.objects.count(),1);self.assertEqual(ParticipationReceipt.objects.count(),1)
        outcomes=race(lambda:admission.mint(f.actor,f.binding.pk,4))
        self.assertEqual(sum(x is not None for x in outcomes),1);self.assertEqual(AccessPass.objects.count(),5)
