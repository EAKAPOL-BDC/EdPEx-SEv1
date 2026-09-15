"""Immutable, server-side inputs and results; identifiers must be pseudonymous.

These objects are internal calculation data, not a disclosure-safe API payload.
"""
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP, localcontext
from types import MappingProxyType
from typing import Mapping


class CalculationInputError(ValueError):
    """Reject ambiguous/invalid input instead of manufacturing a zero result."""


def decimal_number(value):
    # Do not accept bools, floats, formatted strings, NaN or Infinity.
    if type(value) not in (int, Decimal):
        raise CalculationInputError("Expected an integer or Decimal.")
    number = Decimal(value)
    if not number.is_finite():
        raise CalculationInputError("Expected a finite number.")
    return number


def require_id(value):
    if not isinstance(value, str) or not value.strip():
        raise CalculationInputError("A nonempty stable identifier is required.")


@dataclass(frozen=True)
class Answer:
    status: str = "missing"
    value: int | Decimal | str | None = None
    reason: str = ""

    def __post_init__(self):
        if self.status not in {
            "answered", "missing", "not_applicable", "unable_to_assess",
            "not_shown", "skipped",
        }:
            raise CalculationInputError("Unknown answer status.")
        if not isinstance(self.reason, str):
            raise CalculationInputError("Answer reason must be text.")
        if self.status == "answered":
            if type(self.value) not in (str, int, Decimal) or self.value == "":
                raise CalculationInputError("Answered requires a typed value.")
            if not isinstance(self.value, str):
                decimal_number(self.value)
        elif self.value is not None:
            raise CalculationInputError("Non-score answers cannot carry a value.")


MISSING = Answer()


@dataclass(frozen=True)
class AnswerRow:
    # One response unit in a single scope/round/group/context, after revision selection.
    unit_id: str
    answers: Mapping[str, Answer]

    def __post_init__(self):
        require_id(self.unit_id)
        copied = dict(self.answers)
        for key, answer in copied.items():
            require_id(key)
            if not isinstance(answer, Answer):
                raise CalculationInputError("Answers must use the Answer contract.")
        object.__setattr__(self, "answers", MappingProxyType(copied))


@dataclass(frozen=True)
class FrozenPopulation:
    snapshot_id: str
    unit_ids: tuple[str, ...]

    def __post_init__(self):
        require_id(self.snapshot_id)
        ids = tuple(self.unit_ids)
        for unit_id in ids:
            require_id(unit_id)
        if len(ids) != len(set(ids)):
            raise CalculationInputError("Population contains duplicate units.")
        object.__setattr__(self, "unit_ids", tuple(sorted(ids)))


@dataclass(frozen=True)
class FormulaSpec:
    formula_key: str
    question_ids: tuple[str, ...] = ()
    instrument_version: str = "1.1"
    formula_version: str = "1.1"
    category: str = ""

    def __post_init__(self):
        object.__setattr__(self, "question_ids", tuple(self.question_ids))
        for question_id in self.question_ids:
            require_id(question_id)
        if len(set(self.question_ids)) != len(self.question_ids):
            raise CalculationInputError("Duplicate formula questions.")


@dataclass(frozen=True)
class Result:
    status: str
    numerator: Decimal | None
    denominator: Decimal | None
    unit: str
    counts: Mapping[str, int] = field(default_factory=dict)
    # Used only internally for safe merging. Never include in public output.
    input_unit_ids: tuple[str, ...] = field(default=(), repr=False)
    breakdown: Mapping[str, "Result"] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "counts", MappingProxyType(dict(self.counts)))
        object.__setattr__(self, "input_unit_ids", tuple(self.input_unit_ids))
        object.__setattr__(self, "breakdown", MappingProxyType(dict(self.breakdown)))

    @property
    def value(self):
        if self.status != "computed":
            return None
        with localcontext() as ctx:
            ctx.prec = 50
            factor = Decimal(100) if self.unit == "percent" else Decimal(1)
            return self.numerator / self.denominator * factor

    def display_value(self):
        if self.value is None:
            return None
        with localcontext() as ctx:
            ctx.prec = 50
            return str(self.value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def result(numerator, denominator, unit, counts, unit_ids, breakdown=None):
    n, d = decimal_number(numerator), decimal_number(denominator)
    if n < 0 or d < 0 or (unit == "percent" and n > d):
        raise CalculationInputError("Invalid numerator or denominator.")
    return Result(
        "computed" if d else "no_valid_data", n, d, unit, counts,
        tuple(sorted(unit_ids)), breakdown or {},
    )
