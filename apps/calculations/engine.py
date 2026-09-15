"""Blueprint 1.2 §11–12 / Instruments 1.1, evaluated only on the server.

Callers must select one authorized scope, period, response unit and context first.
No user expressions, translated labels, or client-calculated scores are evaluated.
"""
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, localcontext

from .types import (
    AnswerRow, CalculationInputError, FormulaSpec, FrozenPopulation, MISSING,
    Result, decimal_number, require_id, result,
)


FORMULA_KEYS = frozenset({
    "SAT_TOP2", "DIS_YES", "MEAN_5", "ENG_3", "PAIR_MEAN_TOP", "HAPPINESS_10",
    "DIMENSION_SAT", "ADMIN_MEAN", "ETHICS_TOP", "K_EXTERNAL", "SELF_VISION",
    "SELF_VALUES", "SELF_BEHAVIOUR", "SELF_COMPETENCY", "SELF_DIMENSION",
    "SELF_DIGITAL_POP", "TRAINING_HOURS", "TRAINING_PEOPLE", "SAFETY_ANY", "STUDY_VISIT",
})
ACTIVITY_KEYS = frozenset({"TRAINING_HOURS", "TRAINING_PEOPLE", "SAFETY_ANY", "STUDY_VISIT"})
SAFETY_CATEGORIES = ("T47S", "T47H", "T47E")
CATEGORIES = frozenset({"T45", "T46", *SAFETY_CATEGORIES, "T48", "OTHER"})
_ANSWER_KEY = ("B", "A", "C", "B", "A", "D")  # server only, Instruments §K


def numbered(prefix, count, start=1):
    return tuple(f"{prefix}{index:02d}" for index in range(start, start + count))


def validate_spec(spec):
    if not isinstance(spec, FormulaSpec) or spec.formula_key not in FORMULA_KEYS:
        raise CalculationInputError("Unsupported formula template.")
    if spec.formula_version != "1.1" or spec.instrument_version != "1.1":
        raise CalculationInputError("Unsupported formula/instrument version.")
    key, q = spec.formula_key, spec.question_ids
    if key in ACTIVITY_KEYS:
        if q or (key == "TRAINING_PEOPLE" and spec.category not in {"T45", "T46", "T48"}):
            raise CalculationInputError("Invalid activity formula configuration.")
        if key != "TRAINING_PEOPLE" and spec.category:
            raise CalculationInputError("Unexpected activity category.")
        return
    if spec.category:
        raise CalculationInputError("Unexpected survey category.")
    valid = False
    if key in {"SAT_TOP2", "DIS_YES", "MEAN_5"}:
        # Catalog adapter validates scale compatibility for these single-item templates.
        valid = len(q) == 1 and q[0].startswith(("F01-", "F02-", "F03-", "F04-"))
    elif key == "ENG_3":
        valid = q in (numbered("F01-E", 3), numbered("F03-E", 3))
    elif key == "PAIR_MEAN_TOP":
        valid = q == ("F03-S05", "F03-S06")
    elif key == "HAPPINESS_10":
        valid = q == ("F03-H01",)
    elif key == "DIMENSION_SAT":
        valid = len(q) == 1 and q[0] in numbered("F03-G", 7)
    elif key == "ADMIN_MEAN":
        valid = any(q == numbered(f"F04-{role}", 5) for role in ("DE", "BO", "VD", "AS", "PC"))
    elif key == "ETHICS_TOP":
        valid = q == numbered("F04-ET", 4)
    elif key == "K_EXTERNAL":
        valid = q in (numbered("F01-K", 7, 0), numbered("F02-K", 7, 0))
    elif key == "SELF_VISION":
        valid = q == numbered("F06-K", 2)
    elif key == "SELF_VALUES":
        valid = q == numbered("F06-K", 4, 3)
    elif key == "SELF_BEHAVIOUR":
        values = ("F06-VS", "F06-VE", "F06-VU", "F06-VP")
        valid = q == values or (len(q) == 1 and q[0] in values)
    elif key == "SELF_COMPETENCY":
        valid = q in (numbered("F06-A", 5), numbered("F06-A", 9))
    elif key == "SELF_DIMENSION":
        valid = len(q) == 1 and q[0] in numbered("F06-M", 5) + numbered("F06-T", 5)
    elif key == "SELF_DIGITAL_POP":
        valid = q == numbered("F06-D", 5)
    if not valid:
        raise CalculationInputError("Question set does not match formula template 1.1.")


def _score(answer, low=1, high=5):
    if answer.status != "answered":
        return None
    value = decimal_number(answer.value)
    if value != value.to_integral_value() or not low <= value <= high:
        raise CalculationInputError("Score is outside the integer scale.")
    return value


def _choice(answer, choices):
    if answer.status != "answered":
        return None
    if type(answer.value) is not str or answer.value not in choices:
        raise CalculationInputError("Invalid stable option code.")
    return answer.value


