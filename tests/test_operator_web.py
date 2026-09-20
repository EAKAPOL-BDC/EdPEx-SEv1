"""Staff HTML workflow exercises scoped services and disclosure boundaries."""
from datetime import timedelta
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import AccessScope, RoleAssignment
from apps.auditlog.models import AuditEvent
from apps.calculations.models import CalculationRun, ResultDecision, ResultReviewRequest, StoredSourceSelection
from apps.calculations.review import request_review
from apps.rounds.models import CollectionRound
from apps.rounds.services import transition_round
from apps.selfassessments.models import SelfAssessmentAssignment, SelfAssessmentRevision
from apps.selfassessments.operator_web import PREVIEW_MAX_AGE
from apps.selfassessments.services import calculate_self_assessments, save_revision
from tests.m2_fixtures import grant, scenario
from tests.test_self_assessments import self_scenario


class OperatorAssignmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.f = scenario(status='ready', extra_f06=True)
        grant(cls.f.actor, cls.f.scope, ['selfassessment.assign'], 'synthetic-ui-assign')
        cls.owner = get_user_model().objects.create_user(username='synthetic-ui-owner')
        grant(cls.owner, cls.f.scope, ['self.read', 'self.write'], 'synthetic-ui-owner')
        cls.member = cls.f.round.population_snapshot.members.get(eligible_unit_key='staff-A')
        cls.selected = cls.f.round_instruments['F06']

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.f.actor)

    def url(self, name, **kw):
        return reverse('operator-'+name, kwargs={'scope_id': self.f.scope.pk, **kw})

    def assign_url(self):
        return self.url('assign', selected_id=self.selected.pk, member_id=self.member.pk)

    def assignment_data(self):
        return {'owner': self.owner.pk, 'duties': 'Synthetic actual duties',
            **{'expected_'+q.question_id: '4' for q in self.f.versions['F06'].questions.filter(answer_type='integer_scale')},
            'dimensions': ['F06-M01'], 'csrfmiddlewaretoken': self.client.cookies['csrftoken'].value}

    def test_get_has_no_writes_or_assumed_expected_levels_and_uses_pinned_translation(self):
        before = AuditEvent.objects.count()
        response = self.client.get(self.assign_url())
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SelfAssessmentAssignment.objects.exists())
        self.assertEqual(AuditEvent.objects.count(), before)
        fields = response.context['form']
        expected = [f for f in fields if f.name.startswith('expected_')]
        self.assertTrue(expected)
        self.assertTrue(all(f.value() is None for f in expected))
        self.assertTrue(all(len(f.field.choices) == 6 for f in expected))
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(self.client.post('/language/', {'language': 'en',
            'csrfmiddlewaretoken': self.client.cookies['csrftoken'].value}).status_code, 200)
        response = self.client.get(self.assign_url())
        self.assertContains(response, 'Assign a self-report')
        qid = expected[0].name[len('expected_'):]
        text = self.selected.translation_bundle.translations.get(content_key=qid+'.text', locale='en').text
        self.assertContains(response, text)

    def test_assignment_through_csrf_form_freezes_configuration_and_rejects_duplicate(self):
        self.client.get(self.assign_url())
        data = self.assignment_data()
        self.assertEqual(self.client.post(self.assign_url(), data).status_code, 302)
        assignment = SelfAssessmentAssignment.objects.get()
        self.assertEqual(assignment.user_id, self.owner.pk)
        self.assertEqual(assignment.member_id, self.member.pk)
        self.assertEqual(assignment.expected_levels['F06-K01'], 4)
        self.assertIn('F06-M01', assignment.applicable_question_ids)
        self.assertNotIn('F06-M02', assignment.applicable_question_ids)
        self.assertIn('F06-K01', assignment.applicable_question_ids)
        self.assertEqual(self.client.post(self.assign_url(), data).status_code, 302)
        self.assertEqual(SelfAssessmentAssignment.objects.count(), 1)
        self.assertFalse(SelfAssessmentRevision.objects.exists())

    def test_invalid_owner_missing_level_or_injected_dimension_does_not_assign(self):
        self.client.get(self.assign_url())
        outsider = get_user_model().objects.create_user(username='synthetic-ui-outsider')
        for changes in [{'owner': outsider.pk}, {'expected_F06-K01': ''},
                        {'expected_F06-K01': '6'}, {'dimensions': ['F06-UNKNOWN']}]:
            response = self.client.post(self.assign_url(), {**self.assignment_data(), **changes})
            self.assertEqual(response.status_code, 422)
        self.assertFalse(SelfAssessmentAssignment.objects.exists())

    def test_roster_requires_population_permission_and_has_no_superuser_bypass(self):
        only_assign = get_user_model().objects.create_user(username='synthetic-only-assign')
        grant(only_assign, self.f.scope, ['selfassessment.assign'], 'synthetic-only-assign')
        admin = get_user_model().objects.create_user(username='synthetic-ui-super', is_superuser=True, is_staff=True)
        for user in [only_assign, self.owner, admin]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url('roster', selected_id=self.selected.pk)).status_code, 403)
            self.assertEqual(self.client.get(self.assign_url()).status_code, 403)
        self.client.force_login(self.f.actor)
        response = self.client.get(self.url('roster', selected_id=self.selected.pk))
        self.assertContains(response, 'staff-A')
        self.assertNotContains(response, 'org-A')

    def test_scope_and_population_ids_are_bound_to_the_route(self):
        other = AccessScope.objects.create(organization=self.f.org, code='SYNTHETIC-OTHER', name='Synthetic other')
        grant(self.f.actor, other, ['selfassessment.assign', 'population.manage'], 'synthetic-ui-other')
        response = self.client.get(reverse('operator-roster', kwargs={'scope_id': other.pk, 'selected_id': self.selected.pk}))
        self.assertEqual(response.status_code, 404)
        wrong_member = self.f.round.population_snapshot.members.exclude(group__code__in=['ST1', 'ST2']).first()
        self.assertEqual(self.client.get(self.url('assign', selected_id=self.selected.pk,
            member_id=wrong_member.pk)).status_code, 404)
        self.assertEqual(self.client.get(self.url('collection', selected_id=self.f.round_instruments['F02'].pk)).status_code, 404)

    def test_open_and_close_are_explicit_csrf_posts_for_the_whole_round(self):
        url = self.url('collection', selected_id=self.selected.pk)
        response = self.client.get(url+'?action=open')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ทุกแบบฟอร์มและทุกบริบท')
        self.assertEqual(CollectionRound.objects.get(pk=self.f.round.pk).status, 'ready')
        self.assertEqual(self.client.post(url, {'action': 'open', 'reason': 'Synthetic open'}).status_code, 403)
        token = self.client.cookies['csrftoken'].value
        self.assertEqual(self.client.post(url, {'action': 'open', 'reason': '', 'csrfmiddlewaretoken': token}).status_code, 422)
        for action in ['open', 'closed']:
            response = self.client.post(url, {'action': action, 'reason': 'Synthetic '+action, 'csrfmiddlewaretoken': token})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(CollectionRound.objects.get(pk=self.f.round.pk).status, action)
        self.assertEqual(self.client.get(self.assign_url()).status_code, 302)
        self.assertFalse(SelfAssessmentAssignment.objects.exists())

    def test_round_controls_cannot_be_used_by_response_owner(self):
        self.client.force_login(self.owner)
        self.client.get('/workspace/')
        url = self.url('collection', selected_id=self.selected.pk)
        response = self.client.post(url, {'action': 'closed', 'reason': 'Synthetic attempt',
            'csrfmiddlewaretoken': self.client.cookies['csrftoken'].value})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(CollectionRound.objects.get(pk=self.f.round.pk).status, 'ready')


class OperatorResultTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.f = self_scenario()
        answers = {key: dict(value) for key, value in cls.f.answers.items()}
        answers['F06-K01']['example'] = 'PRIVATE-EXAMPLE-DO-NOT-DISCLOSE'
        save_revision(cls.f.staff, assignment_id=cls.f.assignment, expected_revision=0,
            status='submitted', answers=answers, idempotency_key='synthetic-ui-submission')
        cls.f.round = transition_round(cls.f.actor, cls.f.round, 'closed', reason='Synthetic UI close')

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.f.analyst)
        self.url = reverse('operator-calculate', kwargs={'scope_id': self.f.scope.pk,
            'selected_id': self.f.round_instruments['F06'].pk})

    def csrf(self):
        return self.client.cookies['csrftoken'].value

    def preview(self, key='synthetic-ui-calculation'):
        self.assertEqual(self.client.get(self.url).status_code, 200)
        response = self.client.post(self.url, {'action': 'preview', 'cutoff': timezone.now().isoformat(),
            'idempotency_key': key, 'csrfmiddlewaretoken': self.csrf()})
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context['preview'])
        return response.context['preview_token']

    def commit(self, token, **extra):
        return self.client.post(self.url, {'action': 'commit', 'preview_token': token,
            'csrfmiddlewaretoken': self.csrf(), **extra})

    def run_url(self, run_id):
        return reverse('operator-run', kwargs={'scope_id': self.f.scope.pk, 'run_id': run_id})

    def make_run(self, key='synthetic-ui-result'):
        receipt = calculate_self_assessments(self.f.analyst, round_instrument_id=self.f.round_instruments['F06'].pk,
            cutoff=timezone.now(), idempotency_key=key)
        return receipt['run_id']

    def request_review(self, run_id):
        return request_review(self.f.actor, run_id=run_id, reason='Synthetic aggregate review requested')

    def test_dry_run_has_no_writes_and_commit_uses_only_signed_preview(self):
        before = AuditEvent.objects.count()
        token = self.preview()
        self.assertFalse(CalculationRun.objects.exists())
        self.assertFalse(StoredSourceSelection.objects.exists())
        self.assertEqual(AuditEvent.objects.count(), before)
        response = self.commit(token, cutoff='1900-01-01', idempotency_key='injected-key', answers='injected-values')
        self.assertEqual(response.status_code, 302)
        run = CalculationRun.objects.get()
        self.assertGreater(run.cutoff, self.f.round.open_at)
        self.assertEqual(run.result_count, 7)
        self.assertEqual(StoredSourceSelection.objects.count(), 1)
        self.assertEqual(self.commit(token).url, response.url)
        self.assertEqual(CalculationRun.objects.count(), 1)

    def test_missing_tampered_and_expired_confirmation_do_not_write(self):
        token = self.preview()
        for bad in ['', token+'x', 'x'*4097]:
            self.assertEqual(self.commit(bad).status_code, 422)
        with patch('django.core.signing.time.time', return_value=timezone.now().timestamp()+PREVIEW_MAX_AGE+1):
            self.assertEqual(self.commit(token).status_code, 422)
        self.assertFalse(CalculationRun.objects.exists())

    def test_confirmation_cannot_move_to_another_actor_or_context(self):
        token = self.preview()
        self.client.force_login(self.f.actor)
        self.client.get(self.url)
        self.assertEqual(self.commit(token).status_code, 403)
        self.assertFalse(CalculationRun.objects.exists())

    def test_revoked_permission_blocks_previously_prepared_confirmation(self):
        token = self.preview()
        RoleAssignment.objects.filter(membership__user=self.f.analyst).update(revoked_at=timezone.now())
        self.assertEqual(self.commit(token).status_code, 403)
        self.assertFalse(CalculationRun.objects.exists())

    def test_source_change_after_preview_rolls_back_all_writes(self):
        token = self.preview()
        before = AuditEvent.objects.count()
        def changed(*args, **kwargs):
            receipt = calculate_self_assessments(*args, **kwargs)
            return {**receipt, 'input_hash': '0'*64}
        with patch('apps.selfassessments.operator_web.calculate_self_assessments', side_effect=changed):
            self.assertEqual(self.commit(token).status_code, 409)
        self.assertFalse(CalculationRun.objects.exists())
        self.assertFalse(StoredSourceSelection.objects.exists())
        self.assertEqual(AuditEvent.objects.count(), before)

    def test_organization_timezone_interprets_cutoff_on_the_form(self):
        self.f.org.timezone = 'Pacific/Honolulu'
        self.f.org.save()
        self.client.get(self.url)
        local = timezone.now()-timedelta(hours=10)
        response = self.client.post(self.url, {'action': 'preview', 'cutoff': local.strftime('%Y-%m-%dT%H:%M:%S'),
            'idempotency_key': 'synthetic-time-zone', 'csrfmiddlewaretoken': self.csrf()})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Pacific/Honolulu')
        self.assertEqual(response.context['form'].cleaned_data['cutoff'].utcoffset(), timedelta(hours=-10))

    def test_analyst_sees_receipt_metadata_only_and_cannot_review_or_assign(self):
        run_id = self.make_run()
        self.request_review(run_id)
        url = self.run_url(run_id)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['packet'])
        for secret in ['PRIVATE-EXAMPLE-DO-NOT-DISCLOSE', 'staff-A', 'source_revisions',
                       'quality_counts', 'Synthetic aggregate review requested', 'reviewed_token']:
            self.assertNotContains(response, secret)
        self.assertEqual(self.client.post(url, {'action': 'submit', 'reason': 'Synthetic',
            'csrfmiddlewaretoken': self.csrf()}).status_code, 403)
        roster = reverse('operator-roster', kwargs={'scope_id': self.f.scope.pk,
            'selected_id': self.f.round_instruments['F06'].pk})
        self.assertEqual(self.client.get(roster).status_code, 403)

    def test_complete_web_flow_request_and_independent_approval_with_matching_token(self):
        token = self.preview()
        self.assertEqual(self.commit(token).status_code, 302)
        run = CalculationRun.objects.get()
        url = self.run_url(run.pk)
        self.client.force_login(self.f.actor)
        response = self.client.get(url)
        self.assertContains(response, 'ส่งชุดผลเข้าตรวจ')
        data = {'action': 'submit', 'reason': 'Synthetic web review', 'csrfmiddlewaretoken': self.csrf()}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(ResultReviewRequest.objects.count(), 1)
        self.client.force_login(self.f.reviewer)
        response = self.client.get(url)
        self.assertTrue(response.context['can_decide'])
        data = {'action': 'decide', 'outcome': 'approved', 'reason': 'Synthetic web approval',
            'reviewed_token': response.context['packet']['review_token'], 'csrfmiddlewaretoken': self.csrf()}
        self.assertEqual(self.client.post(url, {**data, 'reviewed_token': '0'*64}).status_code, 409)
        self.assertFalse(ResultDecision.objects.exists())
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(ResultDecision.objects.get().outcome, 'approved')
        self.assertEqual(CollectionRound.objects.get(pk=self.f.round.pk).status, 'closed')
        response = self.client.get(url)
        self.assertContains(response, 'ยังคงไม่เผยแพร่')
        self.assertFalse(response.context['can_decide'])

    def test_small_group_packet_has_no_numeric_fields_in_html_in_either_language(self):
        run_id = self.make_run()
        self.request_review(run_id)
        self.client.force_login(self.f.reviewer)
        self.client.get(self.run_url(run_id))
        for locale in ['th', 'en']:
            self.assertEqual(self.client.post('/language/', {'language': locale,
                'csrfmiddlewaretoken': self.csrf()}).status_code, 200)
            response = self.client.get(self.run_url(run_id))
            self.assertContains(response, '<html lang="'+locale+'">')
            self.assertEqual(response.status_code, 200)
            self.assertIn('no-store', response['Cache-Control'])
            for row in response.context['packet']['results']:
                self.assertEqual(row['status'], 'suppressed')
                for key in ['value', 'numerator', 'denominator', 'quality_counts', 'display_value']:
                    self.assertNotIn(key, row)
            for secret in ['PRIVATE-EXAMPLE-DO-NOT-DISCLOSE', 'staff-A', 'source_revisions',
                           'operator-value', 'valid_n', 'population_n']:
                self.assertNotContains(response, secret)

    def test_result_creator_and_submitter_cannot_decide_even_by_direct_post(self):
        run_id = self.make_run()
        review = self.request_review(run_id)
        grant(self.f.analyst, self.f.scope, ['result.review', 'result.approve', 'calculation.validate'], 'synthetic-analyst-review')
        for user in [self.f.analyst, self.f.actor]:
            self.client.force_login(user)
            response = self.client.get(self.run_url(run_id))
            self.assertFalse(response.context['can_decide'])
            data = {'action': 'decide', 'outcome': 'approved', 'reason': 'Synthetic self approval',
                'reviewed_token': review['review_token'], 'csrfmiddlewaretoken': self.csrf()}
            self.assertEqual(self.client.post(self.run_url(run_id), data).status_code, 403)
        self.assertFalse(ResultDecision.objects.exists())

    def test_result_scope_mismatch_and_csrf_are_rejected(self):
        run_id = self.make_run()
        other = AccessScope.objects.create(organization=self.f.org, code='SYNTHETIC-RESULT-OTHER', name='Other')
        grant(self.f.analyst, other, ['calculation.run'], 'synthetic-result-other')
        self.assertEqual(self.client.get(reverse('operator-run', kwargs={'scope_id': other.pk, 'run_id': run_id})).status_code, 404)
        self.assertEqual(self.client.post(self.run_url(run_id), {'action': 'submit', 'reason': 'Missing CSRF'}).status_code, 403)
        self.assertEqual(self.client.get(self.run_url(uuid.uuid4())).status_code, 404)
        self.client.force_login(self.f.staff)
        self.assertEqual(self.client.get(self.run_url(run_id)).status_code, 403)

    def test_failed_replay_does_not_render_decision_controls(self):
        run_id = self.make_run()
        self.request_review(run_id)
        self.client.force_login(self.f.reviewer)
        with patch('apps.selfassessments.operator_web.review_summary', side_effect=ValidationError('Synthetic failed replay')):
            response = self.client.get(self.run_url(run_id))
        self.assertEqual(response.status_code, 422)
        self.assertFalse(response.context['can_decide'])
        self.assertNotContains(response, 'name="action" value="decide"', status_code=422)

    def test_allowed_aggregate_values_render_but_suppressed_numeric_fields_never_do(self):
        # Exercise the renderer's packet contract; aggregate eligibility is tested in the service suite.
        run_id = self.make_run()
        review = self.request_review(run_id)
        self.client.force_login(self.f.reviewer)
        base = {'indicator': '7.4-3', 'group': 'ST1', 'dimension': None, 'method': 'self_report',
            'formula': {'formula_key': 'synthetic-spec'}, 'unit': '%'}
        packet = {'review_token': review['review_token'], 'results': [
            {**base, 'status': 'ok', 'value': '66.666666', 'numerator': '10', 'denominator': '15',
             'quality_counts': {'valid_n': 15}},
            {**base, 'status': 'suppressed', 'reason': 'small_group', 'value': 'SECRET-NUMERIC-FIELD',
             'numerator': 'SECRET-NUMERIC-FIELD', 'denominator': 'SECRET-NUMERIC-FIELD',
             'quality_counts': {'valid_n': 'SECRET-NUMERIC-FIELD'}}]}
        with patch('apps.selfassessments.operator_web.review_summary', return_value=packet):
            response = self.client.get(self.run_url(run_id))
        self.assertContains(response, '66.67 %')
        self.assertContains(response, '10 / 15')
        self.assertNotContains(response, 'SECRET-NUMERIC-FIELD')

    def test_workspace_navigation_and_history_remain_scoped_and_read_only(self):
        run_id = self.make_run()
        before = AuditEvent.objects.count()
        list_url = reverse('operator-list', kwargs={'scope_id': self.f.scope.pk})
        self.assertContains(self.client.get('/workspace/'), list_url)
        response = self.client.get(list_url)
        collection_url = reverse('operator-collection', kwargs={'scope_id': self.f.scope.pk,
            'selected_id': self.f.round_instruments['F06'].pk})
        self.assertContains(response, collection_url)
        self.assertContains(self.client.get(collection_url), self.run_url(run_id))
        self.assertEqual(AuditEvent.objects.count(), before)
        self.client.force_login(self.f.staff)
        self.assertNotContains(self.client.get('/workspace/'), list_url)
        self.assertEqual(self.client.get(list_url).status_code, 403)

    def test_returned_set_retains_decision_and_new_approval_links_previous_approval(self):
        from apps.calculations.review import decide_results
        first = self.make_run('synthetic-approved-old')
        review = self.request_review(first)
        decide_results(self.f.reviewer, run_id=first, outcome='approved', reason='Synthetic old approval',
            reviewed_token=review['review_token'])
        returned = self.make_run('synthetic-returned-middle')
        review = self.request_review(returned)
        self.client.force_login(self.f.reviewer)
        self.client.get(self.run_url(returned))
        self.assertEqual(self.client.post(self.run_url(returned), {'action': 'decide', 'outcome': 'returned',
            'reason': 'Synthetic correction needed', 'reviewed_token': review['review_token'],
            'csrfmiddlewaretoken': self.csrf()}).status_code, 302)
        self.assertFalse(self.client.get(self.run_url(returned)).context['can_decide'])
        newer = self.make_run('synthetic-approved-new')
        review = self.request_review(newer)
        decide_results(self.f.reviewer, run_id=newer, outcome='approved', reason='Synthetic new approval',
            reviewed_token=review['review_token'])
        response = self.client.get(self.run_url(newer))
        self.assertContains(response, self.run_url(first))
        self.assertTrue(all(row['reason'] == 'restricted_revision' for row in response.context['packet']['results']))
        self.assertTrue(self.client.get(self.run_url(first)).context['run']['superseded'])
        self.assertEqual(ResultDecision.objects.get(review__run_id=returned).outcome, 'returned')
