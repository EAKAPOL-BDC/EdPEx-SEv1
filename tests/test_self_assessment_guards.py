"""PostgreSQL-only immutability and real concurrent F06 submission checks."""
from threading import Event, Thread
from time import monotonic
import unittest

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from apps.calculations.models import CalculationRun, ResultDecision, ResultReviewRequest, StoredSourceSelection
from apps.calculations.review import decide_results, request_review
from apps.rounds.services import transition_round
from apps.selfassessments.models import SelfAssessmentAssignment, SelfAssessmentRevision
from apps.selfassessments.services import calculate_self_assessments, save_revision
from tests.test_m2_snapshot_guards import raw_clone
from tests.test_self_assessments import self_scenario


def submit(f, actor=None):
    return save_revision(actor or f.staff, assignment_id=f.assignment, expected_revision=0,
                         status='submitted', answers=f.answers, idempotency_key='postgres-source')


def reviewed(f):
    submit(f)
    transition_round(f.actor, f.round, 'closed', reason='Synthetic close')
    receipt = calculate_self_assessments(f.analyst, round_instrument_id=f.round_instruments['F06'].pk,
        cutoff=timezone.now(), idempotency_key='postgres-calculate')
    request = request_review(f.actor, run_id=receipt['run_id'], reason='Synthetic review')
    decide_results(f.reviewer, run_id=receipt['run_id'], outcome='approved', reason='Synthetic check', reviewed_token=request['review_token'])
    return CalculationRun.objects.get(pk=receipt['run_id'])


@unittest.skipUnless(connection.vendor=='postgresql', 'Requires PostgreSQL triggers')
class SelfAssessmentGuardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.f = self_scenario()

    def test_all_five_new_tables_reject_sql_update_and_delete(self):
        calc = reviewed(self.f)
        records = [SelfAssessmentAssignment.objects.get(pk=self.f.assignment), SelfAssessmentRevision.objects.get(),
                   StoredSourceSelection.objects.get(run=calc), ResultReviewRequest.objects.get(run=calc), ResultDecision.objects.get()]
        for row in records:
            for operation in ('update', 'delete'):
                with self.subTest(table=row._meta.db_table, operation=operation):
                    with self.assertRaises(IntegrityError), transaction.atomic():
                        with connection.cursor() as cursor:
                            table = connection.ops.quote_name(row._meta.db_table)
                            sql = f'UPDATE {table} SET created_at=created_at WHERE id=%s' if operation=='update' else f'DELETE FROM {table} WHERE id=%s'
                            cursor.execute(sql, [row.pk])

    def test_sql_assignment_after_open_is_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            raw_clone(SelfAssessmentAssignment.objects.get(pk=self.f.assignment))

    def test_sql_revision_after_close_is_rejected(self):
        submit(self.f)
        row = SelfAssessmentRevision.objects.get()
        transition_round(self.f.actor, self.f.round, 'closed', reason='Synthetic close')
        with self.assertRaises(IntegrityError), transaction.atomic():
            raw_clone(row, revision=2, idempotency_key='late')

    def test_sql_revision_with_unknown_evidence_field_or_invalid_score_is_rejected(self):
        submit(self.f)
        row = SelfAssessmentRevision.objects.get()
        for answer in [{'status':'answered','value':6}, {'status':'answered','value':4,'evidence':'fake'}]:
            with self.subTest(answer=answer):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    raw_clone(row, revision=2, idempotency_key='bad', answers={**row.answers, 'F06-K01':answer})

    def test_sql_revision_sequence_cannot_skip(self):
        submit(self.f)
        with self.assertRaises(IntegrityError), transaction.atomic():
            raw_clone(SelfAssessmentRevision.objects.get(), revision=4, idempotency_key='skipped')

    def test_sql_decision_requires_independence_and_exact_token(self):
        reviewed(self.f)
        row = ResultDecision.objects.get()
        for changes in [{'actor_id':self.f.actor.pk}, {'reviewed_token':'f'*64}]:
            with self.subTest(changes=changes):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    raw_clone(row, **changes)


@unittest.skipUnless(connection.vendor=='postgresql', 'Requires PostgreSQL row locks')
class SelfAssessmentConcurrencyTests(TransactionTestCase):
    def test_same_request_submitted_concurrently_commits_one_revision(self):
        f = self_scenario()
        ready, outcome = Event(), {}
        def retry():
            db = connections['default']
            try:
                db.ensure_connection()
                with db.cursor() as cursor:
                    cursor.execute("SET lock_timeout='10s'")
                    cursor.execute("SET statement_timeout='15s'")
                    cursor.execute('SELECT pg_backend_pid()')
                    outcome['pid'] = cursor.fetchone()[0]
                ready.set()
                outcome['receipt'] = submit(f, get_user_model().objects.get(pk=f.staff.pk))
            except Exception as exc:
                outcome['error'] = exc
            finally:
                ready.set()
                db.close()
        thread = Thread(target=retry, daemon=True)
        try:
            with transaction.atomic():
                first = submit(f)
                thread.start()
                self.assertTrue(ready.wait(5))
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    holder = cursor.fetchone()[0]
                blocked, deadline = False, monotonic()+5
                while thread.is_alive() and monotonic()<deadline:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT pg_blocking_pids(%s)', [outcome['pid']])
                        blocked = holder in cursor.fetchone()[0]
                    if blocked:
                        break
                    Event().wait(.01)
                self.assertTrue(blocked, 'Retry must wait for the original round transaction')
        finally:
            if thread.ident is not None:
                thread.join(16)
        self.assertFalse(thread.is_alive())
        self.assertNotIn('error', outcome)
        self.assertEqual(first['revision'], outcome['receipt']['revision'])
        self.assertTrue(outcome['receipt']['reused'])
        self.assertEqual(SelfAssessmentRevision.objects.count(), 1)
