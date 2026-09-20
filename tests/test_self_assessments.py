"""Stored F06 intake to calculation and independent aggregate review."""
import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase
from django.utils import timezone
from apps.accounts.models import AccessScope
from apps.auditlog.models import AuditEvent
from apps.calculations.models import CalculationRun, ResultDecision, ResultReviewRequest, StoredSourceSelection
from apps.calculations.review import decide_results, request_review, review_summary
from apps.calculations.services import IdempotencyConflict, record_calculation, validate_run
from apps.rounds.models import CollectionRound
from apps.rounds.services import transition_round
from apps.selfassessments.models import SelfAssessmentAssignment, SelfAssessmentRevision
from apps.selfassessments.services import (assign_self_assessment, calculate_self_assessments,
    list_own_assignments, read_own_assignment, save_revision)
from tests.m2_fixtures import grant, packet, scenario


def self_scenario():
    f = scenario(status='ready', extra_f06=True)
    grant(f.actor, f.scope, ['selfassessment.assign', 'result.submit', 'result.review', 'result.approve'], 'synthetic-collection-operator')
    f.staff = get_user_model().objects.create_user(username='synthetic-self-owner')
    f.reviewer = get_user_model().objects.create_user(username='synthetic-result-reviewer')
    f.analyst = get_user_model().objects.create_user(username='synthetic-db-analyst')
    grant(f.staff, f.scope, ['self.read', 'self.write'], 'synthetic-self-owner')
    grant(f.reviewer, f.scope, ['result.review', 'result.approve', 'calculation.validate'], 'synthetic-result-reviewer')
    grant(f.analyst, f.scope, ['calculation.run'], 'synthetic-db-analyst')
    questions = list(f.versions['F06'].questions.filter(active=True))
    f.assignment = assign_self_assessment(f.actor, round_instrument_id=f.round_instruments['F06'].pk,
        member_id=f.round.population_snapshot.members.get(eligible_unit_key='staff-A').pk, user_id=f.staff.pk,
        duties='Synthetic assigned duties', expected_levels={q.question_id: 4 for q in questions if q.answer_type=='integer_scale'},
        applicable_question_ids=[q.question_id for q in questions])
    f.answers = {q.question_id: {'status': 'answered', 'value': 4} for q in questions if q.answer_type=='integer_scale'}
    f.round = transition_round(f.actor, f.round, 'open')
    return f


class SelfAssessmentFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.f = self_scenario()

    def save(self, answers=None, revision=0, key='source-1', status='submitted', actor=None):
        return save_revision(actor or self.f.staff, assignment_id=self.f.assignment, expected_revision=revision,
            status=status, answers=self.f.answers if answers is None else answers, idempotency_key=key)

    def calculate(self, key='calculate-1', cutoff=None, dry_run=False):
        return calculate_self_assessments(self.f.analyst, round_instrument_id=self.f.round_instruments['F06'].pk,
            cutoff=cutoff or timezone.now(), idempotency_key=key, dry_run=dry_run)

    def close(self):
        self.f.round = transition_round(self.f.actor, self.f.round, 'closed', reason='Synthetic close')

    def review(self):
        self.save()
        self.close()
        receipt = self.calculate()
        requested = request_review(self.f.actor, run_id=receipt['run_id'], reason='Synthetic completeness checked')
        return receipt, requested

    def test_own_assignment_only_and_no_implicit_admin_bypass(self):
        self.assertEqual(len(list_own_assignments(self.f.staff)), 1)
        self.assertEqual(list_own_assignments(self.f.actor), [])
        admin = get_user_model().objects.create_user(username='synthetic-super', is_superuser=True, is_staff=True)
        for user in [admin, self.f.actor, self.f.reviewer]:
            with self.assertRaises(PermissionDenied):
                read_own_assignment(user, assignment_id=self.f.assignment)
            with self.assertRaises(PermissionDenied):
                self.save(actor=user)

    def test_draft_submission_and_revision_use_latest_submitted_not_highest(self):
        self.save(status='draft')
        self.save(revision=1, key='submit-2')
        lower = {qid: {'status':'answered', 'value':3} for qid in self.f.answers}
        self.save(lower, revision=2, key='submit-3')
        self.save(revision=3, key='draft-4', status='draft')
        self.close()
        receipt = self.calculate()
        run = CalculationRun.objects.get(pk=receipt['run_id'])
        result = run.results.get(indicator_code='7.4-3')
        self.assertEqual(result.payload['value'], '0')
        self.assertEqual(result.source.payload['source_revisions'][0]['revision_number'], 3)
        self.assertEqual(run.results.get(indicator_code='7.3-43').payload['denominator'], '2')
        self.assertEqual(validate_run(self.f.reviewer, run_id=run.pk)['matched_results'], 7)
        self.assertEqual(SelfAssessmentRevision.objects.count(), 4)

    def test_partial_answers_keep_valid_other_indicators(self):
        self.save({'F06-K01': {'status':'answered','value':4}, 'F06-K02': {'status':'answered','value':4}})
        self.assertEqual(SelfAssessmentRevision.objects.get().completeness, 'partial')
        self.close()
        run = CalculationRun.objects.get(pk=self.calculate()['run_id'])
        self.assertEqual(run.results.get(indicator_code='7.4-3').payload['value'], '100')
        self.assertEqual(run.results.get(indicator_code='7.3-54', source__definition__series__dimension='F06-M01').payload['status'], 'no_valid_data')

    def test_idempotency_and_optimistic_revision_do_not_overwrite(self):
        first = self.save()
        self.assertTrue(self.save()['reused'])
        self.assertEqual(first['revision'], 1)
        with self.assertRaises(IdempotencyConflict):
            self.save({}, key='source-1')
        with self.assertRaises(IdempotencyConflict):
            self.save({}, key='source-2')
        self.assertEqual(SelfAssessmentRevision.objects.count(), 1)

    def test_invalid_scores_context_other_group_and_evidence_are_rejected(self):
        invalid = [ {'F06-K01': {'status':'answered','value':v}} for v in [True, 6, 0, 4.0, '4'] ]
        invalid += [{'F06-A06': {'status':'answered','value':4}}, {'F06-P02': {'status':'answered','value':'ST2'}},
                    {'F06-K01': {'status':'answered','value':4,'evidence':'test'}},
                    {'F06-K01': {'status':'not_applicable'}}, {'F06-K01': {'status':'not_shown'}},
                    {'F06-K01': {'status':'missing','value':4}}]
        for answers in invalid:
            with self.subTest(answers=answers), self.assertRaises(ValidationError):
                self.save(answers)
        self.assertEqual(SelfAssessmentRevision.objects.count(), 0)

    def test_self_declared_na_needs_reason_but_no_review(self):
        with self.assertRaises(ValidationError):
            self.save({'F06-M01': {'status':'not_applicable'}})
        response = self.save({'F06-M01': {'status':'not_applicable', 'reason':'Outside my assigned task'}})
        self.assertEqual(response['status'], 'submitted')
        self.assertFalse(ResultReviewRequest.objects.exists())

    def test_optional_examples_plans_stay_out_of_score_sources_and_audit(self):
        answers = {qid: {**a, 'example':'SYNTHETIC_PRIVATE_EXAMPLE', 'development_plan':'SYNTHETIC_PRIVATE_PLAN'} for qid,a in self.f.answers.items()}
        self.save(answers)
        self.close()
        run = CalculationRun.objects.get(pk=self.calculate()['run_id'])
        serialized = json.dumps([s.payload for s in run.inputs.all()])
        self.assertNotIn('SYNTHETIC_PRIVATE', serialized)
        self.assertNotIn('SYNTHETIC_PRIVATE', json.dumps(list(AuditEvent.objects.values('metadata'))))
        self.assertEqual(run.results.get(indicator_code='7.4-3').payload['value'], '100')

    def test_assignment_and_expected_levels_freeze_before_open(self):
        a = SelfAssessmentAssignment.objects.get(pk=self.f.assignment)
        with self.assertRaises(ValidationError):
            a.expected_levels = {}; a.save()
        with self.assertRaises(ValidationError):
            assign_self_assessment(self.f.actor, round_instrument_id=a.round_instrument_id,
                member_id=a.member_id, user_id=a.user_id, duties=a.duties,
                expected_levels=a.expected_levels, applicable_question_ids=a.applicable_question_ids)

    def test_closed_window_stops_new_revisions_but_retry_is_safe(self):
        self.save()
        self.close()
        self.assertTrue(self.save()['reused'])
        with self.assertRaises(ValidationError):
            self.save(revision=1, key='late')
        self.assertEqual(SelfAssessmentRevision.objects.count(), 1)

    def test_no_calculation_while_open_and_dry_run_has_no_writes(self):
        self.save()
        with self.assertRaises(ValidationError):
            self.calculate()
        self.close()
        result = self.calculate(dry_run=True)
        self.assertEqual(result['status'], 'dry_run')
        self.assertFalse(CalculationRun.objects.exists())
        self.assertFalse(StoredSourceSelection.objects.exists())

    def test_database_analyst_needs_no_typed_source_permission(self):
        self.save(); self.close()
        cutoff = timezone.now()
        first = self.calculate(cutoff=cutoff)
        second = self.calculate(cutoff=cutoff)
        self.assertEqual(first['run_id'], second['run_id'])
        with self.assertRaises(PermissionDenied):
            record_calculation(self.f.analyst, round_id=self.f.round.pk, inputs=[packet(self.f)], cutoff=cutoff, idempotency_key='raw')
        self.assertEqual(StoredSourceSelection.objects.count(), 1)
        self.assertEqual(CalculationRun.objects.get().result_count, 7)

    def test_audit_failure_rolls_back_response(self):
        with patch('apps.selfassessments.services._audit', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):
                self.save()
        self.assertEqual(SelfAssessmentRevision.objects.count(), 0)

    def test_small_group_review_packet_hides_all_numeric_result_fields(self):
        receipt, requested = self.review()
        packet = review_summary(self.f.reviewer, run_id=receipt['run_id'])
        self.assertEqual(packet['status'], 'review')
        self.assertEqual(packet['review_token'], requested['review_token'])
        for result in packet['results']:
            self.assertEqual(result['status'], 'suppressed')
            for field in ['value', 'numerator', 'denominator', 'quality_counts']:
                self.assertNotIn(field, result)

    def test_approval_requires_independent_reviewer_and_current_token(self):
        receipt, request = self.review()
        args = dict(run_id=receipt['run_id'], outcome='approved', reason='Synthetic checks passed', reviewed_token=request['review_token'])
        with self.assertRaises(ValidationError):
            decide_results(self.f.actor, **args)
        with self.assertRaises(IdempotencyConflict):
            decide_results(self.f.reviewer, **{**args, 'reviewed_token':'f'*64})
        result = decide_results(self.f.reviewer, **args)
        self.assertEqual(result['status'], 'approved')
        self.assertTrue(decide_results(self.f.reviewer, **args)['reused'])
        self.assertEqual(result['publication_status'], 'unpublished')
        self.f.round.refresh_from_db()
        self.assertEqual(self.f.round.status, 'closed')
        self.assertEqual(SelfAssessmentRevision.objects.get().status, 'submitted')
        self.assertEqual(ResultDecision.objects.count(), 1)

    def test_returned_result_retained_and_new_run_can_be_approved(self):
        receipt, request = self.review()
        decide_results(self.f.reviewer, run_id=receipt['run_id'], outcome='returned', reason='Synthetic request for explanation', reviewed_token=request['review_token'])
        with self.assertRaises(IdempotencyConflict):
            decide_results(self.f.reviewer, run_id=receipt['run_id'], outcome='approved', reason='Cannot overwrite', reviewed_token=request['review_token'])
        new = self.calculate(key='recalculate', cutoff=timezone.now())
        new_request = request_review(self.f.actor, run_id=new['run_id'], reason='Synthetic explanation supplied')
        decide_results(self.f.reviewer, run_id=new['run_id'], outcome='approved', reason='Synthetic corrected set checked', reviewed_token=new_request['review_token'])
        self.assertEqual(ResultDecision.objects.count(), 2)
        self.assertEqual(ResultDecision.objects.get(review__run_id=receipt['run_id']).outcome, 'returned')

    def test_correction_preserves_old_approval_and_suppresses_differencing(self):
        receipt, request = self.review()
        old = decide_results(self.f.reviewer, run_id=receipt['run_id'], outcome='approved', reason='Synthetic original', reviewed_token=request['review_token'])
        new = self.calculate(key='correction', cutoff=timezone.now())
        new_request = request_review(self.f.actor, run_id=new['run_id'], reason='Synthetic correction')
        decide_results(self.f.reviewer, run_id=new['run_id'], outcome='approved', reason='Synthetic correction checked', reviewed_token=new_request['review_token'])
        newer = ResultDecision.objects.get(review__run_id=new['run_id'])
        self.assertEqual(str(newer.previous_approval.review.run_id), old['run_id'])
        for run_id in [old['run_id'], new['run_id']]:
            rows = review_summary(self.f.reviewer, run_id=run_id)['results']
            self.assertTrue(all(r['reason']=='restricted_revision' for r in rows))

    def test_revoked_owner_and_cross_scope_reviewer_are_denied(self):
        receipt, request = self.review()
        get_user_model().objects.filter(pk=self.f.staff.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            self.save()
        other_scope = AccessScope.objects.create(organization=self.f.org, code='OTHER', name='Other')
        outsider = get_user_model().objects.create_user(username='synthetic-other-reviewer')
        grant(outsider, other_scope, ['result.review', 'result.approve', 'calculation.validate'], 'synthetic-other-reviewer')
        with self.assertRaises(PermissionDenied):
            review_summary(outsider, run_id=receipt['run_id'])
        with self.assertRaises(PermissionDenied):
            decide_results(outsider, run_id=receipt['run_id'], outcome='approved', reason='No scope', reviewed_token=request['review_token'])

    def test_review_rejects_manual_subset_and_unsealed_source(self):
        self.close()
        receipt = record_calculation(self.f.actor, round_id=self.f.round.pk, inputs=[packet(self.f)], cutoff=timezone.now(), idempotency_key='manual')
        with self.assertRaises(StoredSourceSelection.DoesNotExist):
            request_review(self.f.actor, run_id=receipt.run_id, reason='Manual subset')

    def test_no_admin_registration_or_default_model_permissions(self):
        from django.contrib import admin
        for model in [SelfAssessmentAssignment, SelfAssessmentRevision, ResultDecision, ResultReviewRequest, StoredSourceSelection]:
            self.assertNotIn(model, admin.site._registry)
            self.assertEqual(model._meta.default_permissions, ())

    def test_html_owner_form_and_english_render_without_evidence_controls(self):
        self.client.force_login(self.f.staff)
        response = self.client.get('/workspace/self-assessments/'+self.f.assignment+'/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'F06-K01')
        self.assertNotContains(response, 'type="file"')
        self.assertNotContains(response, 'assessor_score')
        self.assertIn('no-store', response['Cache-Control'])
        with self.settings(LANGUAGE_CODE='en'):
            english = self.client.get('/workspace/self-assessments/'+self.f.assignment+'/', HTTP_ACCEPT_LANGUAGE='en')
            self.assertEqual(english.status_code, 200)
        self.client.force_login(self.f.actor)
        self.assertEqual(self.client.get('/workspace/self-assessments/'+self.f.assignment+'/').status_code, 403)

    def test_api_ownership_strict_payload_and_csrf(self):
        url = '/api/v1/me/self-assessments/'+self.f.assignment+'/submit/'
        self.assertEqual(self.client.get('/api/v1/me/self-assessments/').status_code, 401)
        self.client.force_login(self.f.staff)
        data = {'expected_revision':0, 'answers':self.f.answers, 'idempotency_key':'api-1'}
        self.assertEqual(self.client.post(url, {**data, 'assessor_score':5}, content_type='application/json').status_code, 422)
        self.assertEqual(self.client.post(url, data, content_type='application/json').status_code, 200)
        self.assertEqual(self.client.post(url, {**data, 'answers':{}}, content_type='application/json').status_code, 409)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.f.staff)
        self.assertEqual(csrf_client.post(url, data, content_type='application/json').status_code, 403)
        self.client.force_login(self.f.actor)
        self.assertEqual(self.client.post(url, data, content_type='application/json').status_code, 403)

    def test_owner_html_form_submits_with_real_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.f.staff)
        url = '/workspace/self-assessments/'+self.f.assignment+'/'
        self.assertEqual(client.get(url).status_code, 200)
        data = {qid:'value:4' for qid in self.f.answers}
        data.update(expected_revision=0, idempotency_key='html-submit', action='submitted',
                    csrfmiddlewaretoken=client.cookies['csrftoken'].value)
        response = client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SelfAssessmentRevision.objects.get().status, 'submitted')
        self.assertEqual(SelfAssessmentRevision.objects.get().answers['F06-K01']['value'], 4)

    def test_bootstrap_preset_does_not_expand_with_new_permissions(self):
        from apps.accounts.management.commands.bootstrap_organization import BOOTSTRAP_PERMISSIONS
        self.assertFalse({'calculation.source', 'calculation.run', 'result.approve',
                          'result.submit', 'result.review', 'selfassessment.assign'} & BOOTSTRAP_PERMISSIONS)
