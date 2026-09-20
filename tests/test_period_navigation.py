"""Keep the selected intake workflow through reporting-period creation."""
from urllib.parse import parse_qs, urlsplit
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from apps.accounts.models import Organization, AccessScope, Role, Membership, RoleAssignment
from apps.rounds.models import CollectionRound, ReportingPeriod


class PeriodNavigationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        org = Organization.objects.create(name='Synthetic period navigation')
        cls.scope = AccessScope.objects.create(organization=org, code='NAV', name='Synthetic scope')
        cls.foreign = AccessScope.objects.create(organization=org, code='OTHER', name='Other scope')
        cls.actor = get_user_model().objects.create_user(username='period-operator')
        role = Role.objects.create(code='period-navigation', permissions=['calendar.manage', 'round.manage'])
        membership = Membership.objects.create(user=cls.actor, organization=org)
        RoleAssignment.objects.create(membership=membership, role=role, scope=cls.scope)

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.actor)

    def url(self, name, scope=None):
        return reverse(name, kwargs={'scope_id': (scope or self.scope).pk})

    def payload(self, **extra):
        return {'code': 'Synthetic calendar', 'calendar_type': 'calendar', 'reporting_year_be': 2569,
                'start_date': '2026-01-01', 'last_date': '2026-12-31', 'reason': 'Synthetic dates only',
                'confirm': 'on', **extra}

    def post(self, url, data):
        return self.client.post(url, {**data, 'csrfmiddlewaretoken': self.client.cookies['csrftoken'].value})

    def test_survey_returns_to_survey_and_selects_approved_period(self):
        entry = self.client.get(self.url('survey-new'))
        url = self.url('round-period-new') + '?return_to=survey'
        self.assertContains(entry, 'href="'+url+'"')
        form = self.client.get(url).context['form']
        self.assertEqual(form['return_to'].value(), 'survey')
        result = self.post(url, self.payload(return_to=form['return_to'].value()))
        period = ReportingPeriod.objects.get()
        self.assertTrue(period.approved)
        self.assertEqual(result.status_code, 302)
        self.assertEqual(urlsplit(result.url).path, self.url('survey-new'))
        self.assertEqual(parse_qs(urlsplit(result.url).query), {'period': [str(period.pk)]})
        returned = self.client.get(result.url)
        self.assertEqual(returned.context['form']['period'].value(), str(period.pk))
        self.assertIn('group_code', returned.context['form'].fields)
        self.assertFalse(CollectionRound.objects.exists())

    def test_f06_returns_to_f06_and_selects_approved_period(self):
        entry = self.client.get(self.url('round-new'))
        url = self.url('round-period-new') + '?return_to=f06'
        self.assertContains(entry, 'href="'+url+'"')
        self.client.get(url)
        result = self.post(url, self.payload(return_to='f06'))
        self.assertEqual(urlsplit(result.url).path, self.url('round-new'))
        returned = self.client.get(result.url)
        self.assertEqual(returned.context['form']['period'].value(), str(ReportingPeriod.objects.get().pk))
        self.assertNotIn('group_code', returned.context['form'].fields)

    def test_general_entry_returns_to_round_choice(self):
        url = self.url('round-period-new')
        self.client.get(url)
        result = self.post(url, self.payload())
        self.assertRedirects(result, self.url('round-list'))
        choice = self.client.get(result.url)
        self.assertContains(choice, self.url('survey-new'))
        self.assertContains(choice, self.url('round-new'))
        self.assertFalse(CollectionRound.objects.exists())

    def test_validation_error_preserves_survey_origin(self):
        url = self.url('round-period-new') + '?return_to=survey'
        self.client.get(url)
        invalid = self.post(url, self.payload(return_to='survey', reason=''))
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.context['form']['return_to'].value(), 'survey')
        self.assertFalse(ReportingPeriod.objects.exists())
        valid = self.post(url, self.payload(return_to=invalid.context['form']['return_to'].value()))
        self.assertEqual(urlsplit(valid.url).path, self.url('survey-new'))

    def test_untrusted_return_destination_is_not_a_redirect_target(self):
        url = self.url('round-period-new') + '?return_to=https://example.invalid/'
        page = self.client.get(url)
        self.assertEqual(page.context['form']['return_to'].value(), '')
        result = self.post(url, self.payload(return_to='https://example.invalid/'))
        self.assertEqual(result.status_code, 422)
        self.assertFalse(ReportingPeriod.objects.exists())

    def test_csrf_and_scope_permissions_still_apply(self):
        url = self.url('round-period-new') + '?return_to=survey'
        self.client.get(url)
        result = self.client.post(url, self.payload(return_to='survey'))
        self.assertEqual(result.status_code, 403)
        self.assertEqual(self.client.get(self.url('round-period-new', self.foreign)).status_code, 403)
        self.assertFalse(ReportingPeriod.objects.exists())
