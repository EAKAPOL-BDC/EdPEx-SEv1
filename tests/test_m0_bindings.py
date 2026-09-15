"""Source-grounded M0 binding acceptance tests; no application/database imports.

The expected mappings below were transcribed from Instruments 1.1's coverage
register and form-specific rules, together with Blueprint 1.2 sections 10–11.
They intentionally do not use the catalog builder to construct the oracle.
These tests check the M0 specification, not an M2 calculation implementation.
"""

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
LEARNERS = ("C1", "C2.1")
OTHER_LEARNERS = ("C2.2", "C3.1")
ALL_LEARNERS = LEARNERS + OTHER_LEARNERS
CUSTOMERS = ("C4.1", "C5.1", "C5.2", "C5.3")
STAKEHOLDERS = ("S1", "S3-1", "S3-2", "CO-1", "CO-2", "CO-3", "CO-4")
STAFF = ("ST1", "ST2")


def numbered(prefix, first, last):
    return tuple(f"{prefix}{n:02}" for n in range(first, last + 1))


F05_INPUTS = (
    "F05-A01", "F05-A04", "F05-A05", "F05-A07", "F05-A09",
    "F05-P01", "F05-P02", "F05-P03", "F05-P04", "F05-P05",
    "F05-V01", "F05-V02",
)

