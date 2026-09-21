"""Canonical, versioned snapshot representation; no pickle or executable input."""
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from .engine import Attendance, calculate, validate_spec
from .types import Answer, AnswerRow, CalculationInputError, FormulaSpec, FrozenPopulation


SCHEMA_VERSION = 1
ENGINE_FILES = ("engine.py", "types.py", "revisions.py", "codec.py")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def timestamp(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise CalculationInputError("Snapshot timestamps must be timezone aware.")
    return value.astimezone(timezone.utc).isoformat()


def engine_identity():
    root = Path(__file__).resolve().parent
    files = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in ENGINE_FILES}
    commit = os.environ.get("EDPEX_ENGINE_COMMIT", "")
    if not commit:
        try:
            commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, stderr=subprocess.DEVNULL,
                text=True, timeout=5,
            ).strip()
        except (OSError, subprocess.SubprocessError) as exc:
            raise CalculationInputError("Set EDPEX_ENGINE_COMMIT to the deployed commit SHA.") from exc
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise CalculationInputError("Engine commit must be a full Git SHA.")
    return {"commit": commit, "hash": digest(files), "files": files}


def encode_spec(spec):
    validate_spec(spec)
    value = asdict(spec)
    value["question_ids"] = list(spec.question_ids)
    return value


def decode_spec(value):
    expected = {"formula_key", "question_ids", "instrument_version", "formula_version", "category"}
    if not isinstance(value, dict) or set(value) != expected:
        raise CalculationInputError("Unsupported formula snapshot schema.")
    spec = FormulaSpec(**value)
    validate_spec(spec)
    return spec


def encode_row(row, question_ids):
    answers = {}
    for key in question_ids:
        answer = row.answers.get(key, Answer())
        value = answer.value
        if isinstance(value, Decimal):
            if not value.is_finite() or value != value.to_integral_value():
                raise CalculationInputError("Scored answers must use integer scales.")
            value = int(value)
        answers[key] = {"status": answer.status, "value": value, "reason": answer.reason}
    return {"unit_id": row.unit_id, "answers": answers}


def decode_row(value):
    return AnswerRow(value["unit_id"], {key: Answer(**answer) for key, answer in value["answers"].items()})


def encode_attendance(value):
    return {
        "unit_id": value.unit_id, "activity_id": value.activity_id, "session_id": value.session_id,
        "training_hours": str(value.training_hours), "visit_hours": str(value.visit_hours),
        "categories": sorted(value.categories), "status": value.status,
        "external_visit": value.external_visit, "evidence_verified": value.evidence_verified,
    }


def decode_attendance(value):
    values = dict(value)
    values["training_hours"] = Decimal(values["training_hours"])
    values["visit_hours"] = Decimal(values["visit_hours"])
    return Attendance(**values)


def encode_result(value):
    return {
        "status": value.status, "value": None if value.value is None else str(value.value),
        "numerator": None if value.numerator is None else str(value.numerator),
        "denominator": None if value.denominator is None else str(value.denominator),
        "unit": value.unit, "counts": dict(value.counts),
        "breakdown": {key: encode_result(item) for key, item in sorted(value.breakdown.items())},
    }


def replay_input(payload):
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise CalculationInputError("Unsupported input snapshot version.")
    spec = decode_spec(payload["spec"])
    population = payload["population"]
    if population is not None:
        population = FrozenPopulation(population["snapshot_id"], population["unit_ids"])
    return encode_result(calculate(spec, [decode_row(row) for row in payload["rows"]],
        population=population, attendances=[decode_attendance(row) for row in payload["attendances"]]))
