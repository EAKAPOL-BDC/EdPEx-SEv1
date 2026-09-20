from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from apps.accounts.models import Organization, AccessScope, Membership, Role, RoleAssignment, ALLOWED_PERMISSIONS
from apps.auditlog.services import record_event
from apps.auditlog.models import AuditEvent

class BackofficeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org=Organization.objects.create(name='Demo org')
        cls.scope=AccessScope.objects.create(organization=cls.org,code='A',name='Workspace A')
        cls.other=AccessScope.objects.create(organization=cls.org,code='B',name='Workspace B')
        cls.admin=get_user_model().objects.create_user(username='manager')
        cls.reader=get_user_model().objects.create_user(username='reader')
        for user,code,permissions in [(cls.admin,'all',sorted(ALLOWED_PERMISSIONS)),(cls.reader,'read',['catalog.read'])]:
            m=Membership.objects.create(user=user,organization=cls.org)
            role=Role.objects.create(code=code,permissions=permissions)
            RoleAssignment.objects.create(membership=m,role=role,scope=cls.scope)
    def setUp(self):
        self.client=Client(enforce_csrf_checks=True)
        self.client.force_login(self.admin)
    def url(self,name,scope=None):return reverse('backoffice-'+name,kwargs={'scope_id':(scope or self.scope).pk})
    def test_hub_and_permission_boundaries(self):
        self.assertContains(self.client.get(self.url('home')),'จัดการระบบ')
        self.assertEqual(self.client.get(self.url('home',self.other)).status_code,403)
        self.client.force_login(self.reader)
        for name in ['home','settings','audit']:
            self.assertEqual(self.client.get(self.url(name)).status_code,403)
    def test_settings_csrf_stale_and_audit(self):
        response=self.client.get(self.url('settings'))
        data={'name':'Changed workspace','reason':'Improve label','revision':response.context['form']['revision'].value()}
        self.assertEqual(self.client.post(self.url('settings'),data).status_code,403)
        data['csrfmiddlewaretoken']=self.client.cookies['csrftoken'].value
        self.assertEqual(self.client.post(self.url('settings'),data).status_code,302)
        self.scope.refresh_from_db();self.assertEqual(self.scope.name,'Changed workspace')
        self.assertEqual(self.client.post(self.url('settings'),data).status_code,422)
        self.assertEqual(AuditEvent.objects.filter(action='workspace.settings_updated').count(),1)
    def test_audit_scope_filters_and_no_metadata(self):
        for scope,action in [(self.scope,'visible.event'),(self.other,'private.event')]:
            record_event(self.org,self.admin,action,'Test','1',metadata={'scope_id':str(scope.pk),'source_hash':'HIDDEN_METADATA'})
        response=self.client.get(self.url('audit'))
        self.assertContains(response,'visible.event');self.assertNotContains(response,'private.event');self.assertNotContains(response,'HIDDEN_METADATA')
        self.assertNotContains(self.client.get(self.url('audit')+'?action=missing'),'visible.event')
        self.assertEqual(self.client.get(self.url('audit')+'?start=invalid').status_code,200)
    def test_password_change_requires_old_password(self):
        self.admin.set_password('Previous-Secure-Password-83!');self.admin.save()
        self.client.force_login(self.admin)
        self.client.get(reverse('password-change'))
        data={'csrfmiddlewaretoken':self.client.cookies['csrftoken'].value,'old_password':'incorrect',
            'new_password1':'Replacement-Secure-Password-47!','new_password2':'Replacement-Secure-Password-47!'}
        self.assertEqual(self.client.post(reverse('password-change'),data).status_code,200)
        self.admin.refresh_from_db();self.assertTrue(self.admin.check_password('Previous-Secure-Password-83!'))
        data['old_password']='Previous-Secure-Password-83!'
        self.assertEqual(self.client.post(reverse('password-change'),data).status_code,302)
        self.admin.refresh_from_db();self.assertTrue(self.admin.check_password(data['new_password1']))
        self.assertEqual(self.client.get(self.url('home')).status_code,200)
    def test_navigation_stays_inside_sidebar(self):
        from html.parser import HTMLParser
        class Structure(HTMLParser):
            def __init__(self):
                super().__init__();self.in_aside=False;self.in_nav=False;self.links={};self.direct=[];self.in_main=False;self.depth=0
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if tag=='aside':self.in_aside=True
                if tag=='nav' and self.in_aside:self.in_nav=True
                if tag=='a':self.links.setdefault(attrs.get('href'), []).append((self.in_aside,self.in_nav))
            def handle_endtag(self,tag):
                if tag=='nav':self.in_nav=False
                if tag=='aside':self.in_aside=False
        for route in ['home','settings','audit']:
            response=self.client.get(self.url(route))
            parser=Structure();parser.feed(response.content.decode())
            self.assertIn((True,True),parser.links[self.url('home')])
            self.assertEqual(parser.links[reverse('password-change')],[(True,True)])