# code: (source questions/fields, formula, permitted respondent groups)
EXPECTED = {
    "7.2-1": (("F01-S01",), "SAT_TOP2", LEARNERS),
    "7.2-2": (("F01-S02",), "SAT_TOP2", LEARNERS),
    "7.2-3": (("F01-S03",), "SAT_TOP2", LEARNERS),
    "7.2-4": (("F01-S04",), "SAT_TOP2", LEARNERS),
    "7.2-5": (("F01-S05",), "SAT_TOP2", LEARNERS),
    "7.2-6": (("F01-S06",), "SAT_TOP2", LEARNERS),
    "7.2-7": (("F01-S07",), "SAT_TOP2", LEARNERS),
    "7.2-8": (("F01-D01",), "DIS_YES", LEARNERS),
    "7.2-9": (("F01-D02",), "DIS_YES", LEARNERS),
    "7.2-10": (("F01-D03",), "DIS_YES", LEARNERS),
    "7.2-11": (("F01-S09",), "SAT_TOP2", OTHER_LEARNERS),
    "7.2-12": (("F01-D05",), "DIS_YES", OTHER_LEARNERS),
    "7.2-13": (("F02-S01",), "SAT_TOP2", ("C5.3",)),
    "7.2-14": (("F01-S08",), "SAT_TOP2", LEARNERS),
    "7.2-15": (("F01-D04",), "DIS_YES", LEARNERS),
    "7.2-17": (("F02-S01",), "SAT_TOP2", CUSTOMERS),
    "7.2-18": (("F02-D01",), "DIS_YES", CUSTOMERS),
    "7.2-19": (("F02-S01",), "SAT_TOP2", STAKEHOLDERS),
    "7.2-20": (("F02-D01",), "DIS_YES", STAKEHOLDERS),
    "7.2-24": (numbered("F01-E", 1, 3), "ENG_3", LEARNERS),
    "7.2-25": (("F01-R01",), "MEAN_5", LEARNERS),
    "7.2-34": (("F02-R01",), "MEAN_5", STAKEHOLDERS),
    "7.2-35": (("F02-R01",), "MEAN_5", CUSTOMERS),
    "7.2-36": (("F01-R01",), "MEAN_5", OTHER_LEARNERS),
    "7.3-25": (("F03-S01",), "SAT_TOP2", STAFF),
    "7.3-26": (("F03-S02",), "SAT_TOP2", STAFF),
    "7.3-27": (("F03-S03",), "SAT_TOP2", STAFF),
    "7.3-28": (("F03-S04",), "SAT_TOP2", STAFF),
    "7.3-29": (("F03-D01",), "DIS_YES", STAFF),
    "7.3-36": (numbered("F03-S", 5, 6), "PAIR_MEAN_TOP", STAFF),
    "7.3-37": (numbered("F03-E", 1, 3), "ENG_3", STAFF),
    "7.3-38": (("F03-H01",), "HAPPINESS_10", STAFF),
    "7.3-39": (numbered("F03-G", 1, 7), "DIMENSION_SAT", STAFF),
    "7.3-43": (numbered("F06-D", 1, 5), "SELF_DIGITAL_POP", STAFF),
    "7.3-44": (F05_INPUTS, "TRAINING_HOURS", STAFF),
    "7.3-45": (F05_INPUTS, "TRAINING_PEOPLE", STAFF),
    "7.3-46": (F05_INPUTS, "TRAINING_PEOPLE", STAFF),
    "7.3-47": (F05_INPUTS, "SAFETY_ANY", STAFF),
    "7.3-48": (F05_INPUTS, "TRAINING_PEOPLE", STAFF),
    "7.3-49": (F05_INPUTS, "STUDY_VISIT", STAFF),
    "7.3-50": (numbered("F06-A", 1, 5), "SELF_COMPETENCY", ("ST1",)),
    "7.3-51": (numbered("F06-A", 1, 9), "SELF_COMPETENCY", ("ST2",)),
    "7.3-52": (("F03-S07",), "SAT_TOP2", STAFF),
    "7.3-53": (("F03-D02",), "DIS_YES", STAFF),
    "7.3-54": (numbered("F06-M", 1, 5), "SELF_DIMENSION", STAFF),
    "7.3-55": (numbered("F06-T", 1, 5), "SELF_DIMENSION", STAFF),
    "7.4-1": (("F03-S08",), "SAT_TOP2", STAFF),
    "7.4-2": (("F03-S09",), "MEAN_5", STAFF),
    "7.4-3": (numbered("F06-K", 1, 2), "SELF_VISION", STAFF),
    "7.4-4": (numbered("F06-K", 3, 6), "SELF_VALUES", STAFF),
    "7.4-6": (("F06-VS", "F06-VE", "F06-VU", "F06-VP"), "SELF_BEHAVIOUR", STAFF),
    "7.4-7": (("F01-C01",), "SAT_TOP2", ALL_LEARNERS),
    "7.4-8": (numbered("F01-K", 0, 6), "K_EXTERNAL", ALL_LEARNERS),
    "7.4-9": (("F02-C01",), "SAT_TOP2", CUSTOMERS),
    "7.4-10": (numbered("F02-K", 0, 6), "K_EXTERNAL", CUSTOMERS),
    "7.4-11": (("F02-C01",), "SAT_TOP2", STAKEHOLDERS),
    "7.4-12": (numbered("F02-K", 0, 6), "K_EXTERNAL", STAKEHOLDERS),
    "7.4-13": (numbered("F04-DE", 1, 5), "ADMIN_MEAN", STAFF),
    "7.4-14": (numbered("F04-BO", 1, 5), "ADMIN_MEAN", STAFF),
    "7.4-15": (numbered("F04-ET", 1, 4), "ETHICS_TOP", STAFF),
    "7.4-18A": (numbered("F04-VD", 1, 5), "ADMIN_MEAN", STAFF),
    "7.4-18B": (numbered("F04-AS", 1, 5), "ADMIN_MEAN", STAFF),
    "7.4-18C": (numbered("F04-PC", 1, 5), "ADMIN_MEAN", STAFF),
}


def read_catalog(name):
    return json.loads((ROOT / "catalog" / name).read_text(encoding="utf-8"))


class BindingAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = read_catalog("indicators.json")
        cls.indicators = {row["code"]: row for row in cls.rows}
        cls.formulas = {row["formula_id"]: row for row in read_catalog("formulas.json")}

    def test_all_63_exact_source_question_formula_and_group_mappings(self):
        self.assertEqual(len(EXPECTED), 63)
        self.assertEqual(len(self.rows), len(self.indicators), "Duplicate indicator codes")
        self.assertEqual(set(self.indicators), set(EXPECTED))
        for code, (questions, formula, groups) in EXPECTED.items():
            with self.subTest(indicator=code):
                binding = self.indicators[code]["binding"]
                self.assertEqual(binding["indicator_code"], code)
                self.assertCountEqual(binding["source_question_ids"], questions)
                self.assertEqual(binding["formula_id"], formula)
                self.assertCountEqual(binding["group_codes"], groups)
                self.assertEqual(binding["formula_version"], "1.1")

    def test_units_methods_and_directions_match_source_rules(self):
        score_5 = {
            "7.2-25", "7.2-34", "7.2-35", "7.2-36", "7.3-50", "7.3-51",
            "7.3-54", "7.3-55", "7.4-2", "7.4-13", "7.4-14",
            "7.4-18A", "7.4-18B", "7.4-18C",
        }
        for code, (questions, formula, _) in EXPECTED.items():
            with self.subTest(indicator=code):
                row = self.indicators[code]
                unit = "score_5" if code in score_5 else "percent"
                if code == "7.3-38":
                    unit = "score_10"
                elif code == "7.3-44":
                    unit = "hours_per_person"
                method = "survey"
                if questions[0].startswith("F06-"):
                    method = "self_report"
                elif questions[0].startswith("F05-"):
                    method = "verified_activity"
                self.assertEqual(row["unit"], unit)
                self.assertEqual(row["assessment_method"], method)
                self.assertEqual(row["instrument_version"], "1.1")
                self.assertEqual(row["direction"], "decrease" if formula == "DIS_YES" else "increase")

    def test_twenty_formula_definitions_match_blueprint_table(self):
        blueprint = (ROOT / "docs/source/EdPEx_System_Blueprint_v1.md").read_text(encoding="utf-8")
        expected_keys = {entry[1] for entry in EXPECTED.values()}
        self.assertEqual(len(expected_keys), 20)
        source_rows = {}
        for line in blueprint.splitlines():
            cells = [cell.strip() for cell in line.strip().split("|")]
            if len(cells) == 4 and cells[1] in expected_keys:
                source_rows[cells[1]] = cells[2]
        self.assertEqual(set(source_rows), expected_keys)
        self.assertEqual(set(self.formulas), expected_keys)
        for key, source_definition in source_rows.items():
            with self.subTest(formula=key):
                formula = self.formulas[key]
                self.assertEqual(formula["definition_th"], source_definition)
                self.assertEqual(formula["formula_version"], "1.1")
                self.assertFalse(formula["missing_is_zero"])
                self.assertEqual(formula["zero_denominator"], {"status": "no_valid_data", "value": None})
                self.assertEqual(formula["rounding"], "display_only_2_decimals")
                self.assertEqual(formula["execution_status"], "specification_only_M2_pending")

    def test_f05_verified_distinct_counting_and_categories(self):
        categories = {
            "7.3-44": None, "7.3-45": ["T45"], "7.3-46": ["T46"],
            "7.3-47": ["T47S", "T47H", "T47E"], "7.3-48": ["T48"], "7.3-49": None,
        }
        source = (ROOT / "docs/source/EdPEx_6_Instruments.md").read_text(encoding="utf-8")
        source_rules = source.split("## การตรวจและสูตร F05", 1)[1].split("## ติดตามการนำไปใช้", 1)[0]
        normalize = lambda value: re.sub(r"\s+", " ", value).strip()
        for code, category in categories.items():
            with self.subTest(indicator=code):
                binding = self.indicators[code]["binding"]
                self.assertEqual(binding["parameters"], {
                    "accepted_only": True,
                    "population": "frozen_eligible_staff",
                    "category": category,
                    "distinct_unit": "person_activity_session" if code == "7.3-44" else "person",
                    "external_visit_only": code == "7.3-49",
                })
                # Preserves >0 hours, employment dates, no double-counting of
                # mixed-category hours, and the OR rule for safety subdomains.
                self.assertIn(normalize(source_rules), normalize(binding["source_rules_th"]))
        self.assertIn("อย่างน้อยหนึ่งด้าน", self.indicators["7.3-47"]["display_name"]["th"])
        ancillary = {field["field_key"]: field for field in read_catalog("ancillary_fields.json")["fields"]}
        self.assertEqual(ancillary["development.actual_visit_hours"]["separate_from"], "F05-P03")
        self.assertEqual(ancillary["development.actual_visit_hours"]["minimum"], 0)
        self.assertIn("7.3-49", ancillary["development.external_visit"]["used_by"])
        self.assertEqual(ancillary["development.session_key"]["purpose"], "no_person_activity_session_duplicates")

    def test_f06_denominators_completeness_and_optional_examples(self):
        bindings = {code: row["binding"] for code, row in self.indicators.items()}
        self.assertEqual(bindings["7.3-43"]["denominator"], "frozen_eligible_population_including_nonrespondents")
        self.assertEqual(bindings["7.4-3"]["denominator"], "complete_scored_pair")
        self.assertEqual(bindings["7.4-4"]["denominator"], "complete_scored_four")
        self.assertEqual(bindings["7.3-50"]["required_complete"], 5)
        self.assertEqual(bindings["7.3-51"]["required_complete"], 9)
        self.assertCountEqual(bindings["7.4-6"]["series_dimensions"], ["S", "E", "U", "P", "overall"])
        self.assertFalse(bindings["7.4-6"]["examples_affect_score"])
        questions = {row["question_id"]: row for row in read_catalog("questions.json")}
        for row in questions.values():
            if row["instrument_id"] == "F06":
                self.assertEqual(row["assessment_method"], "self_report")
                self.assertFalse(row["evidence_allowed"])
                self.assertFalse(row["reviewer_step"])
        for suffix in ("S", "E", "U", "P"):
            self.assertFalse(questions[f"F06-V{suffix}-EX"]["required"])

    def test_dimensions_and_f04_completeness_keep_context(self):
        for code, prefix, size in (("7.3-39", "F03-G", 7), ("7.3-54", "F06-M", 5), ("7.3-55", "F06-T", 5)):
            binding = self.indicators[code]["binding"]
            self.assertCountEqual(binding["series_dimensions"], numbered(prefix, 1, size))
            self.assertFalse(binding["overall"])
        for code in ("7.4-13", "7.4-14", "7.4-18A", "7.4-18B", "7.4-18C"):
            binding = self.indicators[code]["binding"]
            self.assertEqual(binding["minimum_answered"], 4)
            self.assertTrue(binding["requires_configured_appointment"])
            self.assertCountEqual(binding["series_dimensions"], ["person", "role", "appointment_dates", "programme"])
        ethics = self.indicators["7.4-15"]["binding"]
        self.assertEqual(ethics["required_complete"], 4)
        self.assertEqual(ethics["role"], "DE")

    def test_external_k_key_and_unknown_are_separate_from_self_report(self):
        key = read_catalog("answer_keys.server.json")
        self.assertEqual(key["correct_options"], {"K01": "B", "K02": "A", "K03": "C", "K04": "B", "K05": "A", "K06": "D"})
        self.assertCountEqual(key["instruments"], ["F01", "F02"])
        self.assertFalse(key["F06_uses_this_key"])
        self.assertEqual(key["unknown_U_score"], 0)
        self.assertEqual(key["blank"], "missing")
        self.assertEqual(key["access"], "server_only_never_include_in_respondent_schema")
        for code in ("7.4-3", "7.4-4", "7.4-6"):
            self.assertNotIn("F06-K00", self.indicators[code]["binding"]["source_question_ids"])


if __name__ == "__main__":
    unittest.main()