def _rows(rows, population):
    rows = tuple(rows)
    if any(not isinstance(row, AnswerRow) for row in rows):
        raise CalculationInputError("Expected AnswerRow objects.")
    ids = tuple(row.unit_id for row in rows)
    if len(ids) != len(set(ids)):
        raise CalculationInputError("Select latest revisions; duplicate response units are not allowed.")
    if population is not None:
        if not isinstance(population, FrozenPopulation):
            raise CalculationInputError("Expected a frozen population.")
        if not set(ids) <= set(population.unit_ids):
            raise CalculationInputError("Response is outside the frozen population.")
    return tuple(sorted(rows, key=lambda row: row.unit_id))


def calculate(spec, rows=(), *, population=None, attendances=()):
    """Evaluate a frozen template; malformed inputs raise CalculationInputError.

    Missing population is a result status for population-based formulas. An explicitly
    empty population instead yields no_valid_data. No database settings are loaded.
    """
    validate_spec(spec)
    with localcontext() as ctx:
        ctx.prec = 50
        if spec.formula_key in ACTIVITY_KEYS:
            if tuple(rows):
                raise CalculationInputError("Activity formulas require attendance data.")
            return _activities(spec, attendances, population)
        if tuple(attendances):
            raise CalculationInputError("Survey formulas do not accept attendance data.")
        return _survey(spec, _rows(rows, population), population)


def _survey(spec, rows, population):
    key, questions = spec.formula_key, spec.question_ids
    if key == "SELF_DIGITAL_POP" and population is None:
        return Result("insufficient_population_definition", None, None, "percent")
    ids = population.unit_ids if population is not None else tuple(row.unit_id for row in rows)
    counts = Counter({
        "eligible": len(ids), "submitted": len(rows), "not_submitted": len(ids) - len(rows),
        "valid_n": 0, "valid_answers": 0, "na": 0, "missing": 0,
        "not_shown": 0, "unable_to_assess": 0, "skipped": 0,
        "complete": 0, "submitted_partial": 0, "passed": 0, "below_threshold": 0,
    })
    total = Decimal(0)
    is_mean = key in {"MEAN_5", "HAPPINESS_10", "ADMIN_MEAN", "SELF_COMPETENCY", "SELF_DIMENSION"}
    for row in rows:
        answers = tuple(row.answers.get(q, MISSING) for q in questions)
        for answer in answers:
            status_key = {"answered": "valid_answers", "not_applicable": "na"}.get(answer.status, answer.status)
            counts[status_key] += 1
            if key == "SELF_DIMENSION" and answer.status == "not_applicable" and not answer.reason.strip():
                raise CalculationInputError("Self-declared inapplicability requires a reason.")
        if key == "DIS_YES":
            values = [_choice(answers[0], {"Y", "N"})]
        elif key == "K_EXTERNAL":
            values = [_choice(answers[0], {"seen", "not_seen", "cannot_recall"})]
            values += [_choice(answer, {"A", "B", "C", "D", "U"}) for answer in answers[1:]]
        else:
            values = [_score(answer, 0 if key == "HAPPINESS_10" else 1,
                             10 if key == "HAPPINESS_10" else 5) for answer in answers]
        valid = [value for value in values if value is not None]
        complete = len(valid) == len(questions)
        counts["complete"] += int(complete)
        counts["submitted_partial"] += int(not complete)
        required = 4 if key == "ADMIN_MEAN" else len(questions)
        if len(valid) < required:
            continue
        counts["valid_n"] += 1
        if is_mean:
            total += sum(valid, Decimal(0)) / len(valid)
            continue
        if key == "DIS_YES":
            passed = valid[0] == "Y"
        elif key == "K_EXTERNAL":
            correct = [value == expected for value, expected in zip(values[1:], _ANSWER_KEY)]
            passed = values[0] == "seen" and all(correct[:2]) and sum(correct[2:]) >= 3
        elif key in {"ENG_3", "PAIR_MEAN_TOP", "ETHICS_TOP"}:
            # Compare sums before dividing or rounding.
            passed = sum(valid) >= 4 * len(valid)
        else:
            threshold = 3 if key == "SELF_DIGITAL_POP" else 4
            passed = all(value >= threshold for value in valid)
        counts["passed"] += int(passed)
        counts["below_threshold"] += int(not passed)
        total += int(passed)
    denominator = len(ids) if key == "SELF_DIGITAL_POP" else counts["valid_n"]
    unit = "score_10" if key == "HAPPINESS_10" else "score_5" if is_mean else "percent"
    return result(total, denominator, unit, counts, ids)


