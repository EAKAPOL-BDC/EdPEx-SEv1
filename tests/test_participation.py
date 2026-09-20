"""Isolated PostgreSQL tests: proofs, atomicity, privacy, authorization and HTTP."""
import copy
import json
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.test import TestCase, Client, override_settings
from django.utils import timezone
from apps.participation import services as proofs
from apps.participation.models import ReceiptPolicy, ParticipationReceipt, VerifierClient, VerifierGrant, ReceiptRedemption
from apps.surveys import services as surveys
from apps.surveys.models import Invitation, AnonymousSession, AnonymousResponse
from apps.auditlog.models import AuditEvent
from tests.test_surveys import setup_surveys


@override_settings(NEXORA_PARTICIPATION_ENABLED=True, SURVEY_ALLOW_TEST_HTTP=True)
class ParticipationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.f = setup_surveys(only={'F01'})
        cls.binding = cls.f.selected['F01']
        cls.policy = proofs.configure_policy(cls.f.actor, cls.binding.pk, activity_code='f01-participation',
            label_th='เข้าร่วมแบบประเมิน F01', label_en='F01 participation',
            expires_at=timezone.now()+timedelta(days=30), workload=True, prize=True)
        cls.consumer, cls.api_key = proofs.create_client(cls.f.actor, cls.f.scope, name='workload-test',
            expires_at=timezone.now()+timedelta(days=60))
        proofs.grant_client(cls.f.actor, cls.consumer.pk, cls.policy.pk, 'workload', can_redeem=True)
        proofs.grant_client(cls.f.actor, cls.consumer.pk, cls.policy.pk, 'prize', can_redeem=True)
        cls.payload = copy.deepcopy(cls.f.answers['F01'])
        cls.payload['F01-P03'] = {'status':'answered', 'value':'option_1'}
        cls.payload['F01-C02'] = {'status':'answered', 'value':['option_3']}

    def prepared(self, n=0):
        raw = surveys.issue(self.f.actor, self.binding.pk, self.f.members['F01'][n].pk)
        session = surveys.exchange(raw)
        return session, proofs.prepare(session)

    def issued(self, n=0):
        session, candidate = self.prepared(n)
        result = proofs.submit(session, self.payload, 0, candidate['issuance_ticket'])
        return candidate['receipt_token'], result

    def assert_error(self, code, callback):
        with self.assertRaises(proofs.ReceiptError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_only_committed_submission_has_proof_and_no_answer_link(self):
        session, c = self.prepared()
        self.assertEqual(proofs.holder_status(c['receipt_token']), {'status':'not_confirmed'})
        self.assertEqual(ParticipationReceipt.objects.count(), 0)
        result = proofs.submit(session, self.payload, 0, c['issuance_ticket'])
        self.assertEqual(result['status'], 'issued')
        self.assertEqual(result['realm'], 'test')
        self.assertEqual(AnonymousResponse.objects.count(), 1)
        self.assertTrue(Invitation.objects.get().spent)
        self.assertFalse(AnonymousSession.objects.exists())
        self.assertEqual(proofs.holder_status(c['receipt_token'])['status'], 'issued')
        self.assertFalse({'answer_id','response_id','receipt_id','group','member','submitted_at','score','answers','token'} & result.keys())
        for model in (ParticipationReceipt, ReceiptRedemption):
            names={f.name for f in model._meta.fields}
            self.assertFalse({'member','user','invitation','response','answer','email','ip','issued_at','created_at'} & names)
        stored = json.dumps(list(ParticipationReceipt.objects.values()), default=str)
        self.assertNotIn(c['receipt_token'], stored)
        self.assertNotIn(session, stored)
        self.assertNotIn(str(AnonymousResponse.objects.get().pk), stored)
        self.assertNotIn(c['receipt_token'], json.dumps(list(AuditEvent.objects.values()), default=str))

    def test_missing_answers_no_proof_no_spend_and_optional_suggestions(self):
        session,c = self.prepared()
        error=self.assert_error('required_answers_missing', lambda: proofs.submit(session,{},0,c['issuance_ticket']))
        self.assertIn('F01-P03', error.missing)
        self.assertNotIn('F01-O01', error.missing)
        self.assertFalse(ParticipationReceipt.objects.exists())
        self.assertFalse(Invitation.objects.get().spent)
        # All required, suggestions absent.
        self.assertEqual(proofs.submit(session,self.payload,0,c['issuance_ticket'])['status'],'issued')

    def test_conditional_text_required_and_explicit_non_assessment_valid(self):
        session,c=self.prepared()
        payload=copy.deepcopy(self.payload)
        payload['F01-D01']={'status':'answered','value':'Y'}
        error=self.assert_error('required_answers_missing',lambda:proofs.submit(session,payload,0,c['issuance_ticket']))
        self.assertIn('F01-D01-FIX',error.missing)
        payload=copy.deepcopy(self.payload)
        payload['F01-S01']={'status':'unable_to_assess'}
        self.assertEqual(proofs.submit(session,payload,0,c['issuance_ticket'])['status'],'issued')

    def test_failure_at_receipt_write_rolls_back_response_and_invitation(self):
        session,c=self.prepared()
        with patch('apps.participation.services.ParticipationReceipt.objects.create',side_effect=IntegrityError('synthetic failure')):
            with self.assertRaises(IntegrityError):proofs.submit(session,self.payload,0,c['issuance_ticket'])
        self.assertFalse(AnonymousResponse.objects.exists())
        self.assertFalse(ParticipationReceipt.objects.exists())
        self.assertFalse(Invitation.objects.get().spent)
        self.assertTrue(AnonymousSession.objects.exists())
        self.assertEqual(proofs.holder_status(c['receipt_token'])['status'],'not_confirmed')
        proofs.submit(session,self.payload,0,c['issuance_ticket'])
        self.assertEqual(ParticipationReceipt.objects.count(),1)

    def test_lost_acknowledgement_recovered_without_second_submission(self):
        session,c=self.prepared()
        proofs.submit(session,self.payload,0,c['issuance_ticket'])
        self.assertEqual(proofs.holder_status(c['receipt_token'])['status'],'issued')
        with self.assertRaises(surveys.SurveyConflict):proofs.submit(session,self.payload,0,c['issuance_ticket'])
        self.assertEqual(AnonymousResponse.objects.count(),1)
        # A used candidate cannot spend another invitation.
        other,_=self.prepared(1)
        self.assert_error('candidate_already_used',lambda:proofs.submit(other,self.payload,0,c['issuance_ticket']))
        self.assertEqual(Invitation.objects.filter(spent=True).count(),1)

    def test_forged_and_expired_ticket_do_not_issue(self):
        session,c=self.prepared()
        self.assert_error('invalid_ticket',lambda:proofs.submit(session,self.payload,0,c['issuance_ticket']+'x'))
        with patch('django.core.signing.time.time',return_value=timezone.now().timestamp()+7201):
            self.assert_error('invalid_ticket',lambda:proofs.submit(session,self.payload,0,c['issuance_ticket']))
        self.assertFalse(ParticipationReceipt.objects.exists())

    def test_verify_is_read_only_redeem_once_and_idempotent(self):
        token,_=self.issued()
        for _ in range(2):self.assertEqual(proofs.verify(self.api_key,self.policy.pk,'workload',token)['status'],'valid')
        self.assertFalse(ReceiptRedemption.objects.exists())
        key=str(uuid.uuid4())
        first=proofs.redeem(self.api_key,self.policy.pk,'workload',token,key)
        retry=proofs.redeem(self.api_key,self.policy.pk,'workload',token,key)
        self.assertEqual(first['redemption_reference'],retry['redemption_reference'])
        self.assertTrue(retry['replayed'])
        self.assertEqual(ReceiptRedemption.objects.count(),1)
        self.assertEqual(proofs.verify(self.api_key,self.policy.pk,'workload',token)['status'],'already_redeemed')
        self.assert_error('already_redeemed',lambda:proofs.redeem(self.api_key,self.policy.pk,'workload',token,str(uuid.uuid4())))
        self.assertNotIn(key,json.dumps(list(ReceiptRedemption.objects.values()),default=str))

    def test_same_idempotency_key_cannot_be_reused_for_other_receipt(self):
        token,_=self.issued();other,_=self.issued(1);key=str(uuid.uuid4())
        proofs.redeem(self.api_key,self.policy.pk,'workload',token,key)
        self.assert_error('idempotency_conflict',lambda:proofs.redeem(self.api_key,self.policy.pk,'workload',other,key))
        self.assertEqual(proofs.verify(self.api_key,self.policy.pk,'workload',other)['status'],'valid')
        self.assert_error('invalid_idempotency_key',lambda:proofs.redeem(self.api_key,self.policy.pk,'workload',other,'employee-123'))

    def test_prize_gated_until_closed_and_verifier_grants_enforced(self):
        token,_=self.issued()
        self.assertEqual(proofs.verify(self.api_key,self.policy.pk,'prize',token)['status'],'not_open')
        self.assert_error('not_open',lambda:proofs.redeem(self.api_key,self.policy.pk,'prize',token,str(uuid.uuid4())))
        VerifierGrant.objects.filter(client=self.consumer,purpose='workload').update(can_redeem=False)
        self.assertEqual(proofs.verify(self.api_key,self.policy.pk,'workload',token)['status'],'valid')
        self.assert_error('forbidden',lambda:proofs.redeem(self.api_key,self.policy.pk,'workload',token,str(uuid.uuid4())))
        VerifierGrant.objects.filter(client=self.consumer,purpose='workload').update(active=False)
        self.assert_error('forbidden',lambda:proofs.verify(self.api_key,self.policy.pk,'workload',token))

    def test_prize_after_close_is_separate_from_workload(self):
        from apps.rounds.services import transition_round
        token,_=self.issued()
        transition_round(self.f.actor,self.binding.collection_round,'closed',reason='Synthetic test closure')
        # An early manual close alone must not start prize claims.
        self.assertEqual(proofs.verify(self.api_key,self.policy.pk,'prize',token)['status'],'not_open')
        with patch('apps.participation.services.timezone.now',return_value=timezone.now()+timedelta(days=3)):
            result=proofs.redeem(self.api_key,self.policy.pk,'prize',token,str(uuid.uuid4()))
            self.assertEqual(result['status'],'redeemed')
            self.assertEqual(proofs.verify(self.api_key,self.policy.pk,'workload',token)['status'],'valid')

    def test_revoke_expire_disable_and_reconcile_previous_result(self):
        token,_=self.issued();key=str(uuid.uuid4())
        result=proofs.redeem(self.api_key,self.policy.pk,'workload',token,key)
        proofs.revoke_receipt(self.f.actor,self.policy.pk,token)
        self.assertEqual(proofs.holder_status(token)['status'],'revoked')
        retry=proofs.redeem(self.api_key,self.policy.pk,'workload',token,key)
        self.assertEqual(retry['redemption_reference'],result['redemption_reference'])
        self.assertEqual(retry['current_status'],'revoked')
        self.assert_error('revoked',lambda:proofs.redeem(self.api_key,self.policy.pk,'workload',token,str(uuid.uuid4())))
        other,_=self.issued(1)
        with patch('apps.participation.services.timezone.now',return_value=timezone.now()+timedelta(days=31)):
            self.assertEqual(proofs.verify(self.api_key,self.policy.pk,'workload',other)['status'],'expired')
        proofs.disable_client(self.f.actor,self.consumer.pk)
        self.assert_error('unauthorized',lambda:proofs.verify(self.api_key,self.policy.pk,'workload',other))

    def test_wrong_scope_and_realm_cannot_inspect_receipts(self):
        token,_=self.issued()
        outsider,key=proofs.create_client(self.f.other,self.f.foreign,name='other',expires_at=timezone.now()+timedelta(days=2))
        self.assert_error('forbidden',lambda:proofs.verify(key,self.policy.pk,'workload',token))
        with self.assertRaises(PermissionDenied):proofs.grant_client(self.f.other,outsider.pk,self.policy.pk,'workload')
        with override_settings(NEXORA_PARTICIPATION_ALLOW_LIVE=True):
            live,key=proofs.create_client(self.f.actor,self.f.scope,name='live',realm='live',expires_at=timezone.now()+timedelta(days=2))
            self.assert_error('scope_or_realm_mismatch',lambda:proofs.grant_client(self.f.actor,live.pk,self.policy.pk,'workload'))
            self.assert_error('forbidden',lambda:proofs.verify(key,self.policy.pk,'workload',token))

    def test_key_rotation_invalidates_old_key_and_never_audits_secrets(self):
        token,_=self.issued()
        with self.assertRaises(PermissionDenied):proofs.rotate_client_key(self.f.other,self.consumer.pk)
        new_key=proofs.rotate_client_key(self.f.actor,self.consumer.pk)
        self.assert_error('unauthorized',lambda:proofs.verify(self.api_key,self.policy.pk,'workload',token))
        self.assertEqual(proofs.verify(new_key,self.policy.pk,'workload',token)['status'],'valid')
        events=json.dumps(list(AuditEvent.objects.values()),default=str)
        for secret in (new_key,self.api_key,token):self.assertNotIn(secret,events)

    def test_database_guards_prevent_history_rewrites(self):
        token,_=self.issued();proofs.redeem(self.api_key,self.policy.pk,'workload',token,str(uuid.uuid4()))
        for op in [lambda:ReceiptPolicy.objects.filter(pk=self.policy.pk).update(workload=False),
                   lambda:ParticipationReceipt.objects.update(token_hash='0'*64),
                   lambda:ReceiptRedemption.objects.update(purpose='prize'),
                   lambda:VerifierClient.objects.filter(pk=self.consumer.pk).update(realm='live')]:
            with self.assertRaises(IntegrityError),transaction.atomic():op()

    def test_anonymous_http_csrf_prepare_submit_recover(self):
        client=Client(enforce_csrf_checks=True)
        client.get('/survey/')
        csrf=client.cookies['csrftoken'].value
        session,_=self.prepared();client.cookies['nexora_survey_session']=session
        url='/survey/participation/'
        self.assertEqual(client.post(url+'prepare/',{},content_type='application/json').status_code,403)
        prepared=client.post(url+'prepare/',{},content_type='application/json',HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(prepared.status_code,200,prepared.content)
        candidate=prepared.json()
        body={'answers':{},'revision':0,'issuance_ticket':candidate['issuance_ticket'],'confirmed':True}
        missing=client.post(url+'submit/',body,content_type='application/json',HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(missing.status_code,422)
        self.assertEqual(missing.json()['error'],'required_answers_missing')
        body['answers']=self.payload
        response=client.post(url+'submit/',body,content_type='application/json',HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code,201,response.content)
        self.assertEqual(response.json()['status'],'issued')
        self.assertNotIn(candidate['receipt_token'],response.content.decode())
        recovery=client.post(url+'status/',{'receipt_token':candidate['receipt_token']},content_type='application/json',HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(recovery.json()['status'],'issued')
        self.assertIn('no-store',recovery['Cache-Control'])
        self.assertEqual(recovery['Referrer-Policy'],'no-referrer')

    def test_verifier_http_requires_key_and_rejects_identity_payloads(self):
        token,_=self.issued();client=Client(enforce_csrf_checks=True);client.force_login(self.f.actor)
        url='/participation/v1/verify/'
        body={'policy_id':str(self.policy.pk),'purpose':'workload','receipt_token':token}
        self.assertEqual(client.post(url,body,content_type='application/json').status_code,401)
        response=client.post(url,body,content_type='application/json',HTTP_AUTHORIZATION='Bearer '+self.api_key)
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['status'],'valid')
        bad=client.post(url,{**body,'employee_id':'PRIVATE-1'},content_type='application/json',HTTP_AUTHORIZATION='Bearer '+self.api_key)
        self.assertEqual(bad.status_code,422)
        self.assertNotIn(b'PRIVATE-1',bad.content)
        self.assertEqual(client.get(url).status_code,405)
        self.assertFalse(ReceiptRedemption.objects.exists())
        redeemed=client.post('/participation/v1/redeem/',{**body,'idempotency_key':str(uuid.uuid4())},
            content_type='application/json',HTTP_AUTHORIZATION='Bearer '+self.api_key)
        self.assertEqual(redeemed.status_code,200,redeemed.content)
        self.assertEqual(redeemed.json()['status'],'redeemed')
        self.assertNotIn(token,redeemed.content.decode())

    @override_settings(DEBUG=True)
    def test_failure_messages_do_not_echo_secrets_or_stack(self):
        with patch('apps.participation.web.services.authenticate',side_effect=RuntimeError('DO-NOT-EXPOSE-SECRET')):
            response=Client().post('/participation/v1/verify/',{},content_type='application/json',HTTP_AUTHORIZATION='Bearer private')
        self.assertEqual(response.status_code,503)
        self.assertNotIn(b'DO-NOT-EXPOSE-SECRET',response.content)
        with patch('apps.participation.web.surveys.throttle',return_value=False):
            response=Client().post('/participation/v1/verify/',{},content_type='application/json')
            self.assertEqual(response.status_code,429)
            self.assertEqual(response['Retry-After'],'600')

    @override_settings(NEXORA_PARTICIPATION_ENABLED=False)
    def test_feature_is_off_by_default(self):
        self.assertEqual(Client().post('/participation/v1/verify/',{},content_type='application/json').status_code,404)

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections, connections
from django.test import TransactionTestCase


@override_settings(NEXORA_PARTICIPATION_ENABLED=True)
class ParticipationRaceTests(TransactionTestCase):
    """Real commits and separate connections; not simulated interleaving."""
    def test_duplicate_submit_and_concurrent_redemption(self):
        f=setup_surveys(only={'F01'})
        binding=f.selected['F01']
        policy=proofs.configure_policy(f.actor,binding.pk,activity_code='race-test',label_th='ทดสอบ',label_en='Test',
            expires_at=timezone.now()+timedelta(days=30),workload=True)
        consumer,key=proofs.create_client(f.actor,f.scope,name='race-client',expires_at=timezone.now()+timedelta(days=30))
        proofs.grant_client(f.actor,consumer.pk,policy.pk,'workload',can_redeem=True)
        payload=copy.deepcopy(f.answers['F01'])
        payload.update({'F01-P03':{'status':'answered','value':'option_1'},'F01-C02':{'status':'answered','value':['option_3']}})
        raw=surveys.issue(f.actor,binding.pk,f.members['F01'][0].pk)
        session=surveys.exchange(raw);candidate=proofs.prepare(session)

        def race(functions):
            barrier=Barrier(2)
            def worker(fn):
                close_old_connections()
                try:
                    with connections['default'].cursor() as cursor:
                        cursor.execute("SET statement_timeout = '10s'")
                    barrier.wait(timeout=10)
                    try:return fn()
                    except proofs.ReceiptError as exc:return {'error':exc.code}
                    except surveys.SurveyConflict:return {'error':'survey_conflict'}
                finally:connections['default'].close()
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=[pool.submit(worker,fn) for fn in functions]
                return [future.result(timeout=30) for future in results]

        results=race([lambda:proofs.submit(session,payload,0,candidate['issuance_ticket'])]*2)
        self.assertEqual(sum(r.get('status')=='issued' for r in results),1,results)
        self.assertEqual(AnonymousResponse.objects.count(),1)
        self.assertEqual(ParticipationReceipt.objects.count(),1)
        self.assertEqual(Invitation.objects.filter(spent=True).count(),1)
        token=candidate['receipt_token'];idempotency=str(uuid.uuid4())
        results=race([lambda:proofs.redeem(key,policy.pk,'workload',token,idempotency)]*2)
        self.assertEqual({r.get('status') for r in results},{'redeemed'},results)
        self.assertEqual({r['replayed'] for r in results},{True,False})
        self.assertEqual(len({r['redemption_reference'] for r in results}),1)
        self.assertEqual(ReceiptRedemption.objects.count(),1)

        raw=surveys.issue(f.actor,binding.pk,f.members['F01'][1].pk)
        session=surveys.exchange(raw);other=proofs.prepare(session)
        proofs.submit(session,payload,0,other['issuance_ticket'])
        c2,k2=proofs.create_client(f.actor,f.scope,name='race-client-two',expires_at=timezone.now()+timedelta(days=30))
        proofs.grant_client(f.actor,c2.pk,policy.pk,'workload',can_redeem=True)
        results=race([lambda:proofs.redeem(key,policy.pk,'workload',other['receipt_token'],str(uuid.uuid4())),
                      lambda:proofs.redeem(k2,policy.pk,'workload',other['receipt_token'],str(uuid.uuid4()))])
        self.assertEqual(sum(r.get('status')=='redeemed' for r in results),1,results)
        self.assertEqual(sum(r.get('error')=='already_redeemed' for r in results),1,results)
        self.assertEqual(ReceiptRedemption.objects.count(),2)

from django.test import SimpleTestCase, RequestFactory
from apps.participation import web as proof_web


@override_settings(NEXORA_PARTICIPATION_ENABLED=True, ALLOWED_HOSTS=['*'])
class ParticipationHTTPGuards(SimpleTestCase):
    def test_non_loopback_http_rejected_and_errors_have_privacy_headers(self):
        request=RequestFactory().post('/participation/v1/verify/',{},content_type='application/json',
            HTTP_HOST='survey.example',REMOTE_ADDR='203.0.113.8')
        response=proof_web.verify(request)
        self.assertEqual(response.status_code,400)
        self.assertEqual(json.loads(response.content)['error'],'https_required')
        self.assertIn('no-store',response['Cache-Control'])
        self.assertEqual(response['Referrer-Policy'],'no-referrer')

    def test_malformed_verification_fields_fail_closed_without_500(self):
        with patch('apps.participation.web.surveys.throttle',return_value=True),patch('apps.participation.web.services.authenticate'):
            for bad in [{'policy_id':str(uuid.uuid4()),'purpose':[],'receipt_token':'private'},
                        {'policy_id':{},'purpose':'workload','receipt_token':'private'}]:
                request=RequestFactory().post('/participation/v1/verify/',bad,content_type='application/json',
                    secure=True,HTTP_HOST='survey.example',HTTP_AUTHORIZATION='Bearer private')
                response=proof_web.verify(request)
                self.assertEqual(response.status_code,422)
                self.assertNotIn(b'private',response.content)
