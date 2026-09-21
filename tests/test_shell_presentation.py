"""Structural and authorization checks for the shared application frame."""
from html.parser import HTMLParser
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from tests.test_backoffice import BackofficeTests


class Landmarks(HTMLParser):
    def __init__(self):
        super().__init__(); self.stack=[]; self.footer_parents=[]; self.aside_parents=[]
    def handle_starttag(self,tag,attrs):
        if tag=='footer': self.footer_parents.append(tuple(self.stack))
        if tag=='aside': self.aside_parents.append(tuple(self.stack))
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
            self.stack.append(tag)
    def handle_endtag(self,tag):
        if tag in self.stack:
            index=len(self.stack)-1-self.stack[::-1].index(tag);self.stack=self.stack[:index]


class ShellPresentationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        BackofficeTests.setUpTestData.__func__(cls)
        cls.native_admin=get_user_model().objects.create_superuser(username='shell-native',password='Synthetic-test-only!')

    def test_workspace_directories_keep_one_outer_footer_and_scoped_navigation(self):
        self.client.force_login(self.admin)
        routes=[('workspace',[]),('self-assessment-list',[]),('backoffice-home',[self.scope.pk]),
                ('portal-members',[self.scope.pk]),('portal-catalog',[self.scope.pk]),
                ('assessment-preview-list',[self.scope.pk]),('operator-list',[self.scope.pk]),
                ('activity-list',[self.scope.pk]),('survey-list',[self.scope.pk]),
                ('round-list',[self.scope.pk]),('insights-list',[self.scope.pk]),('manuals-home',[])]
        for name,args in routes:
            response=self.client.get(reverse(name,args=args))
            self.assertEqual(response.status_code,200,name)
            self.assertContains(response,'portal/identity.css')
            self.assertContains(response,'portal/shell.css')
            self.assertContains(response,'portal/navigation.js')
            self.assertContains(response,'นายเอกพล โพธิจันทร์')
            parser=Landmarks();parser.feed(response.content.decode())
            self.assertEqual(sum(x==('html','body') for x in parser.footer_parents),1,name)
            self.assertTrue(all('main' in x for x in parser.aside_parents),name)
            self.assertContains(response,'class="nx-system-copy"',count=1)
            self.assertContains(response,'id="main-content"',count=1)
        self.client.force_login(self.reader)
        response=self.client.get(reverse('portal-catalog',args=[self.scope.pk]))
        self.assertNotContains(response,reverse('portal-members',args=[self.scope.pk]))
        self.assertNotContains(response,reverse('backoffice-home',args=[self.scope.pk]))

    def test_public_survey_and_admin_share_identity_without_changing_access(self):
        for url in ['/',reverse('login'),reverse('manuals-home'),'/survey/','/admin/login/']:
            response=self.client.get(url,secure=True)
            self.assertEqual(response.status_code,200,url)
            self.assertContains(response,'class="nx-system-copy"')
            self.assertContains(response,'นายเอกพล โพธิจันทร์')
            self.assertContains(response,'สงวนลิขสิทธิ์')
            self.assertNotContains(response,'id="workspace-navigation"')
        self.client.force_login(self.native_admin)
        for url in ['/admin/','/admin/auth/user/']:
            response=self.client.get(url,secure=True)
            self.assertEqual(response.status_code,200,url)
            self.assertContains(response,'portal/admin-frame.js')
            self.assertContains(response,'id="logout-form"')
            self.assertContains(response,'csrfmiddlewaretoken')
        # Native superuser status still grants no NEXORA workspace permissions.
        self.assertEqual(self.client.get(reverse('portal-catalog',args=[self.scope.pk])).status_code,403)
