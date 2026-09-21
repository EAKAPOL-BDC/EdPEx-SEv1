from html.parser import HTMLParser
from django.conf import settings
from django.test import TestCase, SimpleTestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.accounts.workflow import collection_links
from apps.rounds.services import transition_round
from apps.rounds.models import CollectionRound
from apps.calculations.models import CalculationRun
from tests.test_unlinked_access import fixture
from tests.m2_fixtures import grant

class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.urls=set()
    def handle_starttag(self, tag, attrs):
        if tag=='a':
            value=dict(attrs).get('href','')
            if value.startswith('/workspace/') or value=='/manuals/':self.urls.add(value)


class LegacyNavigationTests(SimpleTestCase):
    def test_historical_self_assessments_do_not_get_anonymous_survey_links(self):
        from types import SimpleNamespace
        selected=SimpleNamespace(collection_round=SimpleNamespace(scope=None))
        self.assertEqual(collection_links(None,selected,{'round.manage'}),{})

@override_settings(NEXORA_PARTICIPATION_ENABLED=True,NEXORA_UNLINKED_ACCESS_ENABLED=True,NEXORA_CONFIRM_IMPORTANT_ACTIONS=False)
class WorkspaceWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):cls.f=fixture()
    def setUp(self):self.client.force_login(self.f.actor)

    def test_home_and_list_use_current_flow_and_every_home_link_resolves(self):
        b=self.f.binding
        invite=reverse('participation-manage',args=[self.f.scope.pk,b.pk])
        response=self.client.get('/workspace/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,invite)
        self.assertContains(response,reverse('participation-entry'))
        self.assertContains(response,reverse('participation-holder'))
        self.assertIn('no-store',response['Cache-Control'])
        links=Links();links.feed(response.content.decode())
        for url in links.urls:
            with self.subTest(url=url):self.assertLess(self.client.get(url,follow=True).status_code,400)
        listing=self.client.get(reverse('survey-list',args=[self.f.scope.pk]))
        self.assertContains(listing,invite)
        administration=self.client.get(reverse('backoffice-home',args=[self.f.scope.pk]),{'queue':'open'})
        self.assertContains(administration,invite)
        self.assertEqual(administration.context['rounds'][0].work_url,invite)
        landing=Client().get('/')
        self.assertContains(landing,reverse('participation-entry'))
        self.assertFalse(CalculationRun.objects.exists())
        b.collection_round.refresh_from_db();self.assertEqual(b.collection_round.status,'open')

    def test_closed_round_routes_to_results_and_old_controls_cannot_mutate(self):
        b=self.f.binding
        old=reverse('survey-collection',args=[self.f.scope.pk,b.pk])
        self.assertRedirects(self.client.get(old),reverse('participation-manage',args=[self.f.scope.pk,b.pk]))
        rejected=self.client.post(old,{'action':'closed','reason':'Old screen','confirm':'on'})
        self.assertEqual(rejected.status_code,422)
        b.collection_round.refresh_from_db();self.assertEqual(b.collection_round.status,'open')
        transition_round(self.f.actor,b.collection_round,'closed',reason='Synthetic completion')
        result=reverse('participation-results',args=[self.f.scope.pk,b.pk])
        self.assertRedirects(self.client.get(old),result)
        self.assertContains(self.client.get('/workspace/'),result)
        page=self.client.get(result)
        self.assertContains(page,'aria-current="page"')
        self.assertContains(page,reverse('survey-list',args=[self.f.scope.pk]))

    def test_roles_scopes_language_and_feature_fallback(self):
        foreign=reverse('workspace')+'?scope='+str(self.f.foreign.pk)
        self.assertEqual(self.client.get(foreign).status_code,404)
        self.assertEqual(self.client.get('/workspace/?scope=invalid').status_code,404)
        self.client.force_login(self.f.reviewer)
        page=self.client.get('/workspace/')
        result=reverse('participation-results',args=[self.f.scope.pk,self.f.binding.pk])
        self.assertContains(page,result)
        self.assertNotContains(page,reverse('participation-manage',args=[self.f.scope.pk,self.f.binding.pk]))
        self.assertNotContains(page,reverse('portal-members',args=[self.f.scope.pk]))
        self.assertEqual(self.client.get(reverse('participation-manage',args=[self.f.scope.pk,self.f.binding.pk])).status_code,403)
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME]='en'
        self.assertContains(self.client.get('/workspace/'),'Actions for your role')
        self.assertContains(self.client.get('/workspace/'),'Mr.Eakapol Bodhichandra')
        with override_settings(NEXORA_UNLINKED_ACCESS_ENABLED=False):
            page=self.client.get('/workspace/')
            self.assertNotContains(page,reverse('participation-entry'))
            self.assertNotContains(page,result)
            self.assertContains(page,reverse('survey-access'))
            self.assertNotContains(Client().get('/'),reverse('participation-entry'))
        self.assertEqual(Client().get('/workspace/').status_code,302)

    def test_multiple_scopes_filter_and_assignment_only_role(self):
        grant(self.f.actor,self.f.foreign,['catalog.read'],'workflow-other-scope')
        page=self.client.get('/workspace/?scope='+str(self.f.foreign.pk))
        self.assertEqual(page.status_code,200)
        self.assertEqual(page.context['round_count'],0)
        self.assertNotContains(page,reverse('participation-manage',args=[self.f.scope.pk,self.f.binding.pk]))
        user=get_user_model().objects.create_user(username='legacy-assignment-only')
        grant(user,self.f.scope,['selfassessment.assign'],'workflow-legacy-assignment')
        self.client.force_login(user)
        self.assertNotContains(self.client.get('/workspace/'),reverse('survey-list',args=[self.f.scope.pk]))
