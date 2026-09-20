from io import StringIO
from django import forms
from django.core.management import call_command
from django.core.management.base import CommandError
from django.template.loader import render_to_string
from django.test import SimpleTestCase, RequestFactory
from apps.accounts.field_guidance import guidance
from apps.participation.presentation import html_document, PREVIEW


class ExperienceRevisionTests(SimpleTestCase):
    def test_public_page_has_single_institution_and_no_removed_chips(self):
        html = render_to_string('participation/public_home.html', {'catalog':{}, 'public_preview':True})
        self.assertEqual(html.count('class="nx-institution"'),1)
        self.assertNotIn('class="trust-row"',html)
        self.assertIn('university-phayao.webp',html)
        self.assertIn('class="proof-link"',html)
        self.assertNotIn('ตรวจสอบที่นี่ →',html)

    def test_receipt_keeps_private_token_controls_and_shared_shell(self):
        request=RequestFactory().get('/survey/participation/receipt/')
        request.participation_nonce='test-nonce'
        response=html_document(request,(PREVIEW/'holder.html').read_text(encoding='utf-8'),{},'', '')
        html=response.content.decode()
        self.assertEqual(html.count('id="holder-token"'),1)
        self.assertIn('maxlength="69"',html)
        self.assertIn('href="/survey/public/"',html)
        self.assertIn('Mr.Eakapol Bodhichandra',html)
        self.assertNotIn('<!-- SHARED_IDENTITY -->',html)
        self.assertIn('nonce="test-nonce"',html)
        self.assertEqual(html.count('<main'),html.count('</main>'))

    def test_examples_are_not_default_answers_and_required_state_is_preserved(self):
        class ExampleForm(forms.Form):
            code=forms.CharField()
            reason=forms.CharField(required=False)
        form=ExampleForm()
        html=render_to_string('portal/components/editor_field.html', {'field':form['code'],'LANGUAGE_CODE':'th'})
        self.assertIn('ดูตัวอย่าง',html)
        self.assertIn('required',html)
        self.assertNotIn('value="รอบ',html)
        self.assertTrue(form.fields['code'].required)
        self.assertFalse(form.fields['reason'].required)

    def test_preview_bootstrap_cannot_run_under_regular_test_settings(self):
        with self.assertRaises(CommandError):
            call_command('prepare_preview_administrator', username='blocked-admin',reason='Guard test',apply=True,stdout=StringIO())

    def test_staff_manual_requires_login(self):
        from apps.manuals.operations_web import guide, download
        from django.contrib.auth.models import AnonymousUser
        request=RequestFactory().get('/manuals/operations/staff/')
        request.user=AnonymousUser()
        self.assertEqual(guide(request,'staff').status_code,302)
        self.assertEqual(download(request,'staff').status_code,302)

    def test_guide_has_prerequisites_outcomes_and_real_group_taxonomy(self):
        from apps.manuals.operations_web import context, export_html
        from django.http import Http404
        for key in ('staff','administrator','workflow'):
            data=context(key)
            self.assertEqual(len(data['groups']),17)
            for chapter in data['guide']['chapters']:
                self.assertTrue(chapter['before'] and chapter['steps'] and chapter['result'])
            self.assertIn('ยังไม่เปิดเก็บข้อมูลจริง', export_html(key))
        with self.assertRaises(Http404):
            context('../private')
