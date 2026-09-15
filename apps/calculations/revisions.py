"""Deterministic revision selection in one explicit measurement context."""
from dataclasses import dataclass
from datetime import datetime

from .types import AnswerRow, CalculationInputError, require_id


def aware_datetime(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise CalculationInputError("Cutoff and source timestamps must be timezone aware.")


@dataclass(frozen=True)
class ResponseContext:
    scope_id: str
    round_id: str
    instrument_id: str
    instrument_version: str
    measurement_context_id: str

    def __post_init__(self):
        for value in self.__dict__.values():
            require_id(value)


@dataclass(frozen=True)
class ResponseRevision:
    revision_id: str
    context: ResponseContext
    row: AnswerRow
    revision_number: int
    status: str
    created_at: datetime
    submitted_at: datetime | None = None

    def __post_init__(self):
        require_id(self.revision_id)
        if not isinstance(self.context, ResponseContext) or not isinstance(self.row, AnswerRow):
            raise CalculationInputError("Revision requires a typed context and row.")
        if type(self.revision_number) is not int or self.revision_number < 1:
            raise CalculationInputError("Revision number must be a positive integer.")
        if self.status not in {"draft", "submitted"}:
            raise CalculationInputError("Unsupported response revision status.")
        aware_datetime(self.created_at)
        if self.status == "submitted":
            aware_datetime(self.submitted_at)
            if self.submitted_at < self.created_at:
                raise CalculationInputError("Submission cannot precede creation.")
        elif self.submitted_at is not None:
            raise CalculationInputError("Draft cannot have a submission timestamp.")


def latest_submitted(revisions, *, context, cutoff):
    """Latest submitted revision per unit, including cutoff; drafts never win.

    Input is deliberately rejected if it mixes scopes, rounds, versions or contexts.
    A selection returns revision objects, so the eventual manifest can retain IDs.
    """
    aware_datetime(cutoff)
    if not isinstance(context, ResponseContext):
        raise CalculationInputError("Expected a response context.")
    identities, numbers, latest = {}, set(), {}
    for revision in revisions:
        if not isinstance(revision, ResponseRevision) or revision.context != context:
            raise CalculationInputError("Revisions must share the requested measurement context.")
        if revision.revision_id in identities:
            if identities[revision.revision_id] != revision:
                raise CalculationInputError("Conflicting source revision ID.")
            continue
        identities[revision.revision_id] = revision
        identity = (revision.row.unit_id, revision.revision_number)
        if identity in numbers:
            raise CalculationInputError("Ambiguous revision number for response unit.")
        numbers.add(identity)
        if revision.status != "submitted" or revision.submitted_at > cutoff:
            continue
        previous = latest.get(revision.row.unit_id)
        ordering = (revision.submitted_at, revision.revision_number)
        if previous is None or ordering > (previous.submitted_at, previous.revision_number):
            latest[revision.row.unit_id] = revision
    return tuple(latest[key] for key in sorted(latest))
