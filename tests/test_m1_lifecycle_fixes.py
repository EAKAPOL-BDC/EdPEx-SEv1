"""Regression coverage for departed personnel and pinned historical wording."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Membership, Role, RoleAssignment
from apps.auditlog.models import AuditEvent
from apps.catalog.models import ContentTranslation, InstrumentVersion, TranslationBundle, source_hash
from apps.catalog.round_reading import round_respondent_text
from apps.catalog.services import respondent_text
from apps.rounds.models import CollectionRound, ResponsibilityAssignment, RoundInstrument
from apps.rounds.services import create_record, transition_round, update_record
from tests import test_m1_rounds as round_fixtures


class LifecycleFixtureMixin:
    """Reuse fixture builders without inheriting or repeating the old test cases."""

    period = round_fixtures.RoundDomainTests.period
    collection_round = round_fixtures.RoundDomainTests.collection_round
    population = round_fixtures.RoundDomainTests.population
    binding = round_fixtures.RoundDomainTests.binding
    ready_round = round_fixtures.RoundDomainTests.ready_round

    @classmethod
    def setUpTestData(cls):
        round_fixtures.RoundDomainTests.setUpTestData.__func__(cls)
        full_role = RoleAssignment.objects.get(membership__user=cls.actor, scope=cls.scope).role
        for field, scope, role in (
            ("current_manager", cls.scope, full_role),
            ("outside_manager", cls.other_scope, full_role),
            ("catalog_reader", cls.scope, Role.objects.create(code="history-catalog", permissions=["catalog.read"])),
            ("round_manager", cls.scope, Role.objects.create(code="history-round", permissions=["round.manage"])),
        ):
            user = get_user_model().objects.create_user(username=field)
            membership = Membership.objects.create(user=user, organization=cls.organization)
            RoleAssignment.objects.create(membership=membership, role=role, scope=scope)
            setattr(cls, field, user)
        foreign_membership = Membership.objects.get(user=cls.stranger, organization=cls.foreign_org)
        RoleAssignment.objects.create(membership=foreign_membership, role=full_role, scope=cls.foreign_scope)

    def depart(self, person):
        membership = Membership.objects.get(user=person, organization=self.organization)
        membership.is_active = False
        membership.save()

    def opened_round(self):
        collection_round, snapshot, member, binding = self.ready_round()
        collection_round = transition_round(self.actor, collection_round, "open")
        return collection_round, binding

    def retire(self, binding):
        version = InstrumentVersion.objects.get(pk=binding.instrument_version_id)
        version.status = "retired"
        version.save()
        return version

    def second_round(self, first, code="second-round"):
        return create_record(self.current_manager, CollectionRound, scope=self.scope, period=first.period,
            code=code, owner=self.current_manager, open_at=first.open_at,
            due_at=first.due_at, close_at=first.close_at, privacy_notice="Synthetic second-round notice")


class DepartedPersonnelTests(LifecycleFixtureMixin, TestCase):
    def test_current_manager_closes_round_after_owner_departure_and_keeps_history(self):
        collection_round, _ = self.opened_round()
        original_owner = collection_round.owner_id
        self.depart(self.actor)
        closed = transition_round(self.current_manager, collection_round, "closed", reason="Owner left; authorized manager closes")
        self.assertEqual(closed.status, "closed")
        self.assertEqual(closed.owner_id, original_owner)
        event = AuditEvent.objects.get(object_id=str(collection_round.pk), metadata__after_status="closed")
        self.assertEqual(event.actor_id, self.current_manager.pk)
        self.assertEqual(event.metadata["before_status"], "open")
        self.assertTrue(Membership.objects.filter(user_id=original_owner, is_active=False).exists())

    def test_departed_owner_and_wrong_scope_or_organization_cannot_close(self):
        collection_round, _ = self.opened_round()
        self.depart(self.actor)
        for actor in (self.actor, self.backup, self.outside_manager, self.stranger):
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                transition_round(actor, collection_round, "closed", reason="Unauthorized close")
        collection_round.refresh_from_db()
        self.assertEqual(collection_round.status, "open")
        self.assertFalse(AuditEvent.objects.filter(object_id=str(collection_round.pk), metadata__after_status="closed").exists())

    def test_deactivated_auth_owner_does_not_block_authorized_manager_closing(self):
        collection_round, _ = self.opened_round()
        self.actor.is_active = False
        self.actor.save(update_fields=["is_active"])
        closed = transition_round(self.current_manager, collection_round, "closed", reason="Account deactivated")
        self.assertEqual(closed.owner_id, self.actor.pk)
        self.assertEqual(closed.status, "closed")

    def test_new_or_changed_round_owner_must_still_be_active(self):
        collection_round = self.collection_round()
        self.depart(self.backup)
        with self.assertRaises(ValidationError):
            update_record(self.current_manager, collection_round, reason="Invalid new owner", owner=self.backup)
        with self.assertRaises(ValidationError):
            create_record(self.current_manager, CollectionRound, scope=self.scope, period=collection_round.period,
                code="invalid-new", owner=self.backup, open_at=collection_round.open_at,
                due_at=collection_round.due_at, close_at=collection_round.close_at)
        collection_round.refresh_from_db()
        self.assertEqual(collection_round.owner_id, self.actor.pk)

    def test_manager_ends_assignment_after_primary_and_backup_depart_without_replacing_them(self):
        start = timezone.now() - timedelta(days=1)
        assignment = create_record(self.current_manager, ResponsibilityAssignment, scope=self.scope,
            primary=self.actor, backup=self.backup, active_from=start, reason="Initial synthetic assignment")
        self.depart(self.actor)
        self.depart(self.backup)
        end = timezone.now()
        ended = update_record(self.current_manager, assignment, reason="People departed", active_until=end)
        self.assertEqual((ended.primary_id, ended.backup_id, ended.active_from), (self.actor.pk, self.backup.pk, start))
        self.assertEqual(ended.active_until, end)
        event = AuditEvent.objects.get(object_id=str(assignment.pk), action="responsibility.manage.update")
        self.assertEqual(event.actor_id, self.current_manager.pk)
        self.assertEqual(event.metadata["changed_fields"], ["active_until"])
        with self.assertRaises(ValidationError):
            update_record(self.current_manager, ended, reason="Reopen forbidden", active_until=None)

    def test_ending_departed_assignment_requires_current_matching_scope_permissions(self):
        assignment = create_record(self.current_manager, ResponsibilityAssignment, scope=self.scope,
            primary=self.actor, backup=self.backup, active_from=timezone.now() - timedelta(days=1))
        self.depart(self.actor)
        for actor in (self.actor, self.backup, self.outside_manager, self.stranger, self.round_manager):
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                update_record(actor, assignment, reason="Unauthorized ending", active_until=timezone.now())
        assignment.refresh_from_db()
        self.assertIsNone(assignment.active_until)

    def test_new_assignment_still_rejects_departed_primary_or_backup(self):
        self.depart(self.actor)
        for primary, backup in ((self.actor, self.backup), (self.backup, self.actor)):
            with self.subTest(primary=primary.username), self.assertRaises(ValidationError):
                create_record(self.current_manager, ResponsibilityAssignment, scope=self.scope,
                    primary=primary, backup=backup, active_from=timezone.now())


class PinnedRoundWordingTests(LifecycleFixtureMixin, TestCase):
    content_key = "F06-A01.text"

    def test_retired_wording_remains_readable_only_through_its_open_or_closed_round(self):
        collection_round, binding = self.opened_round()
        expected = round_respondent_text(self.current_manager, collection_round, binding, self.content_key, "en")
        version = self.retire(binding)
        for locale in ("th", "en"):
            self.assertTrue(round_respondent_text(self.current_manager, collection_round, binding, self.content_key, locale))
        with self.assertRaises(ValidationError):
            respondent_text(self.current_manager, binding.translation_bundle, self.content_key, "en")
        closed = transition_round(self.current_manager, collection_round, "closed", reason="Collection finished")
        self.assertEqual(round_respondent_text(self.current_manager, closed, binding, self.content_key, "en"), expected)
        version.refresh_from_db()
        self.assertEqual(version.status, "retired")
        self.assertEqual(version.assessment_method, "self_report")
        self.assertFalse(version.evidence_required or version.assessor_scoring)

    def test_history_read_requires_both_current_permissions_in_exact_scope(self):
        collection_round, binding = self.opened_round()
        self.retire(binding)
        for actor in (self.backup, self.outside_manager, self.stranger, self.catalog_reader, self.round_manager):
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                round_respondent_text(actor, collection_round, binding, self.content_key, "en")
        self.depart(self.current_manager)
        with self.assertRaises(PermissionDenied):
            round_respondent_text(self.current_manager, collection_round, binding, self.content_key, "en")

    def test_draft_and_ready_rounds_cannot_use_history_read_for_retired_versions(self):
        collection_round, _, _, binding = self.ready_round()
        self.retire(binding)
        with self.assertRaises(ValidationError):
            round_respondent_text(self.current_manager, collection_round, binding, self.content_key, "en")
        with self.assertRaises(ValidationError):
            transition_round(self.current_manager, collection_round, "open")
        draft = transition_round(self.current_manager, collection_round, "draft", reason="Select a supported replacement")
        with self.assertRaises(ValidationError):
            round_respondent_text(self.current_manager, draft, binding, self.content_key, "en")

    def test_submitted_binding_must_match_the_persisted_round_not_cached_relations(self):
        collection_round, binding = self.opened_round()
        second = self.second_round(collection_round)
        second_binding = create_record(self.current_manager, RoundInstrument, collection_round=second,
            instrument_version=binding.instrument_version, translation_bundle=binding.translation_bundle)
        self.retire(binding)
        # Spoofing cached objects does not change the submitted stable identities.
        second_binding.collection_round = collection_round
        second_binding.instrument_version = binding.instrument_version
        with self.assertRaises(ValidationError):
            round_respondent_text(self.current_manager, collection_round, second_binding, self.content_key, "en")
        draft_version = InstrumentVersion.objects.create(instrument=binding.instrument_version.instrument,
            version="draft-successor", title_th="Draft successor", assessment_method="self_report")
        draft_bundle = TranslationBundle.objects.create(instrument_version=draft_version, bundle_version="draft-wording")
        draft_marker = "UNREVIEWED DRAFT MUST NOT APPEAR"
        ContentTranslation.objects.create(bundle=draft_bundle, content_key=self.content_key, locale="en",
            text=draft_marker, source_hash=source_hash("Draft source"))
        binding.translation_bundle = draft_bundle
        binding.collection_round.scope = self.other_scope
        wording = round_respondent_text(self.current_manager, collection_round, binding, self.content_key, "en")
        self.assertTrue(wording)
        self.assertNotEqual(wording, draft_marker)

    def test_invalid_locale_and_nonrespondent_keys_have_no_fallback(self):
        collection_round, binding = self.opened_round()
        self.retire(binding)
        for key, locale in ((self.content_key, "fr"), ("raw-source", "en"), ("unknown-draft-key", "en")):
            with self.subTest(key=key, locale=locale), self.assertRaises(ValidationError):
                round_respondent_text(self.current_manager, collection_round, binding, key, locale)

    def test_retired_version_cannot_be_selected_for_new_binding_or_moved_to_new_round(self):
        collection_round, binding = self.opened_round()
        second = self.second_round(collection_round)
        before_retirement = create_record(self.current_manager, RoundInstrument, collection_round=second,
            instrument_version=binding.instrument_version, translation_bundle=binding.translation_bundle)
        self.retire(binding)
        with self.assertRaises(ValidationError):
            create_record(self.current_manager, RoundInstrument, collection_round=second,
                instrument_version=binding.instrument_version, translation_bundle=binding.translation_bundle, context="new")
        third = self.second_round(collection_round, code="third-round")
        with self.assertRaises(ValidationError):
            update_record(self.current_manager, before_retirement, reason="Move obsolete selection", collection_round=third)
        before_retirement.refresh_from_db()
        self.assertEqual(before_retirement.collection_round_id, second.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("UPDATE rounds_roundinstrument SET collection_round_id = %s WHERE id = %s", [third.pk, before_retirement.pk])

    def test_postgresql_rejects_new_retired_binding(self):
        collection_round, binding = self.opened_round()
        second = self.second_round(collection_round)
        self.retire(binding)
        import uuid
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("""INSERT INTO rounds_roundinstrument
                    (id, organization_id, created_at, updated_at, collection_round_id,
                     instrument_version_id, translation_bundle_id, context, configuration)
                    VALUES (%s, %s, NOW(), NOW(), %s, %s, %s, 'new', '{}'::jsonb)""",
                    [uuid.uuid4(), self.organization.pk, second.pk, binding.instrument_version_id, binding.translation_bundle_id])
        self.assertFalse(second.round_instruments.exists())

    def test_draft_english_is_never_returned_by_history_service(self):
        collection_round = self.collection_round()
        binding = self.binding(collection_round, publish=False)
        self.assertTrue(binding.translation_bundle.translations.filter(locale="en", status="draft").exists())
        with self.assertRaises(ValidationError):
            round_respondent_text(self.current_manager, collection_round, binding, self.content_key, "en")
