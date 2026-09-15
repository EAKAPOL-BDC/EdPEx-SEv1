"""Real PostgreSQL connections exercise snapshot locks, including direct SQL.

The first transaction deliberately remains open. Tests observe PostgreSQL's
blocking PID relation before releasing it; timing sleeps do not decide a race.
"""

from datetime import date, timedelta
from threading import Event, Thread
from time import monotonic
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, connections, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from apps.accounts.models import AccessScope, Membership, Organization, Role, RoleAssignment
from apps.rounds.models import (
    Calendar, CollectionRound, DataSource, PopulationMember, PopulationSnapshot,
    ReportingPeriod, RespondentGroup,
)
from apps.rounds.services import create_record, delete_draft, freeze_population, update_record


class PopulationConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor, "postgresql")
        self.actor = get_user_model().objects.create_user(username="population-lock-manager")
        org = Organization.objects.create(name="Synthetic population locks")
        scope = AccessScope.objects.create(organization=org, code="A", name="A")
        membership = Membership.objects.create(user=self.actor, organization=org)
        role = Role.objects.create(code="population-lock-manager", permissions=["population.manage"])
        RoleAssignment.objects.create(membership=membership, role=role, scope=scope)
        calendar = Calendar.objects.create(scope=scope, code="FY", label="FY", calendar_type="fiscal")
        period = ReportingPeriod.objects.create(calendar=calendar, code="FY2565", reporting_year_be=2565,
            start_date=date(2021, 10, 1), end_date=date(2022, 10, 1))
        now = timezone.now()
        self.round = CollectionRound.objects.create(scope=scope, period=period, code="r", owner=self.actor,
            open_at=now, due_at=now + timedelta(days=1), close_at=now + timedelta(days=2))
        self.source = DataSource.objects.create(scope=scope, title="Synthetic roster", location="test fixture",
            source_type="raw", original_method="Complete roster")
        self.group = RespondentGroup.objects.create(scope=scope, code="ST1", label="ST1")
        self.a = PopulationSnapshot.objects.create(collection_round=self.round, definition="A roster",
            counting_unit="person", version=1, counts_by_group={"ST1": 2}, source=self.source)
        self.b = PopulationSnapshot.objects.create(collection_round=self.round, definition="B roster",
            counting_unit="person", version=2, counts_by_group={"ST1": 1}, source=self.source)
        self.member = create_record(self.actor, PopulationMember, snapshot=self.a, group=self.group,
            eligible_unit_key="moving")
        self.staying = create_record(self.actor, PopulationMember, snapshot=self.a, group=self.group,
            eligible_unit_key="staying")
        create_record(self.actor, PopulationMember, snapshot=self.b, group=self.group, eligible_unit_key="b-member")

    def _start_worker(self, operation):
        ready = Event()
        outcome = {}

        def run():
            worker_db = connections["default"]
            try:
                worker_db.ensure_connection()
                with worker_db.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '8s'")
                    cursor.execute("SET statement_timeout = '12s'")
                    cursor.execute("SELECT pg_backend_pid()")
                    outcome["pid"] = cursor.fetchone()[0]
                ready.set()
                operation()
                outcome["ok"] = True
            except Exception as error:
                outcome["error"] = error
            finally:
                ready.set()
                worker_db.close()

        thread = Thread(target=run, daemon=True)
        thread.start()
        self.assertTrue(ready.wait(5), "Worker did not establish its separate PostgreSQL connection")
        return thread, outcome

    def _assert_blocked_by_this_transaction(self, thread, outcome):
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            holder = cursor.fetchone()[0]
        self.assertNotEqual(outcome.get("pid"), holder)
        deadline = monotonic() + 5
        while monotonic() < deadline and thread.is_alive():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_blocking_pids(%s)", [outcome["pid"]])
                blockers = cursor.fetchone()[0]
            if holder in blockers:
                return
            Event().wait(0.01)
        self.fail(f"Expected a real parent-row lock wait, got {outcome}")

    def _join(self, thread, outcome):
        thread.join(13)
        self.assertFalse(thread.is_alive(), "Population operation failed to finish after lock release")
        return outcome

    def _move(self, raw):
        if raw:
            with connections["default"].cursor() as cursor:
                cursor.execute("UPDATE rounds_populationmember SET snapshot_id = %s WHERE id = %s",
                               [self.b.pk, self.member.pk])
        else:
            update_record(self.actor, self.member, reason="Move synthetic eligibility", snapshot=self.b)

    def _assert_frozen_consistent(self, snapshot):
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.status, "frozen")
        self.assertEqual(snapshot.counts_by_group, {"ST1": snapshot.members.count()})

    def _freeze_wins(self, destination, raw):
        snapshot = self.b if destination else self.a
        thread = None
        try:
            with transaction.atomic():
                freeze_population(self.actor, snapshot)
                thread, outcome = self._start_worker(lambda: self._move(raw))
                self._assert_blocked_by_this_transaction(thread, outcome)
        finally:
            if thread:
                self._join(thread, outcome)
        self.assertIsInstance(outcome.get("error"), IntegrityError if raw else ValidationError)
        self.member.refresh_from_db()
        self.assertEqual(self.member.snapshot_id, self.a.pk)
        self._assert_frozen_consistent(snapshot)

    def _move_wins(self, destination, raw):
        snapshot = self.b if destination else self.a
        thread = None
        try:
            with transaction.atomic():
                self._move(raw)
                thread, outcome = self._start_worker(lambda: freeze_population(self.actor, snapshot))
                self._assert_blocked_by_this_transaction(thread, outcome)
        finally:
            if thread:
                self._join(thread, outcome)
        self.assertIsInstance(outcome.get("error"), ValidationError)
        self.member.refresh_from_db()
        self.assertEqual(self.member.snapshot_id, self.b.pk)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.status, "draft")
        snapshot = update_record(self.actor, snapshot, reason="Reconcile complete roster before freeze",
                                 counts_by_group={"ST1": snapshot.members.count()})
        freeze_population(self.actor, snapshot)
        self._assert_frozen_consistent(snapshot)

    def test_service_move_waits_for_source_freeze_then_rejects(self):
        self._freeze_wins(destination=False, raw=False)

    def test_service_move_waits_for_destination_freeze_then_rejects(self):
        self._freeze_wins(destination=True, raw=False)

    def test_sql_move_waits_for_source_freeze_then_rejects(self):
        self._freeze_wins(destination=False, raw=True)

    def test_sql_move_waits_for_destination_freeze_then_rejects(self):
        self._freeze_wins(destination=True, raw=True)

    def test_source_freeze_waits_for_service_move_and_rechecks_counts(self):
        self._move_wins(destination=False, raw=False)

    def test_destination_freeze_waits_for_service_move_and_rechecks_counts(self):
        self._move_wins(destination=True, raw=False)

    def test_source_freeze_waits_for_sql_move_and_rechecks_counts(self):
        self._move_wins(destination=False, raw=True)

    def test_destination_freeze_waits_for_sql_move_and_rechecks_counts(self):
        self._move_wins(destination=True, raw=True)

    def _add_or_delete(self, *, delete, raw):
        if not raw:
            if delete:
                delete_draft(self.actor, self.member, reason="Synthetic removal")
            else:
                create_record(self.actor, PopulationMember, snapshot=self.a, group=self.group,
                              eligible_unit_key="late-addition")
        else:
            with connections["default"].cursor() as cursor:
                if delete:
                    cursor.execute("DELETE FROM rounds_populationmember WHERE id = %s", [self.member.pk])
                else:
                    cursor.execute("""INSERT INTO rounds_populationmember
                        (id, created_at, updated_at, eligible_unit_key, employment_facts,
                         organization_id, snapshot_id, group_id)
                        VALUES (%s, now(), now(), %s, '{}'::jsonb, %s, %s, %s)""",
                        [uuid.uuid4(), "late-addition", self.a.organization_id, self.a.pk, self.group.pk])

    def _membership_change_waits_for_freeze(self, *, delete, raw):
        thread = None
        try:
            with transaction.atomic():
                freeze_population(self.actor, self.a)
                thread, outcome = self._start_worker(lambda: self._add_or_delete(delete=delete, raw=raw))
                self._assert_blocked_by_this_transaction(thread, outcome)
        finally:
            if thread:
                self._join(thread, outcome)
        self.assertIsInstance(outcome.get("error"), IntegrityError if raw else ValidationError)
        self._assert_frozen_consistent(self.a)

    def test_service_add_waits_for_freeze_then_rejects(self):
        self._membership_change_waits_for_freeze(delete=False, raw=False)

    def test_service_delete_waits_for_freeze_then_rejects(self):
        self._membership_change_waits_for_freeze(delete=True, raw=False)

    def test_sql_add_waits_for_freeze_then_rejects(self):
        self._membership_change_waits_for_freeze(delete=False, raw=True)

    def test_sql_delete_waits_for_freeze_then_rejects(self):
        self._membership_change_waits_for_freeze(delete=True, raw=True)

    def test_last_member_departure_cannot_freeze_an_empty_raw_roster_with_positive_counts(self):
        delete_draft(self.actor, self.staying, reason="Synthetic removal")
        self._move(raw=True)
        self.assertEqual(self.a.members.count(), 0)
        with self.assertRaises(ValidationError):
            freeze_population(self.actor, self.a)
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("UPDATE rounds_populationsnapshot SET status='frozen', frozen_at=now() WHERE id=%s",
                               [self.a.pk])
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, "draft")
        self.a = update_record(self.actor, self.a, reason="Explicit complete zero roster", counts_by_group={"ST1": 0})
        freeze_population(self.actor, self.a)
        self._assert_frozen_consistent(self.a)

    def test_aggregate_only_counts_remain_supported(self):
        source = DataSource.objects.create(scope=self.source.scope, title="Synthetic aggregate",
            location="Historical aggregate fixture", source_type="aggregate", original_method="Aggregate only")
        snapshot = PopulationSnapshot.objects.create(collection_round=self.round, definition="Aggregate without identities",
            counting_unit="person", version=3, counts_by_group={"ST1": 25}, source=source)
        freeze_population(self.actor, snapshot)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.status, "frozen")
        self.assertEqual(snapshot.counts_by_group, {"ST1": 25})
        self.assertEqual(snapshot.members.count(), 0)

    def test_stale_member_instance_uses_its_current_source_for_delete(self):
        held_member = PopulationMember.objects.get(pk=self.member.pk)
        self._move(raw=True)
        self.b = update_record(self.actor, self.b, reason="Reconcile B", counts_by_group={"ST1": 2})
        freeze_population(self.actor, self.b)
        with self.assertRaises(ValidationError):
            held_member.delete()
        self.assertTrue(PopulationMember.objects.filter(pk=self.member.pk, snapshot=self.b).exists())
        self._assert_frozen_consistent(self.b)

    def test_direct_sql_cannot_change_a_member_after_freeze_commits(self):
        freeze_population(self.actor, self.a)
        for sql, params in (
            ("UPDATE rounds_populationmember SET eligible_unit_key='changed' WHERE id=%s", [self.member.pk]),
            ("UPDATE rounds_populationmember SET snapshot_id=%s WHERE id=%s", [self.b.pk, self.member.pk]),
            ("DELETE FROM rounds_populationmember WHERE id=%s", [self.member.pk]),
        ):
            with self.subTest(sql=sql), self.assertRaises(IntegrityError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(sql, params)
        self._assert_frozen_consistent(self.a)
