import json
import re
from urllib.parse import urlencode
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, Client, override_settings
from django.utils import timezone
from apps.participation import services
from apps.participation.presentation import form_data
from apps.surveys import services as surveys
from apps.surveys.web import COOKIE
from tests.test_surveys import setup_surveys


@override_settings(NEXORA_PARTICIPATION_ENABLED=True,SURVEY_ALLOW_TEST_HTTP=True)
class ParticipationUITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.f=setup_surveys(only={'F01'},data_kind='synthetic')
        cls.binding=cls.f.selected['F01']
        cls.policy=services.configure_policy(cls.f.actor,cls.binding.pk,activity_code='ui-test',label_th='ทดสอบ',label_en='Test',expires_at=timezone.now()+timedelta(days=30),workload=True)

    def client_session(self):
        raw=surveys.issue(self.f.actor,self.binding.pk,self.f.members['F01'][0].pk)
        client=Client(enforce_csrf_checks=True)
        client.cookies[COOKIE]=surveys.exchange(raw)
        return client

    def test_schema_includes_conditionals_but_never_identity_scores_or_keys(self):
        data=form_data(self.binding.survey_profile)
        self.assertEqual(len(data['questions']),35)
        for q in data['questions']:
            self.assertEqual(set(q),{'id','text','text_en','type','fixed','fixed_en','rule','options'})
            for o in q['options']:self.assertEqual(set(o),{'value','label','label_en','status'})
        self.assertIn('F01-D01-FIX',{q['id'] for q in data['questions']})
        self.assertNotIn('PRIVATE-',json.dumps(data))
        self.assertEqual(data['group'],'C1')

    def test_page_csrf_csp_session_and_feature_gate(self):
        c=self.client_session();page=c.get('/survey/participation/form/')
        self.assertEqual(page.status_code,200)
        self.assertIn('nonce-',page['Content-Security-Policy'])
        self.assertNotIn('unsafe-inline',page['Content-Security-Policy'])
        self.assertEqual(page['Cache-Control'],'no-store, private')
        self.assertEqual(page['Referrer-Policy'],'same-origin')
        text=page.content.decode();self.assertNotIn('PRIVATE-',text)
        payload=json.loads(re.search(r'id="preview-data" type="application/json">(.*?)</script>',text,re.S)[1])
        self.assertEqual(payload['runtime']['realm'],'test')
        self.assertEqual(c.post('/survey/participation/prepare/',data='{}',content_type='application/json').status_code,403)
        result=c.post('/survey/participation/prepare/',data='{}',content_type='application/json',HTTP_X_CSRFTOKEN=payload['runtime']['csrf'])
        self.assertEqual(result.status_code,200)
        self.assertEqual(c.get('/survey/participation/receipt/').status_code,200)
        with override_settings(NEXORA_PARTICIPATION_ENABLED=False):self.assertEqual(c.get('/survey/participation/form/').status_code,404)

    def test_script_delimiters_escaped_and_unreviewed_wording_fails_closed(self):
        c=self.client_session()
        with patch('apps.participation.presentation.form_data',return_value={'instructions':'</script><script>alert(1)</script>'}):
            result=c.get('/survey/participation/form/')
        self.assertNotIn(b'</script><script>alert',result.content)
        from django.core.exceptions import ValidationError
        with patch('apps.surveys.schema.respondent_schema',side_effect=ValidationError('PRIVATE')):
            result=c.get('/survey/participation/form/')
        self.assertEqual(result.status_code,503);self.assertNotIn(b'PRIVATE',result.content)

    def test_actual_submit_status_and_qr_after_commit(self):
        c=self.client_session();page=c.get('/survey/participation/form/')
        data=json.loads(re.search(r'id="preview-data" type="application/json">(.*?)</script>',page.content.decode(),re.S)[1])
        def post(name,payload):return c.post('/survey/participation/'+name+'/',data=json.dumps(payload),content_type='application/json',HTTP_X_CSRFTOKEN=data['runtime']['csrf'])
        candidate=post('prepare',{}).json();token=candidate['receipt_token']
        self.assertEqual(post('qr',{'receipt_token':token}).status_code,409)
        answers=dict(self.f.answers['F01']);answers['F01-P03']={'status':'answered','value':'option_1'};answers['F01-C02']={'status':'answered','value':['option_3']}
        result=post('submit',{'answers':answers,'revision':0,'issuance_ticket':candidate['issuance_ticket'],'confirmed':True})
        self.assertEqual(result.status_code,201)
        self.assertEqual(post('status',{'receipt_token':token}).json()['status'],'issued')
        qr=post('qr',{'receipt_token':token});self.assertEqual(qr.status_code,200)
        self.assertIn('<svg',qr.json()['svg']);self.assertNotIn(token,qr.json()['svg'])
        self.assertEqual(c.post('/survey/participation/download/',{'receipt_token':token}).status_code,403)
        fields=urlencode({'receipt_token':token,'csrfmiddlewaretoken':data['runtime']['csrf']})
        self.assertEqual(c.post('/survey/participation/download/',fields,content_type='application/x-www-form-urlencoded',HTTP_ORIGIN='null').status_code,403)
        attachment=c.post('/survey/participation/download/',fields,content_type='application/x-www-form-urlencoded',HTTP_ORIGIN='http://testserver')
        self.assertEqual(attachment.status_code,200)
        self.assertIn('attachment;',attachment['Content-Disposition'])
        self.assertIn(b'TEST',attachment.content)
        self.assertNotIn(b'<script',attachment.content)
        self.assertEqual(c.get('/survey/participation/download/').status_code,405)
        self.assertRedirects(c.get('/survey/participation/form/'),'/survey/participation/receipt/',fetch_redirect_response=False)

    def test_existing_invitation_routes_to_integrated_f01(self):
        raw=surveys.issue(self.f.actor,self.binding.pk,self.f.members['F01'][0].pk)
        result=self.client.post('/survey/',{'code':raw})
        self.assertRedirects(result,'/survey/participation/form/',fetch_redirect_response=False)
