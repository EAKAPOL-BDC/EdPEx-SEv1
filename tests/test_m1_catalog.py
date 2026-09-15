"""M1 behavior tests against disposable PostgreSQL, including SQL bypasses."""
import json
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, connection, transaction
from django.test import TestCase

from apps.accounts.models import AccessScope, Membership, Organization, Role, RoleAssignment
from apps.catalog.models import (
    BindingQuestion, ContentTranslation, FormulaVersion, Indicator, IndicatorBinding,
    Instrument, InstrumentContent, InstrumentVersion, Question, QuestionOption,
    TranslationBundle, LocalizedLabel, source_hash,
)
from apps.catalog.seeding import seed_catalog
from apps.catalog.services import (
    approve_translation, clone_instrument_version, edit_translation,
    publish_bundle, publish_instrument_version, respondent_text, source_texts, update_question,
    review_localized_label, publish_localized_label, localized_label_text,
    translation_review_snapshot, localized_label_review_snapshot,
)


class CatalogFixtures:
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_user(username="catalog-editor")
        cls.other = get_user_model().objects.create_user(username="catalog-other")
        org = Organization.objects.create(name="Catalog test")
        cls.scope = AccessScope.objects.create(organization=org, code="A", name="A")
        cls.other_scope = AccessScope.objects.create(organization=org, code="B", name="B")
        role = Role.objects.create(code="catalog-test", permissions=["catalog.read", "catalog.edit", "catalog.publish", "translation.review"])
        for user, scope in ((cls.actor, cls.scope), (cls.other, cls.other_scope)):
            membership = Membership.objects.create(user=user, organization=org)
            RoleAssignment.objects.create(membership=membership, role=role, scope=scope)

    def instrument(self, code="F01", scope=None):
        instrument = Instrument.objects.create(scope=scope or self.scope, code=code)
        version = InstrumentVersion.objects.create(instrument=instrument, version="test-1", title_th="แบบสอบถาม",
            assessment_method="self_report" if code == "F06" else "survey", instructions_curated=True)
        question = Question.objects.create(version=version, question_id=f"{code}-S01", text_th="ประสบการณ์", answer_type="single_choice")
        QuestionOption.objects.create(question=question, code="1", label_th="น้อย", score=1)
        InstrumentContent.objects.create(version=version, content_key=f"{code}.instruction", kind="instruction", text_th="เลือกคำตอบ", audience="respondent")
        bundle = TranslationBundle.objects.create(instrument_version=version, bundle_version="test-1")
        for key, text in source_texts(version).items():
            for locale in ("th", "en"):
                ContentTranslation.objects.create(bundle=bundle, content_key=key, locale=locale,
                    text=text if locale == "th" else "Reviewed test translation", source_hash=source_hash(text))
        return version, question, bundle

    def publish(self, version, bundle):
        for entry in bundle.translations.all():
            approve_translation(self.actor, entry, reviewed_token=translation_review_snapshot(self.actor, entry)["reviewed_token"])
        bundle = publish_bundle(self.actor, bundle)
        return publish_instrument_version(self.actor, version), bundle


