"""Independent hand-calculated Blueprint §12 fixtures. All data is synthetic."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from apps.calculations.catalog import Catalog
from apps.calculations.engine import Attendance, SeriesDefinition, calculate, merge_disjoint_results
from apps.calculations.revisions import ResponseContext, ResponseRevision, latest_submitted
from apps.calculations.types import Answer, AnswerRow, FormulaSpec, FrozenPopulation


NA = Answer("not_applicable")
MISSING = Answer("missing")
POP = FrozenPopulation("synthetic-population-4", ("A", "B", "C", "D"))


def row(unit, spec, values, extra=None):
    assert len(values) == len(spec.question_ids), "Fixture width must match the source questions"
    answers = {q: value if isinstance(value, Answer) else Answer("answered", value)
               for q, value in zip(spec.question_ids, values)}
    answers.update(extra or {})
    return AnswerRow(unit, answers)


def attendance(unit, activity, hours, categories=(), **kwargs):
    return Attendance(unit, activity, "session-1", Decimal(str(hours)),
                      categories=frozenset(categories), status="accepted", evidence_verified=True, **kwargs)


def series(spec):
    return SeriesDefinition("synthetic-scope", "2569-Q1", "academic_quarter", "7.2-1",
                            "same-service", "", "survey", "person", spec)


class GoldenCalculationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def spec(self, code, group="ST1", dimension=None):
        return self.catalog.spec(code, group_code=group, dimension=dimension)

    def assert_result(self, result, display, n, d):
        self.assertEqual(result.status, "computed")
        self.assertEqual(result.display_value(), display)
        self.assertEqual(result.numerator, Decimal(str(n)))
        self.assertEqual(result.denominator, Decimal(str(d)))

    def test_CAL_01_sat_separates_valid_na_missing(self):
        spec = self.spec("7.2-1", "C1")
        result = calculate(spec, [row(str(i), spec, [v]) for i, v in enumerate([5, 4, 3, NA, MISSING])])
        self.assert_result(result, "66.67", 2, 3)
        self.assertEqual((result.counts["valid_n"], result.counts["na"], result.counts["missing"]), (3, 1, 1))

    def test_CAL_02_dissatisfaction_is_independent(self):
        spec = FormulaSpec("DIS_YES", ("F01-D01",))
        result = calculate(spec, [row(str(i), spec, [v]) for i, v in enumerate(["Y", "N", "N", NA, MISSING])])
        self.assert_result(result, "33.33", 1, 3)

    def test_CAL_03_engagement_requires_all_three(self):
        spec = self.spec("7.3-37")
        result = calculate(spec, [row("A", spec, [5, 4, 3]), row("B", spec, [4, 4, MISSING]), row("C", spec, [3, 3, 3])])
        self.assert_result(result, "50.00", 1, 2)

    def test_CAL_04_pair_requires_both_scores(self):
        spec = self.spec("7.3-36")
        result = calculate(spec, [row("A", spec, [5, 3]), row("B", spec, [5, NA]), row("C", spec, [3, 3])])
        self.assert_result(result, "50.00", 1, 2)

    def test_CAL_05_admin_averages_people_not_answers(self):
        spec = self.spec("7.4-13")
        result = calculate(spec, [row("A", spec, [5, 5, 5, 5, NA]), row("B", spec, [3] * 5), row("C", spec, [5, 5, NA, NA, NA])])
        self.assert_result(result, "4.00", 8, 2)

    def test_CAL_06_digital_denominator_includes_nonrespondent(self):
        spec = self.spec("7.3-43")
        result = calculate(spec, [row("A", spec, [3] * 5), row("B", spec, [5, 5, 2, 5, 5]), row("C", spec, [4] * 5)], population=POP)
        self.assert_result(result, "50.00", 2, 4)
        self.assertEqual((result.counts["complete"], result.counts["below_threshold"], result.counts["not_submitted"]), (3, 1, 1))

    def test_CAL_07_vision_requires_every_score_at_least_four(self):
        spec = self.spec("7.4-3")
        result = calculate(spec, [row("A", spec, [5, 3]), row("B", spec, [4, 4]), row("C", spec, [4, MISSING])])
        self.assert_result(result, "50.00", 1, 2)

    def test_CAL_08_behaviour_optional_examples_do_not_change_score(self):
        spec = self.spec("7.4-6", dimension="overall")
        a = row("A", spec, [4] * 4)
        b = row("B", spec, [5, 5, 5, 3], {"F06-VS-EX": Answer("answered", "Synthetic optional example")})
        self.assert_result(calculate(spec, [a, b]), "50.00", 1, 2)
        self.assertEqual(calculate(spec, [a, b]), calculate(spec, [a, row("B", spec, [5, 5, 5, 3])]))

    def test_CAL_09_external_knowledge_uses_awareness_key_and_completeness(self):
        spec = self.spec("7.4-8", "C1")
        rows = [row("A", spec, ["seen", "B", "A", "C", "B", "A", "U"]),
                row("B", spec, ["not_seen", "B", "A", "C", "B", "A", "D"]),
                row("C", spec, ["seen", "B", MISSING, "C", "B", "A", "D"])]
        self.assert_result(calculate(spec, rows), "50.00", 1, 2)

    def test_CAL_10_happiness_zero_is_a_real_score(self):
        spec = self.spec("7.3-38")
        self.assert_result(calculate(spec, [row("A", spec, [0]), row("B", spec, [10]), row("C", spec, [MISSING])]), "5.00", 10, 2)

    def test_CAL_11_multiple_training_tags_do_not_multiply_hours(self):
        records = [attendance("A", "course-a", 3, ["T45", "T46"]), attendance("B", "course-b", 2, ["T46"])]
        for code, display, n in [("7.3-44", "1.25", 5), ("7.3-45", "25.00", 1), ("7.3-46", "50.00", 2)]:
            with self.subTest(code=code):
                self.assert_result(calculate(self.spec(code), population=POP, attendances=records), display, n, 4)

    def test_CAL_12_safety_any_counts_distinct_people(self):
        records = [attendance("A", "s", 1, ["T47S"]), attendance("A", "h", 1, ["T47H"]), attendance("B", "e", 1, ["T47E"])]
        result = calculate(self.spec("7.3-47"), population=POP, attendances=records)
        self.assert_result(result, "50.00", 2, 4)
        for side in ("T47S", "T47H", "T47E"):
            self.assert_result(result.breakdown[side], "25.00", 1, 4)

    def test_CAL_13_pool_numerators_and_denominators(self):
        spec = self.spec("7.2-1", "C1")
        one = calculate(spec, [row("A", spec, [5])])
        nine = calculate(spec, [row(str(i), spec, [5 if i == 0 else 3]) for i in range(9)])
        merged = merge_disjoint_results([(series(spec), one), (series(spec), nine)])
        self.assert_result(merged, "20.00", 2, 10)

    def test_CAL_14_all_na_is_no_valid_data_not_zero(self):
        spec = self.spec("7.2-1", "C1")
        result = calculate(spec, [row("A", spec, [NA]), row("B", spec, [NA])])
        self.assertEqual(result.status, "no_valid_data")
        self.assertIsNone(result.value)
        self.assertIsNone(result.display_value())

    def test_CAL_15_latest_submitted_revision_at_cutoff(self):
        spec = self.spec("7.4-3")
        context = ResponseContext("scope-1", "round-1", "F06", "1.1", "staff-self-report")
        cutoff = datetime(2026, 9, 15, tzinfo=timezone.utc)
        revisions = [
            ResponseRevision("draft", context, row("A", spec, [5, 5]), 3, "draft", cutoff),
            ResponseRevision("submitted-1", context, row("A", spec, [4, 4]), 1, "submitted", cutoff - timedelta(hours=3), cutoff - timedelta(hours=2)),
            ResponseRevision("submitted-2", context, row("A", spec, [3, 3]), 2, "submitted", cutoff - timedelta(hours=1), cutoff),
            ResponseRevision("future", context, row("A", spec, [5, 5]), 4, "submitted", cutoff + timedelta(hours=1), cutoff + timedelta(hours=2)),
        ]
        selected = latest_submitted(revisions, context=context, cutoff=cutoff)
        self.assertEqual([r.revision_id for r in selected], ["submitted-2"])
        self.assert_result(calculate(spec, [r.row for r in selected]), "0.00", 0, 1)

    def test_CAL_16_shared_source_binding_does_not_duplicate_people(self):
        spec13 = self.spec("7.2-13", "C5.3")
        spec17 = self.spec("7.2-17", "C5.3")
        self.assertEqual(spec13.question_ids, ("F02-S01",))
        rows = [row("organization-1", spec13, [5])]
        results = [calculate(spec, rows) for spec in (spec13, spec17)]
        self.assertEqual(results[0], results[1])
        for result in results:
            self.assert_result(result, "100.00", 1, 1)
            self.assertEqual(result.counts["eligible"], 1)

    def test_CAL_17_mission_inapplicability_is_not_zero(self):
        spec = self.spec("7.3-54", dimension="F06-M01")
        result = calculate(spec, [row("A", spec, [4]), row("B", spec, [Answer("not_applicable", reason="Outside assigned duties")]), row("C", spec, [MISSING])])
        self.assert_result(result, "4.00", 4, 1)
        self.assertEqual((result.counts["valid_n"], result.counts["na"], result.counts["missing"]), (1, 1, 1))

    def test_CAL_18_visit_only_has_zero_training_hours(self):
        records = [attendance("A", "external-visit", 0, visit_hours=Decimal(8), external_visit=True)]
        self.assert_result(calculate(self.spec("7.3-44"), population=POP, attendances=records), "0.00", 0, 4)
        self.assert_result(calculate(self.spec("7.3-49"), population=POP, attendances=records), "25.00", 1, 4)


if __name__ == "__main__":
    unittest.main()
