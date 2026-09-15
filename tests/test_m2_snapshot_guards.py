"""PostgreSQL constraints and real concurrent transactions, not SQLite substitutes."""
from dataclasses import replace
from threading import Event, Thread
from time import monotonic
import unittest
import uuid

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase

from apps.calculations.codec import digest
from apps.calculations.models import CalculationInputSnapshot, CalculationRequest, CalculationRun, IndicatorResult
from apps.calculations.services import record_calculation
from tests.m2_fixtures import packet, scenario


def raw_clone(instance, **changes):
    fields = list(instance._meta.concrete_fields)
    values = {field.attname: getattr(instance, field.attname) for field in fields}
    values.update(id=uuid.uuid4(), **changes)
    quote = connection.ops.quote_name
    sql = "INSERT INTO " + quote(instance._meta.db_table) + " (" + ",".join(quote(f.column) for f in fields) + ") VALUES (" + ",".join(["%s"]*len(fields)) + ")"
    with connection.cursor() as cursor:
        cursor.execute(sql, [field.get_db_prep_save(values[field.attname], connection) for field in fields])
    return values["id"]


@unittest.skipUnless(connection.vendor == "postgresql", "Requires real PostgreSQL trigger enforcement")
class CalculationSnapshotGuardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.f = scenario()
        receipt = record_calculation(cls.f.actor, round_id=cls.f.round.pk, inputs=[packet(cls.f)], cutoff=cls.f.cutoff, idempotency_key="guard")
        cls.calculation_run = CalculationRun.objects.get(pk=receipt.run_id)

    def test_all_four_tables_reject_sql_update_and_delete(self):
        records = [self.calculation_run, self.calculation_run.inputs.get(), self.calculation_run.results.get(), self.calculation_run.requests.get()]
        for record in records:
            for operation in ("update", "delete"):
                with self.subTest(table=record._meta.db_table, operation=operation):
                    with self.assertRaises(IntegrityError), transaction.atomic():
                        with connection.cursor() as cursor:
                            table = connection.ops.quote_name(record._meta.db_table)
                            sql = f"UPDATE {table} SET created_at=created_at WHERE id=%s" if operation=="update" else f"DELETE FROM {table} WHERE id=%s"
                            cursor.execute(sql, [record.pk])

    def test_cannot_append_input_or_result_to_sealed_run(self):
        for record in (self.calculation_run.inputs.get(), self.calculation_run.results.get()):
            with self.assertRaises(IntegrityError), transaction.atomic():
                raw_clone(record, series_key="f"*64)

    def test_cannot_forge_a_complete_run_at_insert(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            raw_clone(self.calculation_run, input_hash="f"*64)

    def test_unsealed_run_cannot_commit_even_if_created_by_sql(self):
        manifest = {**self.calculation_run.manifest, "synthetic_unsealed": True}
        with self.assertRaises(IntegrityError), transaction.atomic():
            raw_clone(self.calculation_run, status="building", sealed_at=None, result_hash="", input_count=0, result_count=0,
                      manifest=manifest, input_hash=digest(manifest))
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS calc_run_must_seal IMMEDIATE")

    def test_seal_counts_must_match_actual_inputs_and_results(self):
        manifest = {**self.calculation_run.manifest, "synthetic_empty": True}
        with self.assertRaises(IntegrityError), transaction.atomic():
            run_id = raw_clone(self.calculation_run, status="building", sealed_at=None, result_hash="", input_count=0, result_count=0,
                               manifest=manifest, input_hash=digest(manifest))
            with connection.cursor() as cursor:
                cursor.execute("UPDATE calculations_calculationrun SET status='complete', sealed_at=now(), result_hash=%s, input_count=1, result_count=1 WHERE id=%s", ["a"*64, run_id])

    def test_receipt_hash_cannot_reference_a_different_request(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            raw_clone(self.calculation_run.requests.get(), idempotency_key="bad-key", request_hash="f"*64)


@unittest.skipUnless(connection.vendor == "postgresql", "Requires real PostgreSQL row locks")
class CalculationConcurrencyTests(TransactionTestCase):
    def test_concurrent_retries_commit_one_run_and_one_receipt(self):
        f = scenario()
        inputs = [packet(f)]
        ready, outcome = Event(), {}

        def concurrent_request():
            db = connections["default"]
            try:
                db.ensure_connection()
                with db.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                    cursor.execute("SET statement_timeout = '15s'")
                    cursor.execute("SELECT pg_backend_pid()")
                    outcome["pid"] = cursor.fetchone()[0]
                ready.set()
                actor = get_user_model().objects.get(pk=f.actor.pk)
                outcome["receipt"] = record_calculation(actor, round_id=f.round.pk, inputs=inputs, cutoff=f.cutoff, idempotency_key="concurrent")
            except Exception as exc:
                outcome["error"] = exc
            finally:
                ready.set()
                db.close()

        thread = Thread(target=concurrent_request, daemon=True)
        with transaction.atomic():
            first = record_calculation(f.actor, round_id=f.round.pk, inputs=inputs, cutoff=f.cutoff, idempotency_key="concurrent")
            thread.start()
            self.assertTrue(ready.wait(5))
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                holder = cursor.fetchone()[0]
            blocked = False
            deadline = monotonic()+5
            while monotonic() < deadline and thread.is_alive():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_blocking_pids(%s)", [outcome["pid"]])
                    blocked = holder in cursor.fetchone()[0]
                if blocked:
                    break
                Event().wait(0.01)
            self.assertTrue(blocked, "Retry must wait for the first round transaction")
        thread.join(16)
        self.assertFalse(thread.is_alive())
        self.assertNotIn("error", outcome)
        self.assertEqual(outcome["receipt"].run_id, first.run_id)
        self.assertTrue(outcome["receipt"].reused)
        self.assertEqual(CalculationRun.objects.count(), 1)
        self.assertEqual(CalculationRequest.objects.count(), 1)
