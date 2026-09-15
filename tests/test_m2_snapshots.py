from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from io import StringIO
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import AccessScope, Role
from apps.auditlog.models import AuditEvent
from apps.calculations.codec import digest, engine_identity
from apps.calculations.engine import Attendance
from apps.calculations.models import CalculationInputSnapshot, CalculationRequest, CalculationRun, IndicatorResult
from apps.calculations.services import AttendanceSource, IdempotencyConflict, SeriesInput, record_calculation, validate_run
from tests.m2_fixtures import grant, packet, response_context, scenario


class CalculationSnapshotTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fixture = scenario()

    def run_calculation(self, inputs=None, key="synthetic-key", **kwargs):
        f = self.fixture
        return record_calculation(f.actor, round_id=f.round.pk, inputs=inputs or [packet(f)],
                                  cutoff=f.cutoff, idempotency_key=key, **kwargs)

    def test_persisted_manifest_has_versions_cutoff_sources_and_replays(self):
        receipt = self.run_calculation()
        run = CalculationRun.objects.get(pk=receipt.run_id)
        source = run.inputs.get()
        result = run.results.get()
        self.assertEqual(run.status, "complete")
        self.assertEqual((run.input_count, run.result_count), (1, 1))
        self.assertEqual(result.payload["value"], "100")
        self.assertEqual(run.input_hash, digest(run.manifest))
        self.assertEqual(source.source_hash, digest(source.payload))
        self.assertEqual(source.formula_hash, digest(source.definition["formula"]))
        self.assertEqual(source.question_hash, digest(source.definition["questions"]))
        self.assertEqual(source.payload["source_revisions"][0]["revision_number"], 1)
        self.assertEqual(run.engine_hash, engine_identity()["hash"])
        self.assertEqual(validate_run(self.fixture.actor, run_id=run.pk)["matched_results"], 1)
        # Caller gets no ORM object, scores, raw answer rows, numerator or denominator.
        self.assertEqual(set(receipt.__dict__), {"run_id", "input_hash", "result_count", "status", "reused"})

    def test_same_sources_and_retries_reuse_run_and_bind_actor_keys(self):
        a = self.run_calculation()
        audit_count = AuditEvent.objects.count()
        b = self.run_calculation()
        c = self.run_calculation(key="another-key")
        self.assertEqual((a.run_id, a.run_id), (b.run_id, c.run_id))
        self.assertTrue(b.reused and c.reused)
        self.assertEqual(CalculationRun.objects.count(), 1)
        self.assertEqual(CalculationRequest.objects.count(), 2)
        self.assertEqual(AuditEvent.objects.count(), audit_count+1)

    def test_same_key_different_sources_conflicts_without_overwriting(self):
        first = self.run_calculation()
        with self.assertRaises(IdempotencyConflict):
            self.run_calculation([packet(self.fixture, values=[3, 3], revision=2)])
        self.assertEqual(CalculationRun.objects.count(), 1)
        self.assertEqual(IndicatorResult.objects.get(run_id=first.run_id).payload["value"], "100")

    def test_correction_creates_new_run_and_old_snapshot_stays_replayable(self):
        a = self.run_calculation()
        b = self.run_calculation([packet(self.fixture, values=[3, 3], revision=2)], key="correction")
        self.assertNotEqual(a.run_id, b.run_id)
        self.assertEqual(IndicatorResult.objects.get(run_id=a.run_id).payload["value"], "100")
        self.assertEqual(IndicatorResult.objects.get(run_id=b.run_id).payload["value"], "0")
        for receipt in (a, b):
            self.assertEqual(validate_run(self.fixture.actor, run_id=receipt.run_id)["status"], "verified")

    def test_dry_run_has_no_database_or_audit_writes(self):
        before = AuditEvent.objects.count()
        receipt = self.run_calculation(dry_run=True)
        self.assertEqual(receipt.status, "dry_run")
        self.assertIsNone(receipt.run_id)
        self.assertFalse(CalculationRun.objects.exists())
        self.assertFalse(CalculationRequest.objects.exists())
        self.assertEqual(AuditEvent.objects.count(), before)

    def test_audit_failure_rolls_back_entire_run_and_all_children(self):
        before = AuditEvent.objects.count()
        with patch("apps.calculations.services._audit", side_effect=RuntimeError("synthetic failure")):
            with self.assertRaises(RuntimeError):
                self.run_calculation()
        for model in (CalculationRun, CalculationInputSnapshot, IndicatorResult, CalculationRequest):
            self.assertEqual(model.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), before)

    def test_permissions_are_explicit_and_rechecked_on_retry(self):
        f = self.fixture
        admin = get_user_model().objects.create_user(username="synthetic-superuser", is_staff=True, is_superuser=True)
        with self.assertRaises(PermissionDenied):
            record_calculation(admin, round_id=f.round.pk, inputs=[packet(f)], cutoff=f.cutoff, idempotency_key="admin")
        analyst = get_user_model().objects.create_user(username="synthetic-analyst")
        grant(analyst, f.scope, ["calculation.run"], "synthetic-analyst")
        with self.assertRaises(PermissionDenied):
            record_calculation(analyst, round_id=f.round.pk, inputs=[packet(f)], cutoff=f.cutoff, idempotency_key="analyst")
        receipt = self.run_calculation()
        with self.assertRaises(PermissionDenied):
            validate_run(analyst, run_id=receipt.run_id)
        get_user_model().objects.filter(pk=f.actor.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            self.run_calculation()

    def test_no_automatic_grants_and_no_privileged_admin_registration(self):
        from django.contrib import admin
        legacy = Role.objects.create(code="synthetic-legacy-role", permissions=["catalog.read"])
        self.assertEqual(legacy.permissions, ["catalog.read"])
        for model in (CalculationRun, CalculationInputSnapshot, IndicatorResult, CalculationRequest):
            self.assertNotIn(model, admin.site._registry)
            self.assertEqual(model._meta.default_permissions, ())

    def test_cross_scope_context_or_group_is_rejected(self):
        f = self.fixture
        source = packet(f)
        foreign = replace(source.responses[0], context=replace(source.responses[0].context, scope_id="other-scope"))
        with self.assertRaises(ValueError):
            self.run_calculation([replace(source, responses=(foreign,))])
        outsider = AccessScope.objects.create(organization=f.org, code="OTHER", name="Other scope")
        user = get_user_model().objects.create_user(username="synthetic-other-scope")
        grant(user, outsider, ["calculation.run", "calculation.source", "calculation.validate"], "synthetic-other-scope")
        with self.assertRaises(PermissionDenied):
            record_calculation(user, round_id=f.round.pk, inputs=[source], cutoff=f.cutoff, idempotency_key="other")
        receipt = self.run_calculation()
        with self.assertRaises(PermissionDenied):
            validate_run(user, run_id=receipt.run_id)

    def test_latest_revision_and_excluded_draft_do_not_change_idempotency(self):
        f = self.fixture
        original = packet(f)
        newer = packet(f, values=[3, 3], revision=2).responses[0]
        newer = replace(newer, submitted_at=f.cutoff)
        draft = replace(newer, revision_id="synthetic-draft", revision_number=3, status="draft", submitted_at=None)
        with_old_and_draft = replace(original, responses=(draft, original.responses[0], newer))
        a = self.run_calculation([with_old_and_draft])
        b = self.run_calculation([replace(original, responses=(newer,))])
        self.assertEqual(a.run_id, b.run_id)
        source = CalculationInputSnapshot.objects.get(run_id=a.run_id)
        self.assertEqual(source.payload["source_revisions"][0]["revision_number"], 2)

    def test_multiple_series_and_shared_anonymous_source_dont_link_roster(self):
        f = self.fixture
        a = packet(f, "7.2-13", unit="anonymous-response-1", values=[5])
        b = replace(a, binding_id=f.bindings["7.2-17"].pk)
        receipt = self.run_calculation([a, b])
        self.assertEqual(receipt.result_count, 2)
        for source in CalculationInputSnapshot.objects.filter(run_id=receipt.run_id):
            self.assertIsNone(source.payload["population"])
            self.assertNotIn("eligibility-org-A", json.dumps(source.payload))
            self.assertEqual(source.result.payload["denominator"], "1")
        self.assertEqual(validate_run(f.actor, run_id=receipt.run_id)["matched_results"], 2)

    def test_staff_uses_frozen_roster_including_nonrespondents(self):
        receipt = self.run_calculation([packet(self.fixture, "7.3-43", values=[3]*5)])
        result = IndicatorResult.objects.get(run_id=receipt.run_id)
        self.assertEqual(result.payload["value"], "50.0")
        self.assertEqual(result.payload["denominator"], "2")
        self.assertEqual(result.payload["counts"]["not_submitted"], 1)

    def test_attendance_dates_cutoff_and_latest_status_are_frozen(self):
        f = self.fixture
        record = Attendance("staff-A", "synthetic-course", "session-1", Decimal(3), categories=frozenset({"T45", "T46"}), status="accepted", evidence_verified=True)
        source = AttendanceSource("att-1", 1, response_context(f, "F05"), f.cutoff-timedelta(minutes=1), f.round.period.start_date, record)
        item = SeriesInput(f.round_instruments["F05"].pk, f.bindings["7.3-44"].pk, f.groups["ST1"].pk, attendance_sources=(source, source))
        receipt = self.run_calculation([item])
        self.assertEqual(IndicatorResult.objects.get(run_id=receipt.run_id).payload["value"], "1.5")
        rejected = replace(source, revision_id="att-2", revision_number=2, recorded_at=f.cutoff, attendance=replace(record, status="rejected"))
        correction = self.run_calculation([replace(item, attendance_sources=(source, rejected))], key="reject")
        self.assertEqual(IndicatorResult.objects.get(run_id=correction.run_id).payload["value"], "0")
        self.assertEqual(validate_run(f.actor, run_id=receipt.run_id)["status"], "verified")

    def test_replay_uses_snapshots_and_rejects_engine_drift(self):
        receipt = self.run_calculation()
        with patch("apps.calculations.services.Catalog", side_effect=AssertionError("must not load live catalog")):
            self.assertEqual(validate_run(self.fixture.actor, run_id=receipt.run_id)["status"], "verified")
        identity = engine_identity()
        with patch("apps.calculations.services.engine_identity", return_value={**identity, "hash": "a"*64}):
            with self.assertRaises(ValidationError):
                validate_run(self.fixture.actor, run_id=receipt.run_id)

    def test_orm_updates_deletion_and_child_appending_are_blocked(self):
        receipt = self.run_calculation()
        run = CalculationRun.objects.get(pk=receipt.run_id)
        for record in (run, run.inputs.get(), run.results.get(), run.requests.get()):
            with self.assertRaises(ValidationError):
                record.save()
            with self.assertRaises(ValidationError):
                record.delete()
            with self.assertRaises(ValidationError):
                type(record).objects.filter(pk=record.pk).delete()
        with self.assertRaises(ValidationError):
            CalculationRun.objects.filter(pk=run.pk).update(result_count=99)

    def test_duplicate_series_and_invalid_cutoff_leave_no_run(self):
        f = self.fixture
        with self.assertRaises(ValidationError):
            self.run_calculation([packet(f), packet(f)])
        for cutoff in (f.round.open_at-timedelta(seconds=1), timezone.now()+timedelta(days=1)):
            with self.assertRaises(ValidationError):
                record_calculation(f.actor, round_id=f.round.pk, inputs=[packet(f)], cutoff=cutoff, idempotency_key="bad")
        self.assertFalse(CalculationRun.objects.exists())

    def test_audit_and_validation_receipts_do_not_expose_raw_answers(self):
        receipt = self.run_calculation()
        messages = json.dumps(list(AuditEvent.objects.filter(action__startswith="calculation.").values_list("metadata", flat=True)))
        self.assertNotIn("staff-A", messages)
        self.assertNotIn("answers", messages)
        validation = validate_run(self.fixture.actor, run_id=receipt.run_id)
        self.assertNotIn("payload", validation)
        self.assertNotIn("numerator", validation)

    def test_validation_command_is_read_only_and_uses_explicit_actor_permission(self):
        receipt = self.run_calculation()
        output = StringIO()
        before = AuditEvent.objects.count()
        call_command("validate_results", run_id=receipt.run_id, actor_user_id=self.fixture.actor.pk, stdout=output)
        self.assertEqual(json.loads(output.getvalue())["status"], "verified")
        self.assertNotIn("staff-A", output.getvalue())
        self.assertEqual(AuditEvent.objects.count(), before)
        stranger = get_user_model().objects.create_user(username="synthetic-cli-stranger", is_superuser=True)
        with self.assertRaises(CommandError):
            call_command("validate_results", run_id=receipt.run_id, actor_user_id=stranger.pk, stdout=StringIO())

    def test_anonymous_multiple_submissions_are_not_treated_as_f06_revisions(self):
        first = packet(self.fixture, "7.2-13", unit="anonymous-response-1", values=[5])
        second = packet(self.fixture, "7.2-13", unit="anonymous-response-1", values=[3], revision=2)
        with self.assertRaises(ValidationError):
            self.run_calculation([replace(first, responses=first.responses+second.responses)])

    def test_source_cutoff_can_follow_close_but_survey_close_is_exclusive(self):
        f = self.fixture
        original = packet(f)
        late = replace(original.responses[0], revision_id="at-close", revision_number=2,
                       submitted_at=f.round.close_at)
        after_close = f.round.close_at+timedelta(minutes=1)
        with patch("apps.calculations.services.timezone.now", return_value=after_close):
            receipt = record_calculation(f.actor, round_id=f.round.pk, inputs=[replace(original, responses=original.responses+(late,))],
                                         cutoff=after_close, idempotency_key="close-boundary")
        source = CalculationInputSnapshot.objects.get(run_id=receipt.run_id)
        self.assertEqual(source.payload["source_revisions"][0]["revision_number"], 1)

    def test_future_activity_cannot_be_recorded_as_already_accepted(self):
        f = self.fixture
        record = Attendance("staff-A", "synthetic-future", "session-1", Decimal(3), status="accepted", evidence_verified=True)
        source = AttendanceSource("future-att", 1, response_context(f, "F05"), f.cutoff,
                                  f.cutoff.date()+timedelta(days=2), record)
        item = SeriesInput(f.round_instruments["F05"].pk, f.bindings["7.3-44"].pk, f.groups["ST1"].pk, attendance_sources=(source,))
        with self.assertRaises(ValidationError):
            self.run_calculation([item])
