"""Read-only adapter for the checked-in 1.1 catalog; never loads live drafts.

This validates formula/question/scale/group/dimension compatibility. It does not
authorize a caller or certify that a respondent belongs to a group/context.
"""
import json
from pathlib import Path

from .engine import ACTIVITY_KEYS, validate_spec
from .types import CalculationInputError, FormulaSpec


CATALOG_DIR = Path(__file__).resolve().parents[2] / "catalog"


class Catalog:
    def __init__(self, directory=CATALOG_DIR):
        directory = Path(directory)
        self.indicators = self._read(directory, "indicators.json", "code")
        self.questions = self._read(directory, "questions.json", "question_id")
        self.formulas = self._read(directory, "formulas.json", "formula_id")

    @staticmethod
    def _read(directory, filename, key):
        rows = json.loads((directory / filename).read_text(encoding="utf-8"))
        records = {row[key]: row for row in rows}
        if len(records) != len(rows):
            raise CalculationInputError("Duplicate catalog IDs.")
        return records

    def spec(self, indicator_code, *, group_code, dimension=None):
        try:
            indicator = self.indicators[indicator_code]
        except KeyError as exc:
            raise CalculationInputError("Unknown indicator.") from exc
        binding = indicator["binding"]
        if group_code not in binding["group_codes"]:
            raise CalculationInputError("Indicator is not bound to this group.")
        key = binding["formula_id"]
        questions = tuple(binding["source_question_ids"])
        if key in {"DIMENSION_SAT", "SELF_DIMENSION"}:
            if dimension not in binding["series_dimensions"]:
                raise CalculationInputError("Select an individual dimension; no overall mean is defined.")
            questions = (dimension,)
        elif key == "SELF_BEHAVIOUR":
            if dimension not in binding["series_dimensions"]:
                raise CalculationInputError("Select a value dimension or overall.")
            if dimension != "overall":
                questions = (f"F06-V{dimension}",)
        elif dimension is not None:
            raise CalculationInputError("Unexpected formula dimension.")
        if key in ACTIVITY_KEYS:
            # Attendance is a normalized source contract, not a scored questionnaire.
            questions = ()
        categories = binding.get("parameters", {}).get("category", [])
        category = categories[0] if key == "TRAINING_PEOPLE" and len(categories) == 1 else ""
        spec = FormulaSpec(key, questions, indicator["instrument_version"], binding["formula_version"], category)
        if key not in self.formulas or self.formulas[key]["formula_version"] != spec.formula_version:
            raise CalculationInputError("Formula version is not available in this catalog.")
        validate_spec(spec)
        for question_id in questions:
            question = self.questions.get(question_id)
            if question is None or question["instrument_version"] != spec.instrument_version:
                raise CalculationInputError("Question version is unavailable.")
            if group_code not in question["group_codes"]:
                raise CalculationInputError("Question does not apply to this group.")
            allowed = {
                "SAT_TOP2": {"SAT", "AGR", "ADM"}, "DIS_YES": {"DIS"},
                "MEAN_5": {"SAT", "AGR", "ADM", "RECOMMEND_5"},
            }.get(key)
            if allowed is not None and question["scale_id"] not in allowed:
                raise CalculationInputError("Question scale is incompatible with this formula.")
        return spec
