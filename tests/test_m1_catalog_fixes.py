"""PR #3 review regressions, including two independent PostgreSQL connections."""
from queue import Queue
from threading import Event, Thread
from time import monotonic

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections, transaction
from django.test import TestCase, TransactionTestCase

from apps.auditlog.models import AuditEvent
from apps.accounts.models import Membership, Role, RoleAssignment
from apps.catalog.models import ContentTranslation, LocalizedLabel, TranslationBundle, source_hash
from apps.catalog.services import (
    approve_translation, clone_instrument_version, edit_translation,
    localized_label_review_snapshot, publish_bundle, publish_localized_label,
    review_localized_label, translation_review_snapshot, update_question,
)
from tests.test_m1_catalog import CatalogFixtures


class CatalogReviewFixTests(CatalogFixtures, TestCase):
    def test_stale_translation_review_cannot_approve_or_publish_changed_text(self):
        version, question, bundle = self.instrument()
        entry = bundle.translations.get(content_key=f"{question.question_id}.text", locale="en")
        for other in bundle.translations.exclude(pk=entry.pk):
            approve_translation(self.actor, other, reviewed_token=translation_review_snapshot(self.actor, other)["reviewed_token"])
        seen_a = translation_review_snapshot(self.actor, entry)
        self.assertEqual(seen_a["source_text"], question.text_th)
        self.assertEqual(seen_a["translation_text"], entry.text)
        edit_translation(self.actor, entry, "Changed B")
        count_before = AuditEvent.objects.filter(action="catalog.translation_approved").count()
        with self.assertRaisesMessage(ValidationError, "changed"):
            approve_translation(self.actor, entry, reviewed_token=seen_a["reviewed_token"])
        entry.refresh_from_db()
        self.assertEqual((entry.text, entry.status, entry.reviewed_by_id), ("Changed B", "needs_review", None))
        self.assertIsNone(entry.reviewed_at)
        self.assertEqual(AuditEvent.objects.filter(action="catalog.translation_approved").count(), count_before)
        with self.assertRaises(ValidationError):
            publish_bundle(self.actor, bundle)
        seen_b = translation_review_snapshot(self.actor, entry)
        approve_translation(self.actor, entry, reviewed_token=seen_b["reviewed_token"])
        self.assertEqual(publish_bundle(self.actor, bundle).status, "published")

    def test_review_requires_explicit_snapshot_and_binds_source_and_entry(self):
        _, question, bundle = self.instrument()
        entry = bundle.translations.get(content_key=f"{question.question_id}.text", locale="en")
        seen = translation_review_snapshot(self.actor, entry)
        with self.assertRaises(TypeError):
            approve_translation(self.actor, entry)
        with self.assertRaises(ValidationError):
            approve_translation(self.actor, bundle.translations.exclude(pk=entry.pk).first(), reviewed_token=seen["reviewed_token"])
        with self.assertRaises(ValidationError):
            approve_translation(self.actor, entry, reviewed_token="tampered")
        update_question(self.actor, question, text_th="ต้นฉบับใหม่")
        edit_translation(self.actor, entry, entry.text)
        with self.assertRaisesMessage(ValidationError, "changed"):
            approve_translation(self.actor, entry, reviewed_token=seen["reviewed_token"])
        entry.refresh_from_db()
        self.assertNotEqual(entry.status, "approved")

    def test_editing_back_to_same_text_does_not_revive_old_review(self):
        _, question, bundle = self.instrument()
        entry = bundle.translations.get(content_key=f"{question.question_id}.text", locale="en")
        seen = translation_review_snapshot(self.actor, entry)
        edit_translation(self.actor, entry, "B")
        edit_translation(self.actor, entry, seen["translation_text"])
        with self.assertRaisesMessage(ValidationError, "changed"):
            approve_translation(self.actor, entry, reviewed_token=seen["reviewed_token"])

    def test_snapshot_cannot_be_reused_by_another_authorized_reviewer(self):
        _, question, bundle = self.instrument()
        entry = bundle.translations.get(content_key=f"{question.question_id}.text", locale="en")
        seen = translation_review_snapshot(self.actor, entry)
        RoleAssignment.objects.create(membership=Membership.objects.get(user=self.other),
            role=Role.objects.get(code="catalog-test"), scope=self.scope)
        with self.assertRaises(ValidationError):
            approve_translation(self.other, entry, reviewed_token=seen["reviewed_token"])
        own_seen = translation_review_snapshot(self.other, entry)
        approved = approve_translation(self.other, entry, reviewed_token=own_seen["reviewed_token"])
        self.assertEqual(approved.reviewed_by_id, self.other.pk)

    def test_database_revision_cannot_be_rewound_by_bulk_update(self):
        _, _, bundle = self.instrument()
        entry = bundle.translations.first()
        before = entry.review_revision
        ContentTranslation.objects.filter(pk=entry.pk).update(text="B", review_revision=0)
        entry.refresh_from_db()
        self.assertEqual(entry.review_revision, before + 1)

    def test_system_label_review_rejects_changed_source_or_translation(self):
        for index, change in enumerate(({"text_en": "Changed B"}, {"source_th": "ต้นฉบับใหม่"})):
            with self.subTest(change=change):
                label = LocalizedLabel.objects.create(scope=self.scope, namespace="calendar", key=f"year-{index}",
                    version="1", source_th="ปี", text_en="Year A", source_hash=source_hash("ปี"))
                seen = localized_label_review_snapshot(self.actor, label)
                LocalizedLabel.objects.filter(pk=label.pk).update(**change, review_revision=0)
                with self.assertRaisesMessage(ValidationError, "changed"):
                    review_localized_label(self.actor, label, reviewed_token=seen["reviewed_token"])
                with self.assertRaises(ValidationError):
                    publish_localized_label(self.actor, label)
                label.refresh_from_db()
                self.assertGreater(label.review_revision, seen["review_revision"])
                self.assertIsNone(label.reviewed_by_id)
                new_seen = localized_label_review_snapshot(self.actor, label)
                review_localized_label(self.actor, label, reviewed_token=new_seen["reviewed_token"])
                self.assertTrue(publish_localized_label(self.actor, label).published)

    def test_approval_audit_records_exact_reviewed_hashes_and_revision(self):
        _, question, bundle = self.instrument()
        entry = bundle.translations.get(content_key=f"{question.question_id}.text", locale="en")
        seen = translation_review_snapshot(self.actor, entry)
        approve_translation(self.actor, entry, reviewed_token=seen["reviewed_token"])
        event = AuditEvent.objects.get(action="catalog.translation_approved")
        self.assertEqual(event.metadata["revision"], seen["review_revision"])
        self.assertEqual(event.metadata["source_hash"], source_hash(seen["source_text"]))
        self.assertEqual(event.metadata["checksum"], source_hash(seen["translation_text"]))


