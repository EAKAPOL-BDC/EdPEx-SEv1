from unittest.mock import patch
from django.test import SimpleTestCase, RequestFactory
from django.template.loader import render_to_string
from django.contrib.auth.models import AnonymousUser
from django.forms import RadioSelect
from apps.surveys.forms import ResponseForm
from apps.selfassessments.web import SelfReportForm
from apps.catalog.assessment_ui import sections

class AssessmentPresentationTests(SimpleTestCase):
    def test_survey_radio_values_sections_and_zero_answer_preserved(self):
        schema={'title':'Test F03','context':'Synthetic','instructions':[],'privacy':'Synthetic',
            'questions':[{'id':'F03-H01','text':'Happiness','type':'integer_scale','options':[
                {'code':str(n),'label':str(n),'status':'answered','value':n} for n in range(11)]},
                {'id':'F03-O01','text':'Suggestions','type':'text','options':[]}]}
        with patch('apps.surveys.forms.respondent_schema',return_value=schema):
            form=ResponseForm(None,{'F03-H01':{'status':'answered','value':0}},3,'th')
        self.assertIsInstance(form.fields['F03-H01'].widget,RadioSelect)
        self.assertEqual(form['F03-H01'].value(),'value:0')
        grouped=sections(form)
        self.assertEqual([s['key'] for s in grouped],['H','O'])
        request=RequestFactory().get('/survey/answer/');request.user=AnonymousUser()
        html=render_to_string('surveys/answer.html',dict(schema=schema,form=form,locale='th',question_sections=grouped),request=request)
        self.assertRegex(html,r'<input[^>]*value="value:0"[^>]*checked')
        self.assertIn('<legend',html);self.assertIn('data-section-form',html)
        self.assertIn('name="ui_section"',html)
        self.assertNotIn('<select',html)
    def test_self_report_controls_keep_contract_and_readonly(self):
        schema={'revision':0,'editable':True,'answers':{},'questions':[
            {'id':'F06-M01','text':'Synthetic question','type':'integer_scale','expected_level':3,'allow_na':True,
             'options':[{'code':str(n),'value':n,'label':str(n)} for n in range(1,6)]}]}
        form=SelfReportForm(schema,{'expected_revision':0,'idempotency_key':'synthetic',
            'F06-M01':'not_applicable','F06-M01__reason':'No assigned duty'})
        self.assertTrue(form.is_valid(),form.errors)
        self.assertEqual(form.answers()['F06-M01'],{'status':'not_applicable','reason':'No assigned duty'})
        schema['editable']=False
        form=SelfReportForm(schema)
        self.assertTrue(form.fields['F06-M01'].disabled)
        self.assertIsInstance(form.fields['F06-M01'].widget,RadioSelect)
    def test_draft_returns_to_valid_section_only(self):
        from types import SimpleNamespace
        from django.test import override_settings
        from apps.surveys.web import answer
        schema={'questions':[{'id':'F03-H01','text':'Happiness','type':'integer_scale','options':[
            {'code':'0','label':'0','status':'answered','value':0}]}]}
        session=SimpleNamespace(invitation=SimpleNamespace(binding=SimpleNamespace(survey_profile=None)),draft={},revision=0)
        with override_settings(SURVEY_ALLOW_TEST_HTTP=True,ALLOWED_HOSTS=['testserver']), patch('apps.surveys.web.services.read_session',return_value=session), patch('apps.surveys.web.services.save'), patch('apps.surveys.web.posted_payload',return_value={'F03-H01':{'status':'answered','value':0}}), patch('apps.surveys.forms.respondent_schema',return_value=schema):
            for section,expected in [('H','#section-H'),('https://example.invalid/','')]:
                request=RequestFactory().post('/survey/answer/',{'revision':0,'action':'draft','F03-H01':'value:0','ui_section':section})
                request._dont_enforce_csrf_checks=True
                request.COOKIES['nexora_survey_session']='synthetic'
                response=answer(request)
                self.assertEqual(response.status_code,302)
                self.assertEqual(response['Location'],'/survey/answer/?saved=1&lang=th'+expected)
