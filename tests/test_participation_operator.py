from unittest.mock import patch
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.core import signing
from apps.participation import admission
from apps.participation.models import AccessPass, AccessSession
from apps.participation.operator import SALT
from tests.test_unlinked_access import fixture


@override_settings(NEXORA_PARTICIPATION_ENABLED=True,NEXORA_UNLINKED_ACCESS_ENABLED=True,NEXORA_CONFIRM_IMPORTANT_ACTIONS=False)
class InvitationOperatorTests(TestCase):
    @classmethod
    def setUpTestData(cls):cls.f=fixture()

    def setUp(self):
        self.url=reverse('participation-manage',args=[self.f.scope.pk,self.f.binding.pk])
        self.client.force_login(self.f.actor)

    def data(self,count=1):
        page=self.client.get(self.url)
        return {'action':'mint','count':count,'confirm':'on','stamp':page.context['batch'].initial['stamp']}

    def test_auth_scope_and_feature_gate(self):
        c=Client();self.assertEqual(c.get(self.url).status_code,302)
        for user in [self.f.other,self.f.reviewer]:
            c.force_login(user)
            self.assertEqual(c.get(self.url).status_code,403)
            self.assertEqual(c.post(self.url,{'action':'mint'}).status_code,403)
        foreign=reverse('participation-manage',args=[self.f.foreign.pk,self.f.binding.pk])
        self.assertEqual(self.client.get(foreign).status_code,404)
        with override_settings(NEXORA_UNLINKED_ACCESS_ENABLED=False):self.assertEqual(self.client.get(self.url).status_code,404)

    def test_batch_single_return_and_replay(self):
        data=self.data(2);response=self.client.post(self.url,data)
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.context['cards']),2)
        self.assertIn('no-store',response['Cache-Control'])
        self.assertIn("frame-ancestors 'none'",response['Content-Security-Policy'])
        for card in response.context['cards']:
            self.assertTrue(card['link'].endswith('#'+card['code']))
            self.assertIn('<svg',card['qr'])
            self.assertNotContains(self.client.get(self.url),card['code'])
        self.assertEqual(self.client.post(self.url,data).status_code,409)
        self.assertEqual(AccessPass.objects.count(),2)

    def test_invalid_and_stale_forms_do_not_consume_quota(self):
        data=self.data(6);self.assertEqual(self.client.post(self.url,data).status_code,422)
        data=self.data();data.pop('confirm');self.assertEqual(self.client.post(self.url,data).status_code,422)
        data=self.data();data['stamp']+='bad';self.assertEqual(self.client.post(self.url,data).status_code,409)
        data=self.data();data['stamp']=signing.dumps({'actor':str(self.f.other.pk),'binding':str(self.f.binding.pk),'total':0},salt=SALT)
        self.assertEqual(self.client.post(self.url,data).status_code,409)
        self.assertEqual(AccessPass.objects.count(),0)
        data=self.data();admission.mint(self.f.actor,self.f.binding.pk,1)
        self.assertEqual(self.client.post(self.url,data).status_code,409)
        self.assertEqual(AccessPass.objects.count(),1)

    def test_csrf_required_and_no_get_mutation(self):
        c=Client(enforce_csrf_checks=True);c.force_login(self.f.actor)
        page=c.get(self.url);self.assertEqual(page.status_code,200)
        self.assertEqual(AccessPass.objects.count(),0)
        data=self.data();self.assertEqual(c.post(self.url,data).status_code,403)
        from django.conf import settings
        self.assertEqual(c.post(self.url,data,HTTP_X_CSRFTOKEN=c.cookies[settings.CSRF_COOKIE_NAME].value).status_code,200)

    def test_pause_and_resume_require_confirmation(self):
        mint_data=self.data()
        raw=admission.mint(self.f.actor,self.f.binding.pk,1)[0];admission.exchange(raw)
        self.assertEqual(self.client.post(self.url,{'action':'pause'}).status_code,422)
        self.assertEqual(AccessSession.objects.count(),1)
        self.assertEqual(self.client.post(self.url,{'action':'pause','confirm':'on'}).status_code,302)
        self.assertEqual(AccessSession.objects.count(),0)
        self.assertFalse(self.client.get(self.url).context['pool'].enabled)
        self.assertEqual(self.client.post(self.url,mint_data).status_code,409)
        self.assertEqual(self.client.post(self.url,{'action':'resume','confirm':'on'}).status_code,302)
        self.assertTrue(self.client.get(self.url).context['pool'].enabled)
        self.assertTrue(admission.exchange(raw).startswith('NXS1-'))

    def test_qr_failure_rolls_back_batch(self):
        data=self.data()
        with patch('apps.participation.operator.receipt_svg',side_effect=RuntimeError('render failed')):
            with self.assertRaises(RuntimeError):self.client.post(self.url,data)
        self.assertEqual(AccessPass.objects.count(),0)

    @override_settings(NEXORA_CONFIRM_IMPORTANT_ACTIONS=True)
    def test_existing_review_confirmation_then_issue_once(self):
        data=self.data()
        review=self.client.post(self.url,data)
        self.assertEqual(review.status_code,200)
        self.assertEqual(AccessPass.objects.count(),0)
        data.update(operation_ticket=str(review.context['ticket']),operation_ack='yes')
        issued=self.client.post(self.url,data)
        self.assertEqual(issued.status_code,200)
        self.assertEqual(len(issued.context['cards']),1)
        self.assertEqual(self.client.post(self.url,data).status_code,409)
        self.assertEqual(AccessPass.objects.count(),1)

    def test_aggregate_only_dashboard_and_collection_link(self):
        page=self.client.get(self.url)
        self.assertNotContains(page,'PRIVATE-')
        self.assertEqual(page.context['tally']['remaining'],5)
        self.assertRedirects(self.client.get(reverse('survey-collection',args=[self.f.scope.pk,self.f.binding.pk])),self.url)
        # Both locales use the existing portal language preference.
        from django.conf import settings
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME]='en'
        self.assertContains(self.client.get(self.url),'Assessment invitation centre')