@dataclass(frozen=True)
class Attendance:
    unit_id: str
    activity_id: str
    session_id: str
    training_hours: Decimal
    visit_hours: Decimal = Decimal(0)
    categories: frozenset[str] = frozenset()
    status: str = "draft"
    external_visit: bool = False
    evidence_verified: bool = False

    def __post_init__(self):
        for identifier in (self.unit_id, self.activity_id, self.session_id):
            require_id(identifier)
        for field in ("training_hours", "visit_hours"):
            hours = decimal_number(getattr(self, field))
            if hours < 0:
                raise CalculationInputError("Hours cannot be negative.")
            object.__setattr__(self, field, hours)
        categories = frozenset(self.categories)
        if not categories <= CATEGORIES:
            raise CalculationInputError("Unclassified activity category.")
        object.__setattr__(self, "categories", categories)
        if self.status not in {"draft", "submitted", "revision_requested", "accepted", "rejected"}:
            raise CalculationInputError("Invalid attendance status.")
        if type(self.external_visit) is not bool or type(self.evidence_verified) is not bool:
            raise CalculationInputError("Attendance flags must be booleans.")


def _activities(spec, attendances, population):
    unit = "hours_per_person" if spec.formula_key == "TRAINING_HOURS" else "percent"
    if population is None:
        return Result("insufficient_population_definition", None, None, unit)
    if not isinstance(population, FrozenPopulation):
        raise CalculationInputError("Expected a frozen population.")
    unique = {}
    duplicates = 0
    for attendance in attendances:
        if not isinstance(attendance, Attendance):
            raise CalculationInputError("Expected Attendance objects.")
        if attendance.unit_id not in population.unit_ids:
            raise CalculationInputError("Attendance is outside the frozen population.")
        identity = (attendance.unit_id, attendance.activity_id, attendance.session_id)
        if identity in unique:
            if unique[identity] != attendance:
                raise CalculationInputError("Conflicting attendance duplicates; resolve source records first.")
            duplicates += 1
        unique[identity] = attendance
    accepted = [a for _, a in sorted(unique.items()) if a.status == "accepted"]
    if any(not a.evidence_verified for a in accepted):
        raise CalculationInputError("Accepted F05 attendance requires verified evidence.")
    counts = {
        "eligible": len(population.unit_ids), "accepted_attendances": len(accepted),
        "excluded_attendances": len(unique) - len(accepted), "duplicate_rows_ignored": duplicates,
    }
    trained = [a for a in accepted if a.training_hours > 0]
    key = spec.formula_key
    breakdown = {}
    if key == "TRAINING_HOURS":
        numerator = sum((a.training_hours for a in accepted), Decimal(0))
    else:
        if key == "TRAINING_PEOPLE":
            people = {a.unit_id for a in trained if spec.category in a.categories}
        elif key == "STUDY_VISIT":
            people = {a.unit_id for a in accepted if a.external_visit and a.visit_hours > 0}
        else:
            by_side = {side: {a.unit_id for a in trained if side in a.categories} for side in SAFETY_CATEGORIES}
            people = set().union(*by_side.values())
            for side, side_people in by_side.items():
                breakdown[side] = result(len(side_people), len(population.unit_ids), "percent",
                                         {"eligible": len(population.unit_ids), "passed": len(side_people)},
                                         population.unit_ids)
        numerator = len(people)
        counts["passed"] = numerator
    return result(numerator, len(population.unit_ids), unit, counts, population.unit_ids, breakdown)


@dataclass(frozen=True)
class SeriesDefinition:
    """All fields except group must agree when pooling disjoint groups."""
    scope_id: str
    period_id: str
    period_type: str
    indicator_code: str
    context_id: str
    dimension_id: str
    method: str
    response_unit: str
    spec: FormulaSpec

    def __post_init__(self):
        for value in (self.scope_id, self.period_id, self.period_type, self.indicator_code,
                      self.context_id, self.method, self.response_unit):
            require_id(value)
        if not isinstance(self.dimension_id, str):
            raise CalculationInputError("Dimension ID must be text.")
        validate_spec(self.spec)


def merge_disjoint_results(parts):
    """Pool n/N (or person-level sum/count), never rounded values or overlapping units.

    This is NOT an annualization rule and does not pool historical aggregates with
    unknown denominators. Inputs must be internal results, before disclosure rules.
    """
    parts = tuple(parts)
    if not parts:
        raise CalculationInputError("At least one result is required.")
    definition, first = parts[0]
    if not isinstance(definition, SeriesDefinition) or not isinstance(first, Result):
        raise CalculationInputError("Typed series definitions and results are required.")
    ids, counts = set(), Counter()
    numerator, denominator = Decimal(0), Decimal(0)
    with localcontext() as ctx:
        ctx.prec = 50
        for candidate, item in parts:
            if candidate != definition or item.unit != first.unit:
                raise CalculationInputError("Incompatible result series.")
            if item.status not in {"computed", "no_valid_data"} or item.breakdown:
                raise CalculationInputError("Result requires source-level aggregation.")
            if ids.intersection(item.input_unit_ids):
                raise CalculationInputError("Overlapping response units; aggregate original records.")
            ids.update(item.input_unit_ids)
            counts.update(item.counts)
            numerator += item.numerator
            denominator += item.denominator
        return result(numerator, denominator, first.unit, counts, ids)