class CatalogCloneFixTests(CatalogFixtures, TestCase):
    def test_long_bundle_codes_clone_repeatedly_without_approval_or_history_changes(self):
        for index, length in enumerate((36, 40)):
            with self.subTest(length=length):
                version, _, old_bundle = self.instrument(code=f"F0{index + 1}")
                # Bundle identity is immutable after insertion; make a fresh long-ID bundle.
                old_bundle.translations.all().delete()
                old_bundle.delete()
                bundle = TranslationBundle.objects.create(instrument_version=version, bundle_version="x" * length)
                from apps.catalog.services import source_texts
                for key, original in source_texts(version).items():
                    for locale in ("th", "en"):
                        ContentTranslation.objects.create(bundle=bundle, content_key=key, locale=locale,
                            text=original if locale == "th" else "Reviewed English", source_hash=source_hash(original))
                version, bundle = self.publish(version, bundle)
                before = list(bundle.translations.order_by("pk").values())
                first = clone_instrument_version(self.actor, version, "copy-1")
                second = clone_instrument_version(self.actor, version, "copy-2")
                third = clone_instrument_version(self.actor, first, "copy-3")
                for target in (first, second, third):
                    copied = target.translation_bundles.get()
                    self.assertLessEqual(len(copied.bundle_version), 40)
                    self.assertNotEqual(copied.bundle_version, target.based_on.translation_bundles.get().bundle_version)
                    self.assertEqual(copied.status, "draft")
                    self.assertFalse(copied.translations.exclude(status="needs_review").exists())
                    self.assertFalse(copied.translations.filter(reviewed_by__isnull=False).exists())
                    self.assertFalse(copied.translations.filter(reviewed_at__isnull=False).exists())
                bundle.refresh_from_db()
                version.refresh_from_db()
                self.assertEqual(bundle.bundle_version, "x" * length)
                self.assertEqual(version.status, "published")
                self.assertEqual(list(bundle.translations.order_by("pk").values()), before)

    def test_truncation_and_existing_source_code_collisions_are_resolved(self):
        version, _, _ = self.instrument()
        codes = ("z" * 35 + "a", "z" * 35 + "b", "z" * 35 + "-copy", "z" * 33 + "-copy-2")
        for code in codes:
            TranslationBundle.objects.create(instrument_version=version, bundle_version=code)
        cloned = clone_instrument_version(self.actor, version, "collision-copy")
        actual = list(cloned.translation_bundles.values_list("bundle_version", flat=True))
        self.assertEqual(len(actual), len(codes) + 1)
        self.assertEqual(len(set(actual)), len(actual))
        self.assertTrue(all(len(code) <= 40 for code in actual))
        self.assertFalse(set(actual).intersection(version.translation_bundles.values_list("bundle_version", flat=True)))


