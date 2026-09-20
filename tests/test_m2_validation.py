"""Boundary, source compatibility and invariance tests for the offline core."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from itertools import permutations, product
import json
import unittest

from apps.calculations.catalog import Catalog, CATALOG_DIR
from apps.calculations.engine import (
    ACTIVITY_KEYS, FORMULA_KEYS, Attendance, calculate, merge_disjoint_results, validate_spec,
)
from apps.calculations.revisions import ResponseContext, ResponseRevision, latest_submitted
from apps.calculations.types import Answer, AnswerRow, CalculationInputError, FormulaSpec, FrozenPopulation
from tests.test_m2_golden import MISSING, NA, POP, attendance, row, series


class CalculationValidationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog()
        self.sat = self.catalog.spec("7.2-1", group_code="C1")

    def test_all_63_indicators_and_20_templates_execute_for_every_catalog_variant(self):
        indicators, keys, variants = set(), set(), 0
        for code, indicator in self.catalog.indicators.items():
            binding = indicator["binding"]
            key = binding["formula_id"]
            dimensions = binding["series_dimensions"] if key in {"DIMENSION_SAT", "SELF_DIMENSION", "SELF_BEHAVIOUR"} else [None]
            for group in binding["group_codes"]:
                for dimension in dimensions:
                    with self.subTest(code=code, group=group, dimension=dimension):
                        spec = self.catalog.spec(code, group_code=group, dimension=dimension)
                        if key in ACTIVITY_KEYS:
                            data = [attendance("A", "mixed", 2, ["T45", "T46", "T48", "T47S"], visit_hours=Decimal(1), external_visit=True)]
                            result = calculate(spec, population=POP, attendances=data)
                        else:
                            values = [5] * len(spec.question_ids)
                            if key == "DIS_YES":
                                values = ["Y"]
                            if key == "K_EXTERNAL":
                                values = ["seen", "B", "A", "C", "B", "A", "D"]
                            result = calculate(spec, [row("A", spec, values)], population=POP)
                        self.assertEqual(result.status, "computed")
                        self.assertGreater(result.value, 0)
                        keys.add(key)
                        indicators.add(code)
                        variants += 1
        self.assertEqual(len(indicators), 63)
        self.assertEqual(keys, FORMULA_KEYS)
        self.assertEqual(variants, 198)

    def test_external_key_matches_server_only_catalog(self):
        key = json.loads((CATALOG_DIR / "answer_keys.server.json").read_text())
        spec = self.catalog.spec("7.4-8", group_code="C1")
        values = ["seen"] + [key["correct_options"][f"K{i:02d}"] for i in range(1, 7)]
        self.assertEqual(calculate(spec, [row("A", spec, values)]).display_value(), "100.00")
        # Wrong vision and two wrong values fail, including U as an answered option.
        for index in (1, 2):
            wrong = list(values)
            wrong[index] = "U"
            self.assertEqual(calculate(spec, [row("A", spec, wrong)]).display_value(), "0.00")
        values[3:5] = ["U", "U"]
        self.assertEqual(calculate(spec, [row("A", spec, values)]).display_value(), "0.00")

    def test_cannot_recall_is_complete_but_not_a_pass(self):
        spec = self.catalog.spec("7.4-8", group_code="C1")
        result = calculate(spec, [row("A", spec, ["cannot_recall", "B", "A", "C", "B", "A", "D"])])
        self.assertEqual((result.display_value(), result.denominator), ("0.00", 1))

    def test_every_non_score_status_remains_separate(self):
        values = [5, NA, MISSING, Answer("not_shown"), Answer("unable_to_assess"), Answer("skipped")]
        result = calculate(self.sat, [row(str(i), self.sat, [a]) for i, a in enumerate(values)])
        for key in ("valid_n", "na", "missing", "not_shown", "unable_to_assess", "skipped"):
            self.assertEqual(result.counts[key], 1)
        self.assertEqual(result.display_value(), "100.00")

    def test_missing_population_differs_from_empty_population(self):
        specs = [self.catalog.spec(code, group_code="ST1") for code in ("7.3-43", "7.3-44", "7.3-45", "7.3-47", "7.3-49")]
        for spec in specs:
            with self.subTest(formula=spec.formula_key):
                undefined = calculate(spec)
                empty = calculate(spec, population=FrozenPopulation("empty", ()))
                self.assertEqual(undefined.status, "insufficient_population_definition")
                self.assertIsNone(undefined.denominator)
                self.assertEqual(empty.status, "no_valid_data")
                self.assertEqual(empty.denominator, 0)
                self.assertIsNone(empty.value)

    def test_digital_partial_unable_and_nonrespondents_stay_in_denominator(self):
        spec = self.catalog.spec("7.3-43", group_code="ST1")
        result = calculate(spec, [row("A", spec, [3, 3, 3, 3, MISSING]),
                                  row("B", spec, [Answer("unable_to_assess")] * 5)], population=POP)
        self.assertEqual((result.display_value(), result.denominator), ("0.00", 4))
        self.assertEqual((result.counts["submitted_partial"], result.counts["not_submitted"]), (2, 2))

    def test_duplicates_and_outside_population_fail(self):
        a = row("A", self.sat, [5])
        for rows in ([a, a], [row("outsider", self.sat, [5])]):
            with self.assertRaises(CalculationInputError):
                calculate(self.sat, rows, population=POP)
        with self.assertRaises(CalculationInputError):
            FrozenPopulation("duplicate", ["A", "A"])

    def test_invalid_scores_never_become_zero_or_missing(self):
        for value in (-1, 0, 6, Decimal("4.5"), Decimal("NaN"), Decimal("Infinity"), True, 4.0, "4", "4,00"):
            with self.subTest(value=str(value)), self.assertRaises(CalculationInputError):
                calculate(self.sat, [row("A", self.sat, [value])])
        with self.assertRaises(CalculationInputError):
            Answer("not_applicable", 0)
        with self.assertRaises(CalculationInputError):
            Answer("arbitrary_status")

    def test_na_mission_requires_reason_without_assessor(self):
        spec = self.catalog.spec("7.3-54", group_code="ST1", dimension="F06-M01")
        with self.assertRaises(CalculationInputError):
            calculate(spec, [row("A", spec, [NA])])
        result = calculate(spec, [row("A", spec, [Answer("not_applicable", reason="No assigned duty")])])
        self.assertEqual(result.status, "no_valid_data")

    def test_invalid_templates_groups_dimensions_and_versions_are_rejected(self):
        for spec in (replace(self.sat, formula_key="eval"), replace(self.sat, formula_version="9"),
                     replace(self.sat, instrument_version="1.0"), FormulaSpec("SELF_VISION", ("F01-K01", "F01-K02")),
                     FormulaSpec("DIMENSION_SAT", ("F03-G08",)), FormulaSpec("SELF_COMPETENCY", ("F06-A01",)),
                     FormulaSpec("TRAINING_PEOPLE", category="OTHER")):
            with self.subTest(spec=spec), self.assertRaises(CalculationInputError):
                validate_spec(spec)
        for kwargs in ({"indicator_code": "7.2-13", "group_code": "ST1"},
                       {"indicator_code": "7.3-39", "group_code": "ST1"},
                       {"indicator_code": "7.3-54", "group_code": "ST1", "dimension": "overall"},
                       {"indicator_code": "7.4-6", "group_code": "ST1"},
                       {"indicator_code": "7.2-1", "group_code": "C1", "dimension": "other"}):
            with self.assertRaises(CalculationInputError):
                self.catalog.spec(**kwargs)

    def test_wrong_catalog_scale_is_rejected(self):
        self.catalog.questions["F01-S01"]["scale_id"] = "HAPPINESS_10"
        with self.assertRaises(CalculationInputError):
            self.catalog.spec("7.2-1", group_code="C1")

    def test_competency_st1_and_st2_have_different_completion_rules(self):
        for code, size in (("7.3-50", 5), ("7.3-51", 9)):
            spec = self.catalog.spec(code, group_code="ST1" if size == 5 else "ST2")
            result = calculate(spec, [row("A", spec, [4] * size), row("B", spec, [5] * (size - 1) + [NA])])
            self.assertEqual((result.display_value(), result.denominator), ("4.00", 1))

    def test_behaviour_dimension_does_not_require_other_dimensions(self):
        spec = self.catalog.spec("7.4-6", group_code="ST1", dimension="S")
        result = calculate(spec, [row("A", spec, [4]), row("B", spec, [3]), row("C", spec, [NA])])
        self.assertEqual((result.display_value(), result.denominator), ("50.00", 2))

    def test_inputs_and_results_are_immutable_copies(self):
        answers = {"F01-S01": Answer("answered", 5)}
        source = AnswerRow("A", answers)
        old = calculate(self.sat, [source])
        answers["F01-S01"] = Answer("answered", 1)
        self.assertEqual(calculate(self.sat, [source]), old)
        with self.assertRaises(TypeError):
            source.answers["F01-S01"] = Answer("answered", 1)
        with self.assertRaises(TypeError):
            old.counts["eligible"] = 100
        with self.assertRaises(FrozenInstanceError):
            old.denominator = Decimal(100)

    def test_result_is_independent_of_decimal_context_and_row_order(self):
        rows = [row("A", self.sat, [5]), row("B", self.sat, [4]), row("C", self.sat, [3])]
        expected = calculate(self.sat, rows)
        for order in permutations(rows):
            with localcontext() as context:
                context.prec = 3
                result = calculate(self.sat, order)
                self.assertEqual(result, expected)
                self.assertEqual(result.display_value(), "66.67")
                self.assertNotEqual(result.value, Decimal("66.67"))

    def test_percent_bounds_and_valid_counts_for_small_input_combinations(self):
        for values in product([1, 3, 4, 5, NA, MISSING], repeat=3):
            result = calculate(self.sat, [row(str(i), self.sat, [v]) for i, v in enumerate(values)])
            self.assertLessEqual(result.counts["valid_n"], result.counts["eligible"])
            if result.value is not None:
                self.assertGreaterEqual(result.value, 0)
                self.assertLessEqual(result.value, 100)

    def test_locale_labels_never_change_numeric_results(self):
        before = calculate(self.sat, [row("A", self.sat, [5])])
        for question in self.catalog.questions.values():
            question["text"] = {"th": "ข้อความไทย", "en": "Different translated label"}
            for option in question["options"]:
                option["label"] = {"th": "ไทย", "en": "English"}
        after_spec = self.catalog.spec("7.2-1", group_code="C1")
        self.assertEqual(calculate(after_spec, [row("A", after_spec, [5])]), before)

    def test_f05_duplicate_rows_do_not_multiply_hours_or_people(self):
        a = attendance("A", "course", 3, ["T45", "T46"])
        for code in ("7.3-44", "7.3-45"):
            spec = self.catalog.spec(code, group_code="ST1")
            once = calculate(spec, population=POP, attendances=[a])
            duplicate = calculate(spec, population=POP, attendances=[a, a])
            self.assertEqual(duplicate.value, once.value)
            self.assertEqual(duplicate.counts["duplicate_rows_ignored"], 1)
            with self.assertRaises(CalculationInputError):
                calculate(spec, population=POP, attendances=[a, replace(a, training_hours=Decimal(4))])

    def test_f05_counts_repeated_training_person_once_but_sums_all_hours(self):
        records = [attendance("A", "course-1", 3, ["T45"]), attendance("A", "course-2", 2, ["T45"])]
        hours = calculate(self.catalog.spec("7.3-44", group_code="ST1"), population=POP, attendances=records)
        people = calculate(self.catalog.spec("7.3-45", group_code="ST1"), population=POP, attendances=records)
        self.assertEqual((hours.display_value(), people.display_value()), ("1.25", "25.00"))

    def test_f05_acceptance_evidence_hours_and_population_are_validated(self):
        spec = self.catalog.spec("7.3-44", group_code="ST1")
        a = attendance("A", "course", 2, ["T45"])
        for record in (replace(a, evidence_verified=False), replace(a, unit_id="outsider")):
            with self.assertRaises(CalculationInputError):
                calculate(spec, population=POP, attendances=[record])
        for hours in (Decimal(-1), Decimal("NaN"), True, 1.5):
            with self.assertRaises(CalculationInputError):
                replace(a, training_hours=hours)
        pending = calculate(spec, population=POP, attendances=[replace(a, status="submitted", evidence_verified=False)])
        self.assertEqual(pending.display_value(), "0.00")
        self.assertEqual(pending.counts["excluded_attendances"], 1)

    def test_zero_training_and_internal_visits_are_not_qualifying_people(self):
        records = [attendance("A", "zero", 0, ["T45"], visit_hours=Decimal(8), external_visit=False)]
        for code in ("7.3-45", "7.3-49"):
            result = calculate(self.catalog.spec(code, group_code="ST1"), population=POP, attendances=records)
            self.assertEqual(result.display_value(), "0.00")

    def test_incompatible_or_overlapping_series_cannot_be_pooled(self):
        a = calculate(self.sat, [row("A", self.sat, [5])])
        b = calculate(self.sat, [row("B", self.sat, [3])])
        definition = series(self.sat)
        for field in ("scope_id", "period_id", "period_type", "indicator_code", "context_id", "dimension_id", "method", "response_unit"):
            with self.subTest(field=field), self.assertRaises(CalculationInputError):
                merge_disjoint_results([(definition, a), (replace(definition, **{field: "different"}), b)])
        with self.assertRaises(CalculationInputError):
            merge_disjoint_results([(definition, a), (definition, a)])

    def test_mean_merging_keeps_person_level_sums(self):
        spec = self.catalog.spec("7.4-13", group_code="ST1")
        a = calculate(spec, [row("A", spec, [5, 5, 5, 5, NA])])
        b = calculate(spec, [row("B", spec, [3] * 5), row("C", spec, [1] * 5)])
        merged = merge_disjoint_results([(series(spec), a), (series(spec), b)])
        self.assertEqual((merged.display_value(), merged.denominator), ("3.00", 3))

    def test_revision_selection_is_idempotent_and_rejects_mixed_contexts(self):
        context = ResponseContext("scope", "round", "F01", "1.1", "context")
        time = datetime(2026, 9, 15, tzinfo=timezone.utc)
        a = ResponseRevision("r1", context, row("A", self.sat, [5]), 1, "submitted", time, time)
        b = replace(a, revision_id="r2", revision_number=2, row=row("A", self.sat, [3]))
        for revisions in ([a, b], [b, a], [b, a, b]):
            self.assertEqual(latest_submitted(revisions, context=context, cutoff=time), (b,))
        for field in ("scope_id", "round_id", "instrument_id", "instrument_version", "measurement_context_id"):
            with self.subTest(field=field), self.assertRaises(CalculationInputError):
                latest_submitted([replace(a, context=replace(context, **{field: "other"}))], context=context, cutoff=time)
        with self.assertRaises(CalculationInputError):
            latest_submitted([a, replace(a, row=row("A", self.sat, [1]))], context=context, cutoff=time)
        with self.assertRaises(CalculationInputError):
            latest_submitted([a, replace(a, revision_id="other-id")], context=context, cutoff=time)

    def test_revision_timestamps_are_aware_and_cutoff_is_inclusive(self):
        context = ResponseContext("scope", "round", "F01", "1.1", "context")
        time = datetime(2026, 9, 15, tzinfo=timezone.utc)
        a = ResponseRevision("r1", context, row("A", self.sat, [5]), 1, "submitted", time, time)
        self.assertEqual(latest_submitted([a], context=context, cutoff=time - timedelta(microseconds=1)), ())
        self.assertEqual(latest_submitted([a], context=context, cutoff=time), (a,))
        with self.assertRaises(CalculationInputError):
            latest_submitted([a], context=context, cutoff=time.replace(tzinfo=None))
        with self.assertRaises(CalculationInputError):
            replace(a, submitted_at=time - timedelta(seconds=1))
        with self.assertRaises(CalculationInputError):
            replace(a, status="draft")


if __name__ == "__main__":
    unittest.main()