class CatalogBehaviorTests(CatalogFixtures, TestCase):
    def test_cross_user_and_scope_are_denied_for_mutation_and_reads(self):
        version, question, bundle = self.instrument()
        with self.assertRaises(PermissionDenied):
            update_question(self.other, question, text_th="Unauthorized")
        with self.assertRaises(PermissionDenied):
            approve_translation(self.other, bundle.translations.first(), reviewed_token="unauthorized")
        version, bundle = self.publish(version, bundle)
        with self.assertRaises(PermissionDenied):
            respondent_text(self.other, bundle, f"{question.question_id}.text", "en")
        self.assertEqual(respondent_text(self.actor, bundle, f"{question.question_id}.text", "en"), "Reviewed test translation")

    def test_unreviewed_or_missing_translation_never_publishes(self):
        version, question, bundle = self.instrument()
        with self.assertRaises(ValidationError):
            publish_bundle(self.actor, bundle)
        with self.assertRaises(ValidationError):
            respondent_text(self.actor, bundle, f"{question.question_id}.text", "en")
        for entry in bundle.translations.exclude(locale="en"):
            approve_translation(self.actor, entry, reviewed_token=translation_review_snapshot(self.actor, entry)["reviewed_token"])
        with self.assertRaises(ValidationError):
            publish_bundle(self.actor, bundle)
        with self.assertRaises(DatabaseError), transaction.atomic():
            TranslationBundle.objects.filter(pk=bundle.pk).update(status="published")

    def test_source_change_invalidates_approval_including_raw_sql(self):
        version, question, bundle = self.instrument()
        entry = bundle.translations.get(content_key=f"{question.question_id}.text", locale="en")
        entry = approve_translation(self.actor, entry, reviewed_token=translation_review_snapshot(self.actor, entry)["reviewed_token"])
        Question.objects.filter(pk=question.pk).update(text_th="เนื้อหาใหม่")
        entry.refresh_from_db()
        self.assertEqual(entry.status, "stale")
        self.assertIsNone(entry.reviewed_by_id)
        with self.assertRaises(ValidationError):
            approve_translation(self.actor, entry, reviewed_token=translation_review_snapshot(self.actor, entry)["reviewed_token"])
        entry = edit_translation(self.actor, entry, "Revised translation")
        self.assertEqual(approve_translation(self.actor, entry, reviewed_token=translation_review_snapshot(self.actor, entry)["reviewed_token"]).status, "approved")

    def test_version_source_metadata_change_invalidates_bilingual_review(self):
        version, question, bundle = self.instrument()
        for entry in bundle.translations.all():
            approve_translation(self.actor, entry, reviewed_token=translation_review_snapshot(self.actor, entry)["reviewed_token"])
        InstrumentVersion.objects.filter(pk=version.pk).update(group_codes=["C2.2"], source_metadata={"changed_context": True})
        self.assertFalse(bundle.translations.exclude(status="stale").exists())
        self.assertFalse(bundle.translations.filter(reviewed_by__isnull=False).exists())
        self.assertFalse(bundle.translations.filter(reviewed_at__isnull=False).exists())
        with self.assertRaises(ValidationError):
            publish_bundle(self.actor, bundle)

    def test_published_history_immutable_and_clone_retains_stable_ids(self):
        version, question, bundle = self.instrument()
        version, bundle = self.publish(version, bundle)
        with self.assertRaises(ValidationError):
            update_question(self.actor, question, text_th="Cannot replace")
        with self.assertRaises(DatabaseError), transaction.atomic():
            Question.objects.filter(pk=question.pk).update(text_th="Cannot replace using SQL")
        with self.assertRaises(DatabaseError), transaction.atomic():
            ContentTranslation.objects.filter(bundle=bundle).update(text="Cannot replace")
        with self.assertRaises(DatabaseError), transaction.atomic():
            InstrumentVersion.objects.filter(pk=version.pk).delete()
        new = clone_instrument_version(self.actor, version, "test-2")
        self.assertNotEqual(new.pk, version.pk)
        self.assertEqual(new.based_on_id, version.pk)
        self.assertEqual(new.questions.get().question_id, question.question_id)
        self.assertFalse(new.translation_bundles.get().translations.filter(status="approved").exists())
        update_question(self.actor, new.questions.get(), text_th="รุ่นใหม่")
        question.refresh_from_db()
        self.assertEqual(question.text_th, "ประสบการณ์")
        self.assertEqual(respondent_text(self.actor, bundle, f"{question.question_id}.text", "th"), "ประสบการณ์")

    def test_f06_has_no_assessor_scoring_or_required_evidence(self):
        version, question, bundle = self.instrument(code="F06")
        for change in ({"assessment_method": "survey"}, {"evidence_required": True}, {"assessor_scoring": True}, {"workflow": ["draft", "verified"]}):
            with self.assertRaises(DatabaseError), transaction.atomic():
                InstrumentVersion.objects.filter(pk=version.pk).update(**change)
        for answer_type in ("evidence_reference", "review_metadata", "assessor_score"):
            with self.assertRaises(DatabaseError), transaction.atomic():
                Question.objects.filter(pk=question.pk).update(answer_type=answer_type)
        version.refresh_from_db()
        self.assertEqual(version.assessment_method, "self_report")
        self.assertFalse(version.evidence_required)

    def test_bindings_cannot_cross_scopes_or_instrument_versions(self):
        version, question, _ = self.instrument()
        other_version, other_question, _ = self.instrument(code="F02", scope=self.other_scope)
        formula = FormulaVersion.objects.create(scope=self.scope, key="SAT_TOP2", version="1", definition_th="สูตร", source_hash="a" * 64)
        indicator = Indicator.objects.create(scope=self.other_scope, code="7.2-1", original_name_status="pending", display_name_th="ชื่อ", display_name_status="derived", unit="percent", direction="increase")
        with self.assertRaises(ValidationError):
            IndicatorBinding.objects.create(version=version, formula=formula, indicator=indicator)
        with self.assertRaises(DatabaseError), transaction.atomic():
            IndicatorBinding.objects.bulk_create([IndicatorBinding(version=version, formula=formula, indicator=indicator)])
        local_indicator = Indicator.objects.create(scope=self.scope, code="7.2-1", original_name_status="pending", display_name_th="ชื่อ", display_name_status="derived", unit="percent", direction="increase")
        binding = IndicatorBinding.objects.create(version=version, formula=formula, indicator=local_indicator)
        with self.assertRaises(DatabaseError), transaction.atomic():
            BindingQuestion.objects.bulk_create([BindingQuestion(binding=binding, question=other_question)])

    def test_source_sections_remain_private_and_na_is_not_zero(self):
        version, question, bundle = self.instrument()
        with self.assertRaises(ValidationError):
            InstrumentContent.objects.create(version=version, content_key="raw", kind="source_section", text_th="คู่มือผู้ดูแล", audience="respondent")
        with self.assertRaises(ValidationError):
            QuestionOption.objects.create(question=question, code="NA", label_th="ไม่เกี่ยวข้อง", answer_status="not_applicable", score=0)
        self.assertNotIn("raw", source_texts(version))

    def test_stable_identity_and_formula_allowlist_guard_bulk_operations(self):
        version, question, bundle = self.instrument()
        with self.assertRaises(DatabaseError), transaction.atomic():
            Question.objects.filter(pk=question.pk).update(question_id="F01-CHANGED")
        with self.assertRaises(DatabaseError), transaction.atomic():
            Instrument.objects.filter(pk=version.instrument_id).update(scope=self.other_scope)
        with self.assertRaises(DatabaseError), transaction.atomic():
            FormulaVersion.objects.bulk_create([FormulaVersion(scope=self.scope, key="EVAL_PYTHON", version="1", definition_th="unsafe", source_hash="a" * 64)])

    def test_version_lineage_cannot_be_reassigned_or_cross_instruments(self):
        version, _, _ = self.instrument()
        other_version, _, _ = self.instrument(code="F02", scope=self.other_scope)
        for parent in (version, other_version):
            with self.assertRaises(DatabaseError), transaction.atomic():
                InstrumentVersion.objects.filter(pk=version.pk).update(based_on=parent)
        with self.assertRaises(DatabaseError), transaction.atomic():
            InstrumentVersion.objects.bulk_create([InstrumentVersion(instrument=version.instrument, version="bad-lineage",
                based_on=other_version, title_th="bad", assessment_method="survey")])
        cloned = clone_instrument_version(self.actor, version, "good-lineage")
        with self.assertRaises(DatabaseError), transaction.atomic():
            InstrumentVersion.objects.filter(pk=cloned.pk).update(based_on=None)

    def test_system_labels_require_scoped_review_and_keep_published_history(self):
        label = LocalizedLabel.objects.create(scope=self.scope, namespace="calendar", key="fiscal.year", version="1",
            source_th="ปีงบประมาณ", text_en="Fiscal year", source_hash=source_hash("ปีงบประมาณ"))
        with self.assertRaises(ValidationError):
            localized_label_text(self.actor, label, "en")
        with self.assertRaises(PermissionDenied):
            review_localized_label(self.other, label, reviewed_token="unauthorized")
        with self.assertRaises(ValidationError):
            publish_localized_label(self.actor, label)
        label = publish_localized_label(self.actor, review_localized_label(self.actor, label, reviewed_token=localized_label_review_snapshot(self.actor, label)["reviewed_token"]))
        self.assertEqual(localized_label_text(self.actor, label, "en"), "Fiscal year")
        with self.assertRaises(DatabaseError), transaction.atomic():
            LocalizedLabel.objects.filter(pk=label.pk).update(text_en="Changed after publication")
        newer = LocalizedLabel.objects.create(scope=self.scope, namespace=label.namespace, key=label.key, version="2",
            source_th=label.source_th, text_en="Fiscal reporting year", source_hash=label.source_hash)
        review_localized_label(self.actor, newer, reviewed_token=localized_label_review_snapshot(self.actor, newer)["reviewed_token"])
        LocalizedLabel.objects.filter(pk=newer.pk).update(source_th="ปีงบประมาณใหม่")
        newer.refresh_from_db()
        self.assertEqual(newer.status, "stale")
        self.assertIsNone(newer.reviewed_by_id)
        self.assertEqual(localized_label_text(self.actor, label, "en"), "Fiscal year")


class CatalogSeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_user(username="seed-editor")
        org = Organization.objects.create(name="Seed test")
        cls.scope = AccessScope.objects.create(organization=org, code="SEED", name="Seed")
        membership = Membership.objects.create(user=cls.actor, organization=org)
        role = Role.objects.create(code="seed-test", permissions=["catalog.edit", "catalog.publish"])
        RoleAssignment.objects.create(membership=membership, role=role, scope=cls.scope)
        cls.result = seed_catalog(cls.scope, cls.actor)

    def test_seed_is_idempotent_and_preserves_source_semantics(self):
        ids_before = set(Question.objects.values_list("id", flat=True))
        self.assertEqual(seed_catalog(self.scope, self.actor)["created_instruments"], 0)
        self.assertEqual(set(Question.objects.values_list("id", flat=True)), ids_before)
        originals = json.loads((Path(settings.BASE_DIR) / "catalog" / "questions.json").read_text(encoding="utf-8"))
        scales = {row["scale_id"]: row for row in json.loads((Path(settings.BASE_DIR) / "catalog" / "scales.json").read_text(encoding="utf-8"))}
        for original in originals:
            question = Question.objects.get(question_id=original["question_id"])
            self.assertEqual(question.text_th, original["text"]["th"])
            self.assertEqual(question.answer_type, original["answer_type"])
            self.assertEqual(question.group_codes, original["group_codes"])
            self.assertEqual(question.visibility_rule, original["visibility_condition"])
            self.assertEqual(question.required_rule, {"required": original["required"]})
            self.assertEqual(question.scale, scales.get(original.get("scale_id"), {}))
            self.assertEqual(question.answer_statuses, original["answer_statuses"])
            self.assertEqual(question.source_metadata, original)
            self.assertEqual(set(question.options.values_list("code", flat=True)), {o["code"] for o in original["options"]})
            for position, expected_option in enumerate(original["options"]):
                option = question.options.get(code=expected_option["code"])
                self.assertEqual(option.label_th, expected_option["label"]["th"])
                expected_score = expected_option.get("score")
                self.assertEqual(option.score, None if expected_score is None else Decimal(str(expected_score)))
                self.assertEqual(option.position, position)
                expected_status = "answered"
                if expected_option["code"] == "NA":
                    expected_status = "unable_to_assess" if original.get("scale_id") in ("AGR", "ADM") else "not_applicable"
                self.assertEqual(option.answer_status, expected_status)
        self.assertEqual(Indicator.objects.count(), 63)
        self.assertEqual(FormulaVersion.objects.count(), 20)
        self.assertEqual(Question.objects.get(question_id="F04-DE01").options.get(code="NA").answer_status, "unable_to_assess")
        self.assertEqual(Question.objects.get(question_id="F01-S01").options.get(code="NA").answer_status, "not_applicable")
        self.assertTrue(InstrumentVersion.objects.get(instrument__code="F01").contents.filter(content_key="INS-039.content", audience="configuration_only").exists())
        for original in json.loads((Path(settings.BASE_DIR) / "catalog" / "formulas.json").read_text(encoding="utf-8")):
            formula = FormulaVersion.objects.get(key=original["formula_id"])
            self.assertEqual(formula.version, original["formula_version"])
            self.assertEqual(formula.definition_th, original["definition_th"])
            self.assertEqual(formula.parameters, original)
            self.assertEqual(formula.source_metadata, original["source"])
            self.assertEqual(formula.requirements, original["blueprint_requirements"])
        for original in json.loads((Path(settings.BASE_DIR) / "catalog" / "instruments.json").read_text(encoding="utf-8")):
            version = InstrumentVersion.objects.get(instrument__code=original["instrument_id"])
            for field in ("version", "title_th", "assessment_method", "group_codes", "workflow", "response_unit", "identity_domain"):
                self.assertEqual(getattr(version, field), original[field])
            self.assertEqual(version.requirements, original["blueprint_requirements"])
        for original in json.loads((Path(settings.BASE_DIR) / "catalog" / "indicators.json").read_text(encoding="utf-8")):
            binding = IndicatorBinding.objects.get(indicator__code=original["code"])
            self.assertEqual(set(binding.questions.values_list("question_id", flat=True)), set(original["binding"]["source_question_ids"]))
            self.assertEqual(binding.formula.key, original["binding"]["formula_id"])
            self.assertEqual(binding.group_rules["group_codes"], original["binding"]["group_codes"])
            self.assertEqual(binding.indicator_snapshot, original)

    def test_seed_keeps_english_draft_f06_self_report_and_instructions_unpublished(self):
        self.assertFalse(ContentTranslation.objects.filter(status="approved").exists())
        self.assertFalse(InstrumentVersion.objects.exclude(status="draft").exists())
        self.assertFalse(ContentTranslation.objects.filter(locale="en").exclude(status="draft").exists())
        self.assertEqual(LocalizedLabel.objects.filter(namespace="group").count(), 17)
        self.assertEqual(LocalizedLabel.objects.filter(namespace="indicator").count(), 63)
        self.assertFalse(LocalizedLabel.objects.filter(published=True).exists())
        self.assertFalse(LocalizedLabel.objects.exclude(status="draft").exists())
        f06 = InstrumentVersion.objects.get(instrument__code="F06")
        self.assertEqual(f06.assessment_method, "self_report")
        self.assertFalse(f06.assessor_scoring or f06.evidence_required)
        self.assertFalse(f06.questions.filter(answer_type__in=["evidence_reference", "review_metadata", "assessor_score"]).exists())
        self.assertFalse(f06.contents.get(content_key="self.optional_example").source_metadata["required"])
        with self.assertRaises(ValidationError):
            publish_bundle(self.actor, f06.translation_bundles.get())