class CatalogReviewConcurrencyTests(CatalogFixtures, TransactionTestCase):
    def setUp(self):
        self.setUpTestData()

    def overlap(self, first, second):
        """Hold the first write uncommitted, prove the other connection waits on it."""
        held, release = Event(), Event()
        pids, results = Queue(), Queue()

        def writer(name, operation, hold=False):
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '12s'")
                        cursor.execute("SELECT pg_backend_pid()")
                        pids.put((name, cursor.fetchone()[0]))
                    result = operation()
                    if hold:
                        held.set()
                        if not release.wait(12):
                            raise AssertionError("Test did not release the first writer")
                results.put((name, result))
            except Exception as error:
                results.put((name, error))
                held.set()
            finally:
                connections.close_all()

        one = Thread(target=writer, args=("first", first, True), daemon=True)
        two = Thread(target=writer, args=("second", second), daemon=True)
        one.start()
        try:
            self.assertTrue(held.wait(12), "First connection did not write")
            first_name, first_pid = pids.get(timeout=2)
            two.start()
            second_name, second_pid = pids.get(timeout=2)
            self.assertEqual((first_name, second_name), ("first", "second"))
            self.assertNotEqual(first_pid, second_pid)
            deadline, blocked = monotonic() + 8, False
            while monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", [second_pid])
                    row = cursor.fetchone()
                if row and row[0] == "Lock":
                    blocked = True
                    break
                Event().wait(0.01)
            self.assertTrue(blocked, "Second PostgreSQL connection never waited for the first write")
        finally:
            release.set()
            one.join(15)
            if two.ident is not None:
                two.join(15)
        self.assertFalse(one.is_alive() or two.is_alive())
        return dict(results.get(timeout=2) for _ in range(2))

    def test_translation_edit_commits_before_waiting_approval_rejects_old_snapshot(self):
        _, question, bundle = self.instrument()
        entry = bundle.translations.get(content_key=f"{question.question_id}.text", locale="en")
        seen = translation_review_snapshot(self.actor, entry)
        result = self.overlap(
            lambda: edit_translation(self.actor, entry, "Concurrent B"),
            lambda: approve_translation(self.actor, entry, reviewed_token=seen["reviewed_token"]),
        )
        self.assertIsInstance(result["first"], ContentTranslation)
        self.assertIsInstance(result["second"], ValidationError)
        entry.refresh_from_db()
        self.assertEqual((entry.text, entry.status, entry.reviewed_by_id), ("Concurrent B", "needs_review", None))
        with self.assertRaises(ValidationError):
            publish_bundle(self.actor, bundle)

    def test_translation_approval_commits_before_waiting_edit_invalidates_approval(self):
        _, question, bundle = self.instrument()
        entry = bundle.translations.get(content_key=f"{question.question_id}.text", locale="en")
        seen = translation_review_snapshot(self.actor, entry)
        result = self.overlap(
            lambda: approve_translation(self.actor, entry, reviewed_token=seen["reviewed_token"]),
            lambda: edit_translation(self.actor, entry, "Concurrent B"),
        )
        self.assertTrue(all(isinstance(value, ContentTranslation) for value in result.values()), result)
        entry.refresh_from_db()
        self.assertEqual((entry.text, entry.status, entry.reviewed_by_id), ("Concurrent B", "needs_review", None))
        self.assertIsNone(entry.reviewed_at)

    def test_source_edit_commits_before_waiting_approval_rejects_old_snapshot(self):
        _, question, bundle = self.instrument()
        entry = bundle.translations.get(content_key=f"{question.question_id}.text", locale="en")
        seen = translation_review_snapshot(self.actor, entry)
        result = self.overlap(
            lambda: update_question(self.actor, question, text_th="ต้นฉบับใหม่พร้อมกัน"),
            lambda: approve_translation(self.actor, entry, reviewed_token=seen["reviewed_token"]),
        )
        self.assertIsInstance(result["second"], ValidationError)
        entry.refresh_from_db()
        self.assertEqual(entry.status, "stale")
        self.assertIsNone(entry.reviewed_by_id)

    def test_label_edit_and_review_are_serialized_in_both_orders(self):
        for index, edit_first in enumerate((True, False)):
            with self.subTest(edit_first=edit_first):
                label = LocalizedLabel.objects.create(scope=self.scope, namespace="calendar", key=f"year-{index}",
                    version="1", source_th="ปี", text_en="A", source_hash=source_hash("ปี"))
                seen = localized_label_review_snapshot(self.actor, label)
                edit = lambda: LocalizedLabel.objects.filter(pk=label.pk).update(text_en="B")
                approve = lambda: review_localized_label(self.actor, label, reviewed_token=seen["reviewed_token"])
                result = self.overlap(edit if edit_first else approve, approve if edit_first else edit)
                if edit_first:
                    self.assertEqual(result["first"], 1)
                    self.assertIsInstance(result["second"], ValidationError)
                else:
                    self.assertIsInstance(result["first"], LocalizedLabel)
                    self.assertEqual(result["second"], 1)
                label.refresh_from_db()
                self.assertEqual((label.text_en, label.status, label.reviewed_by_id), ("B", "needs_review", None))
                with self.assertRaises(ValidationError):
                    publish_localized_label(self.actor, label)
