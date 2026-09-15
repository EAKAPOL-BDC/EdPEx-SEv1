"""Temporal, source-history and restricted population tests on the test database."""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import AccessScope, Membership, Organization, Role, RoleAssignment
from apps.auditlog.models import AuditEvent
from apps.catalog.models import (
    ContentTranslation, Instrument, InstrumentContent, InstrumentVersion,
    Question, TranslationBundle, source_hash,
)
from apps.catalog.services import approve_translation, publish_bundle, publish_instrument_version, source_texts
from apps.rounds.models import (
    Calendar, CollectionRound, DataSource, PopulationMember, PopulationSnapshot,
    ReportingPeriod, RespondentGroup, ResponsibilityAssignment, RoundInstrument,
)
from apps.rounds.services import (
    approve_period, create_record, freeze_population, records_for_scope,
    transition_round, update_record,
)


class RoundDomainTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="องค์กรทดสอบ")
        cls.scope = AccessScope.objects.create(organization=cls.organization, code="A", name="กลุ่ม A")
        cls.other_scope = AccessScope.objects.create(organization=cls.organization, code="B", name="กลุ่ม B")
        cls.foreign_org = Organization.objects.create(name="องค์กรอื่น")
        cls.foreign_scope = AccessScope.objects.create(organization=cls.foreign_org, code="A", name="อื่น")
        cls.actor = get_user_model().objects.create_user(username="round-manager")
        cls.backup = get_user_model().objects.create_user(username="backup")
        cls.stranger = get_user_model().objects.create_user(username="other-org")
        membership = Membership.objects.create(user=cls.actor, organization=cls.organization)
        Membership.objects.create(user=cls.backup, organization=cls.organization)
        Membership.objects.create(user=cls.stranger, organization=cls.foreign_org)
        role = Role.objects.create(code="test-round-manager", permissions=[
            "calendar.manage", "round.manage", "population.manage", "responsibility.manage", "source.manage",
            "catalog.edit", "catalog.publish", "translation.review", "catalog.read",
        ])
        RoleAssignment.objects.create(membership=membership, role=role, scope=cls.scope)
        cls.calendar = create_record(cls.actor, Calendar, scope=cls.scope, code="FY", label="ปีงบประมาณ", calendar_type="fiscal")

    def period(self, **overrides):
        values = dict(calendar=self.calendar, code="FY2565", reporting_year_be=2565,
                      start_date=date(2021, 10, 1), end_date=date(2022, 10, 1))
        values.update(overrides)
        return create_record(self.actor, ReportingPeriod, **values)

    def collection_round(self):
        period = approve_period(self.actor, self.period(), reason="ยืนยันวันจากปฏิทินองค์กรทดสอบ")
        now = timezone.now()
        return create_record(self.actor, CollectionRound, scope=self.scope, period=period,
                             code="test-round", owner=self.actor, open_at=now - timedelta(hours=1),
                             due_at=now + timedelta(days=1), close_at=now + timedelta(days=2),
                             privacy_notice="ใช้ข้อมูลตามสิทธิ์ขององค์กร")

    def population(self, collection_round, *, members=True):
        group = create_record(self.actor, RespondentGroup, scope=self.scope, code="ST1", label="บุคลากรวิชาการ")
        source = create_record(self.actor, DataSource, scope=self.scope, title="แหล่งประชากรในกรณีทดสอบ",
                               location="ข้อมูลทดสอบสำหรับสิทธิ์", source_type="raw" if members else "aggregate",
                               original_method="ทะเบียนประชากรตามวันที่ตัดยอด")
        snapshot = create_record(self.actor, PopulationSnapshot, collection_round=collection_round,
                                 definition="รายชื่อจริง ณ วันตัดยอดในกรณีทดสอบ", counting_unit="person",
                                 counts_by_group={"ST1": 1}, source=source)
        member = None
        if members:
            member = create_record(self.actor, PopulationMember, snapshot=snapshot, group=group,
                                   eligible_unit_key="restricted-fixture-1", employment_facts={"staff_type": "ST1"})
        return snapshot, member

    def binding(self, collection_round, *, publish=True):
        instrument = Instrument.objects.create(scope=self.scope, code="F06")
        version = InstrumentVersion.objects.create(instrument=instrument, version="test-1", title_th="แบบทดสอบระบบ",
                                                    assessment_method="self_report", instructions_curated=True)
        Question.objects.create(version=version, question_id="F06-A01", text_th="ประเมินตนเอง", answer_type="integer_scale")
        InstrumentContent.objects.create(version=version, content_key="test-instructions", kind="instruction",
                                         text_th="ประเมินตนเอง ไม่บังคับหลักฐาน", audience="respondent")
        bundle = TranslationBundle.objects.create(instrument_version=version, bundle_version="test-1")
        for key, original in source_texts(version).items():
            for locale in ("th", "en"):
                entry = ContentTranslation.objects.create(bundle=bundle, content_key=key, locale=locale,
                    text=original if locale == "th" else "Self-report test wording, no mandatory evidence.", source_hash=source_hash(original))
                if publish:
                    approve_translation(self.actor, entry)
        if publish:
            bundle = publish_bundle(self.actor, bundle)
            version = publish_instrument_version(self.actor, version)
        return create_record(self.actor, RoundInstrument, collection_round=collection_round,
                             instrument_version=version, translation_bundle=bundle)

    def ready_round(self):
        collection_round = self.collection_round()
        snapshot, member = self.population(collection_round)
        freeze_population(self.actor, snapshot)
        binding = self.binding(collection_round)
        collection_round = transition_round(self.actor, collection_round, "ready")
        return collection_round, snapshot, member, binding

    def test_fiscal_2565_can_begin_in_2021_and_dates_are_not_inferred(self):
        period = self.period()
        self.assertEqual(period.start_date, date(2021, 10, 1))
        self.assertEqual(period.reporting_year_be, 2565)
        with self.assertRaises(ValidationError):
            self.period(code="old", reporting_year_be=2564)

    def test_half_open_adjacent_periods_and_child_containment(self):
        parent = self.period()
        self.period(code="Q1", parent=parent, start_date=date(2021, 10, 1), end_date=date(2022, 1, 1))
        self.period(code="Q2", parent=parent, start_date=date(2022, 1, 1), end_date=date(2022, 4, 1))
        with self.assertRaises(ValidationError):
            self.period(code="outside", parent=parent, start_date=date(2021, 9, 30), end_date=date(2021, 10, 1))
        with self.assertRaises(ValidationError):
            self.period(code="overlap", parent=parent, start_date=date(2021, 12, 1), end_date=date(2022, 2, 1))

    def test_approved_period_is_immutable_but_revision_is_allowed(self):
        period = approve_period(self.actor, self.period(), reason="องค์กรยืนยัน")
        period.end_date = date(2022, 11, 1)
        with self.assertRaises(ValidationError):
            period.save()
        with self.assertRaises(ValidationError):
            period.delete()
        revised = self.period(version=2, end_date=date(2022, 11, 1))
        self.assertFalse(revised.approved)
        self.assertEqual(ReportingPeriod.objects.get(pk=period.pk).end_date, date(2022, 10, 1))

    def test_service_denies_cross_user_scope_and_organization(self):
        for actor, scope in ((self.backup, self.scope), (self.actor, self.other_scope), (self.actor, self.foreign_scope)):
            with self.subTest(actor=actor.username, scope=scope.pk), self.assertRaises(PermissionDenied):
                create_record(actor, Calendar, scope=scope, code="forbidden", label="x", calendar_type="calendar")
        with self.assertRaises(PermissionDenied):
            update_record(self.actor, self.calendar, reason="try moving scope", scope=self.other_scope)
        self.calendar.refresh_from_db()
        self.assertEqual(self.calendar.scope, self.scope)

    def test_restricted_population_read_requires_matching_scope_grant(self):
        snapshot, member = self.population(self.collection_round())
        self.assertEqual(list(records_for_scope(self.actor, PopulationMember, self.scope)), [member])
        with self.assertRaises(PermissionDenied):
            records_for_scope(self.backup, PopulationMember, self.scope)
        with self.assertRaises(PermissionDenied):
            records_for_scope(self.actor, PopulationMember, self.other_scope)
        fields = {field.name for field in PopulationMember._meta.fields}
        self.assertFalse(fields & {"response", "survey_response", "answer", "invitation"})

    def test_foreign_group_cannot_enter_population(self):
        snapshot, _ = self.population(self.collection_round(), members=False)
        group = RespondentGroup.objects.create(scope=self.other_scope, code="ST1", label="อื่น")
        with self.assertRaises(ValidationError):
            create_record(self.actor, PopulationMember, snapshot=snapshot, group=group, eligible_unit_key="x")

    def test_freeze_validates_counts_and_preserves_member_history(self):
        snapshot, member = self.population(self.collection_round())
        snapshot.counts_by_group = {"ST1": 2}
        snapshot.save()
        with self.assertRaises(ValidationError):
            freeze_population(self.actor, snapshot)
        snapshot.counts_by_group = {"ST1": 1}
        snapshot.save()
        freeze_population(self.actor, snapshot)
        # The held member has a stale draft snapshot object: saved DB state wins.
        member.eligible_unit_key = "changed"
        with self.assertRaises(ValidationError):
            member.save()
        with self.assertRaises(ValidationError):
            member.delete()
        with self.assertRaises(ValidationError):
            PopulationMember.objects.filter(pk=member.pk).update(eligible_unit_key="bulk")
        with self.assertRaises(ValidationError):
            PopulationSnapshot.objects.filter(pk=snapshot.pk).delete()

    def test_draft_english_cannot_activate_round(self):
        collection_round = self.collection_round()
        snapshot, _ = self.population(collection_round)
        freeze_population(self.actor, snapshot)
        self.binding(collection_round, publish=False)
        with self.assertRaises(ValidationError):
            transition_round(self.actor, collection_round, "ready")
        collection_round.refresh_from_db()
        self.assertEqual(collection_round.status, "draft")
        self.assertTrue(ContentTranslation.objects.filter(locale="en", status="draft").exists())

    def test_open_pins_versions_population_and_enforces_server_window(self):
        collection_round, snapshot, member, binding = self.ready_round()
        opened = transition_round(self.actor, collection_round, "open")
        self.assertEqual(opened.population_snapshot_id, snapshot.pk)
        self.assertTrue(opened.accepting_at(opened.open_at))
        self.assertTrue(opened.accepting_at(opened.due_at + timedelta(seconds=1)))
        self.assertFalse(opened.accepting_at(opened.close_at))
        binding.context = "changed"
        with self.assertRaises(ValidationError):
            binding.save()
        with self.assertRaises(ValidationError):
            binding.delete()
        with self.assertRaises(ValidationError):
            update_record(self.actor, opened, reason="เปลี่ยนวัน", close_at=opened.close_at + timedelta(days=1))
        self.assertEqual(RoundInstrument.objects.get(pk=binding.pk).translation_bundle_id, binding.translation_bundle_id)

    def test_round_status_changes_only_through_service_and_no_fake_calculation(self):
        collection_round = self.collection_round()
        collection_round.status = "open"
        with self.assertRaises(ValidationError):
            collection_round.save()
        with self.assertRaises(ValidationError):
            transition_round(self.actor, collection_round, "approved")
        with self.assertRaises(ValidationError):
            update_record(self.actor, collection_round, reason="bypass", status="open")

    def test_primary_backup_need_active_membership_and_reassignment_retains_history(self):
        now = timezone.now()
        assignment = create_record(self.actor, ResponsibilityAssignment, scope=self.scope, primary=self.actor,
                                   backup=self.backup, active_from=now)
        for invalid in (self.actor, self.stranger):
            with self.assertRaises(ValidationError):
                create_record(self.actor, ResponsibilityAssignment, scope=self.scope, primary=self.actor,
                              backup=invalid, active_from=now)
        with self.assertRaises(ValidationError):
            update_record(self.actor, assignment, reason="transfer", primary=self.backup, backup=self.actor)
        end = now + timedelta(days=1)
        ended = update_record(self.actor, assignment, reason="transfer effective tomorrow", active_until=end)
        successor = create_record(self.actor, ResponsibilityAssignment, scope=self.scope, primary=self.backup,
                                  backup=self.actor, active_from=end)
        self.assertEqual(ended.primary_id, self.actor.pk)
        self.assertEqual(successor.primary_id, self.backup.pk)
        with self.assertRaises(ValidationError):
            ended.delete()

    def test_owner_from_another_organization_is_rejected(self):
        collection_round = self.collection_round()
        with self.assertRaises(ValidationError):
            update_record(self.actor, collection_round, reason="invalid owner", owner=self.stranger)

    def test_data_source_keeps_unknown_legacy_and_actual_recorded_time(self):
        before = timezone.now()
        source = create_record(self.actor, DataSource, scope=self.scope, title="รายงานเดิมปี 2565", location="รายงาน หน้า 4",
                               source_type="aggregate", occurred_at=date(2021, 12, 1),
                               limitations="ไม่ทราบวิธีวัดและรุ่นเดิม ไม่มีข้อมูลรายคน")
        self.assertIsNone(source.original_method)
        self.assertIsNone(source.instrument_version_original)
        self.assertGreaterEqual(source.recorded_at, before)
        source.title = "overwrite"
        with self.assertRaises(ValidationError):
            source.save()
        revision = create_record(self.actor, DataSource, scope=self.scope, title="แก้ชื่ออ้างอิง", location="รายงาน หน้า 5",
                                 source_type="aggregate", limitations="ยังไม่ทราบรุ่นเดิม", supersedes=source, revision=2)
        self.assertEqual(revision.supersedes_id, source.pk)
        self.assertEqual(DataSource.objects.get(pk=source.pk).title, "รายงานเดิมปี 2565")
        self.assertEqual(PopulationMember.objects.count(), 0)

    def test_audit_records_scope_without_population_identity(self):
        snapshot, member = self.population(self.collection_round())
        events = AuditEvent.objects.filter(object_id=str(member.pk))
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.first().metadata["scope_id"], str(self.scope.pk))
        self.assertNotIn("restricted-fixture-1", str(events.first().metadata))

    def test_f06_binding_has_no_assessor_or_mandatory_evidence_override(self):
        collection_round = self.collection_round()
        binding = self.binding(collection_round, publish=False)
        self.assertEqual(binding.instrument_version.assessment_method, "self_report")
        binding.configuration = {"evidence_required": True, "assessor_scoring": True}
        with self.assertRaises(ValidationError):
            binding.save()

    def test_fk_protect_preserves_parent_and_catalog_dependencies(self):
        collection_round = self.collection_round()
        binding = self.binding(collection_round, publish=False)
        with self.assertRaises(ProtectedError):
            self.calendar.delete()
        with self.assertRaises(ProtectedError):
            binding.instrument_version.delete()

    def test_postgresql_rejects_raw_frozen_population_and_period_edits(self):
        collection_round = self.collection_round()
        snapshot, member = self.population(collection_round)
        freeze_population(self.actor, snapshot)
        for sql, values in (
            ("UPDATE rounds_populationmember SET eligible_unit_key = %s WHERE id = %s", ["tampered", member.pk]),
            ("UPDATE rounds_populationsnapshot SET definition = %s WHERE id = %s", ["tampered", snapshot.pk]),
            ("UPDATE rounds_reportingperiod SET code = %s WHERE id = %s", ["tampered", collection_round.period_id]),
        ):
            with self.subTest(sql=sql), self.assertRaises(IntegrityError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(sql, values)
        member.refresh_from_db()
        self.assertEqual(member.eligible_unit_key, "restricted-fixture-1")

    def test_postgresql_rejects_used_binding_and_provenance_overwrite(self):
        collection_round, _, _, binding = self.ready_round()
        source = create_record(self.actor, DataSource, scope=self.scope, title="ต้นฉบับ", location="หน้า 1",
                               source_type="aggregate", limitations="ไม่ทราบวิธีเดิม")
        for sql, values in (
            ("UPDATE rounds_roundinstrument SET context = %s WHERE id = %s", ["tampered", binding.pk]),
            ("UPDATE rounds_datasource SET title = %s WHERE id = %s", ["tampered", source.pk]),
        ):
            with self.subTest(sql=sql), self.assertRaises(IntegrityError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(sql, values)

    def test_cached_parent_cannot_redirect_scoped_authorization(self):
        foreign_calendar = Calendar.objects.create(scope=self.other_scope, code="foreign", label="อื่น", calendar_type="calendar")
        # A submitted object may carry stale or mutated cached relations. Only its
        # real persisted FK identity is authoritative for service authorization.
        foreign_calendar.scope = self.scope
        with self.assertRaises(PermissionDenied):
            create_record(self.actor, ReportingPeriod, calendar=foreign_calendar, code="forbidden",
                          reporting_year_be=2565, start_date=date(2022, 1, 1), end_date=date(2023, 1, 1))
        self.assertFalse(ReportingPeriod.objects.filter(code="forbidden").exists())

    def test_population_freeze_requires_source_and_rejects_foreign_source(self):
        snapshot, _ = self.population(self.collection_round())
        snapshot.source = None
        snapshot.save()
        with self.assertRaises(ValidationError):
            freeze_population(self.actor, snapshot)
        foreign_source = DataSource.objects.create(scope=self.other_scope, title="ต่างขอบเขต", location="หน้า 1",
                                                  source_type="aggregate", limitations="ไม่ทราบวิธีเดิม")
        with self.assertRaises(ValidationError):
            update_record(self.actor, snapshot, reason="wrong source", source=foreign_source)
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("UPDATE rounds_populationsnapshot SET source_id = %s WHERE id = %s", [foreign_source.pk, snapshot.pk])

    def test_dependent_parent_scope_cannot_be_moved_by_raw_sql(self):
        collection_round = self.collection_round()
        snapshot, _ = self.population(collection_round)
        foreign_calendar = Calendar.objects.create(scope=self.other_scope, code="foreign", label="อื่น", calendar_type="calendar")
        foreign_period = ReportingPeriod.objects.create(calendar=foreign_calendar, code="FY", reporting_year_be=2565,
                                                       start_date=date(2022, 1, 1), end_date=date(2023, 1, 1))
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("UPDATE rounds_collectionround SET scope_id = %s, period_id = %s WHERE id = %s",
                               [self.other_scope.pk, foreign_period.pk, collection_round.pk])
        another = create_record(self.actor, CollectionRound, scope=self.scope, period=collection_round.period,
                                code="second", owner=self.actor, open_at=collection_round.open_at,
                                due_at=collection_round.due_at, close_at=collection_round.close_at)
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("UPDATE rounds_populationsnapshot SET collection_round_id = %s WHERE id = %s",
                               [another.pk, snapshot.pk])

    def test_count_only_population_preserves_its_group_definition(self):
        snapshot, _ = self.population(self.collection_round(), members=False)
        freeze_population(self.actor, snapshot)
        group = RespondentGroup.objects.get(scope=self.scope, code="ST1")
        group.label = "changed"
        with self.assertRaises(ValidationError):
            group.save()
        with self.assertRaises(ValidationError):
            group.delete()
        for sql in ("UPDATE rounds_respondentgroup SET label = 'changed' WHERE id = %s", "DELETE FROM rounds_respondentgroup WHERE id = %s"):
            with self.assertRaises(IntegrityError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(sql, [group.pk])

    def test_postgresql_allows_deleting_an_unreferenced_draft_calendar(self):
        calendar = create_record(self.actor, Calendar, scope=self.scope, code="scratch", label="draft", calendar_type="custom")
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM rounds_calendar WHERE id = %s", [calendar.pk])
        self.assertFalse(Calendar.objects.filter(pk=calendar.pk).exists())

    def test_draft_round_can_adopt_new_population_revision_without_overwriting_old(self):
        collection_round, old_snapshot, old_member, _ = self.ready_round()
        draft = transition_round(self.actor, collection_round, "draft", reason="แก้กรอบประชากรก่อนเปิดจริง")
        old_snapshot.refresh_from_db()
        new_snapshot = create_record(self.actor, PopulationSnapshot, collection_round=draft,
                                     definition="นิยามปรับใหม่ในกรณีทดสอบ", counting_unit="person", version=2,
                                     counts_by_group={"ST1": 0}, source=old_snapshot.source)
        freeze_population(self.actor, new_snapshot)
        ready = transition_round(self.actor, draft, "ready")
        self.assertEqual(ready.population_snapshot_id, new_snapshot.pk)
        self.assertEqual(PopulationSnapshot.objects.get(pk=old_snapshot.pk).counts_by_group, {"ST1": 1})
        self.assertTrue(PopulationMember.objects.filter(pk=old_member.pk, snapshot=old_snapshot).exists())
