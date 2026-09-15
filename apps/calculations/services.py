"""Atomic internal source-to-result snapshots; no HTTP intake of caller scores.

The source adapter is a trusted server boundary. Until collection models exist,
explicitly authorized operators may supply typed, provenance-bearing source data.
That capability requires BOTH calculation.run and calculation.source. Ordinary
analysts receive receipts only, never raw inputs or unsuppressed result values.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from apps.accounts.permissions import require_permission
from apps.auditlog.services import record_event
from apps.catalog.models import IndicatorBinding
from apps.rounds.models import CollectionRound, PopulationMember, RespondentGroup, RoundInstrument

from .catalog import Catalog
from .codec import (SCHEMA_VERSION, canonical, digest, encode_attendance, encode_row,
                    encode_spec, engine_identity, replay_input, timestamp)
from .engine import ACTIVITY_KEYS, Attendance
from .models import CalculationInputSnapshot, CalculationRequest, CalculationRun, IndicatorResult
from .revisions import ResponseContext, ResponseRevision, aware_datetime, latest_submitted
from .types import CalculationInputError, require_id


class IdempotencyConflict(ValidationError):
    pass


@dataclass(frozen=True)
class AttendanceSource:
    revision_id: str
    revision_number: int
    context: ResponseContext
    recorded_at: object
    activity_date: date
    attendance: Attendance

    def __post_init__(self):
        require_id(self.revision_id)
        if type(self.revision_number) is not int or self.revision_number < 1:
            raise CalculationInputError("Attendance revision must be positive.")
        aware_datetime(self.recorded_at)
        if type(self.activity_date) is not date or not isinstance(self.attendance, Attendance) or not isinstance(self.context, ResponseContext):
            raise CalculationInputError("Invalid attendance source contract.")


@dataclass(frozen=True)
class SeriesInput:
    round_instrument_id: object
    binding_id: object
    group_id: object
    dimension: str | None = None
    responses: tuple[ResponseRevision, ...] = ()
    attendance_sources: tuple[AttendanceSource, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "responses", tuple(self.responses))
        object.__setattr__(self, "attendance_sources", tuple(self.attendance_sources))
        if any(not isinstance(item, ResponseRevision) for item in self.responses):
            raise CalculationInputError("Expected response revisions.")
        if any(not isinstance(item, AttendanceSource) for item in self.attendance_sources):
            raise CalculationInputError("Expected attendance source revisions.")


@dataclass(frozen=True)
class RunReceipt:
    run_id: str | None
    input_hash: str
    result_count: int
    status: str
    reused: bool = False


def _audit(actor, collection_round, action, object_id, **metadata):
    record_event(collection_round.organization, actor, action, "calculations.calculationrun", object_id,
                 metadata={"scope_id": str(collection_round.scope_id), "round_id": str(collection_round.pk), **metadata})


def _question_snapshot(question):
    return {
        "id": str(question.pk), "question_id": question.question_id, "text_th": question.text_th,
        "answer_type": question.answer_type, "scale": question.scale,
        "required_rule": question.required_rule, "visibility_rule": question.visibility_rule,
        "group_codes": question.group_codes, "answer_statuses": question.answer_statuses,
        "options": [{"code": option.code, "label_th": option.label_th,
                     "score": None if option.score is None else str(option.score),
                     "answer_status": option.answer_status}
                    for option in question.options.all().order_by("code")],
    }


def _definition(collection_round, item, catalog):
    # Restrict the query by persisted round/scope rather than trusting cached FKs.
    selected = RoundInstrument.objects.select_related("instrument_version__instrument", "translation_bundle").get(
        pk=item.round_instrument_id, collection_round=collection_round)
    version = selected.instrument_version
    binding = IndicatorBinding.objects.select_related("formula", "indicator").get(
        pk=item.binding_id, version=version, indicator__scope_id=collection_round.scope_id)
    group = RespondentGroup.objects.get(pk=item.group_id, scope_id=collection_round.scope_id)
    if version.status not in {"published", "retired"} or selected.translation_bundle.status not in {"published", "retired"} or binding.formula.status not in {"published", "retired"}:
        raise ValidationError("Calculation requires the immutable versions pinned by the round.")
    spec = catalog.spec(binding.indicator.code, group_code=group.code, dimension=item.dimension)
    expected = catalog.indicators[binding.indicator.code]["binding"]
    if (version.version != spec.instrument_version or binding.formula.key != spec.formula_key
            or binding.formula.version != spec.formula_version
            or binding.formula.parameters != catalog.formulas[spec.formula_key]
            or binding.group_rules != {"group_codes": expected["group_codes"]}
            or binding.dimensions != expected.get("series_dimensions", [])
            or binding.source_metadata != expected):
        raise ValidationError("This engine does not implement the selected definition; create a supported version.")
    questions = list(binding.questions.prefetch_related("options").order_by("question_id"))
    if {q.question_id for q in questions} != set(expected["source_question_ids"]):
        raise ValidationError("Binding questions differ from the supported formula.")
    for question in questions:
        baseline = catalog.questions[question.question_id]
        if not question.active or group.code not in question.group_codes or question.answer_type != baseline["answer_type"]:
            raise ValidationError("Question type or applicability differs from the template.")
        if question.scale.get("scale_id") != baseline.get("scale_id"):
            raise ValidationError("Question scale differs from the implemented template.")
        # Numeric/choice scoring must match the implemented scale, even if a draft
        # was edited before publishing with the same nominal version number.
        expected_options = baseline.get("options", [])
        expected_codes = {o["code"]: o.get("score") for o in expected_options}
        actual_codes = {o.code: None if o.score is None else Decimal(o.score) for o in question.options.all()}
        if actual_codes != expected_codes:
            raise ValidationError("Question options differ from the implemented scoring template.")
    if version.instrument.code == "F06" and (version.assessment_method != "self_report" or version.evidence_required or version.assessor_scoring):
        raise ValidationError("F06 must remain self-report without an assessor or evidence workflow.")
    series = {
        "scope_id": str(collection_round.scope_id), "period_id": str(collection_round.period_id),
        "calendar_type": collection_round.period.calendar.calendar_type,
        "indicator_code": binding.indicator.code, "group_code": group.code,
        "context": selected.context, "dimension": item.dimension,
        "method": version.assessment_method, "response_unit": version.response_unit,
        "spec": encode_spec(spec),
    }
    definition = {
        "series": series,
        "instrument": {"id": str(version.pk), "code": version.instrument.code, "version": version.version,
                       "checksum": version.checksum, "method": version.assessment_method},
        "translation_bundle": {"id": str(selected.translation_bundle_id), "version": selected.translation_bundle.bundle_version},
        "binding": {"id": str(binding.pk), "mapping": binding.source_metadata, "indicator_snapshot": binding.indicator_snapshot},
        "questions": [_question_snapshot(q) for q in questions],
        "formula": {"id": str(binding.formula_id), "key": binding.formula.key, "version": binding.formula.version,
                    "definition_th": binding.formula.definition_th, "parameters": binding.formula.parameters},
    }
    return selected, binding, group, spec, definition


def _attendance_payload(sources, context, cutoff, period):
    unique, identities, latest = {}, set(), {}
    for source in sources:
        if source.context != context:
            raise ValidationError("Attendance source belongs to another scope, round or context.")
        if source.revision_id in unique:
            if unique[source.revision_id] != source:
                raise ValidationError("Conflicting attendance revision ID.")
            continue
        unique[source.revision_id] = source
        record = source.attendance
        unit = (record.unit_id, record.activity_id, record.session_id)
        numbered = (*unit, source.revision_number)
        if numbered in identities:
            raise ValidationError("Conflicting attendance revision number.")
        identities.add(numbered)
        if source.recorded_at > cutoff:
            continue
        previous = latest.get(unit)
        if previous is None or (source.recorded_at, source.revision_number) > (previous.recorded_at, previous.revision_number):
            latest[unit] = source
    selected = [source for _, source in sorted(latest.items())
                if period.start_date <= source.activity_date < period.end_date]
    if any(source.attendance.status == "accepted" and source.activity_date >
           source.recorded_at.astimezone(ZoneInfo(period.calendar.timezone)).date() for source in selected):
        raise ValidationError("Accepted attendance cannot precede the actual activity date.")
    records = [encode_attendance(source.attendance) for source in selected]
    provenance = [{"revision_id": source.revision_id, "revision_number": source.revision_number,
                   "recorded_at": timestamp(source.recorded_at), "activity_date": source.activity_date.isoformat(),
                   "row_hash": digest(record)} for source, record in zip(selected, records)]
    return records, provenance


def _prepare_input(collection_round, item, cutoff, catalog):
    selected, binding, group, spec, definition = _definition(collection_round, item, catalog)
    context = ResponseContext(str(collection_round.scope_id), str(collection_round.pk),
                              selected.instrument_version.instrument.code, selected.instrument_version.version, selected.context)
    rows, records, provenance = [], [], []
    if spec.formula_key in ACTIVITY_KEYS:
        if item.responses:
            raise ValidationError("Activity formulas do not accept questionnaire responses.")
        records, provenance = _attendance_payload(item.attendance_sources, context, cutoff, collection_round.period)
    else:
        if item.attendance_sources:
            raise ValidationError("Survey formulas do not accept attendance records.")
        # Pure engine cutoff is inclusive; the collection window closes exclusively.
        effective_cutoff = min(cutoff, collection_round.close_at - timedelta(microseconds=1))
        if context.instrument_id in {"F01", "F02", "F03", "F04"}:
            submissions = {}
            for revision in item.responses:
                if revision.status == "submitted" and collection_round.open_at <= revision.submitted_at <= effective_cutoff:
                    submissions.setdefault(revision.row.unit_id, set()).add(revision.revision_id)
            if any(len(ids) > 1 for ids in submissions.values()):
                raise ValidationError("Anonymous survey units permit one submitted response per context.")
        selected_responses = latest_submitted(item.responses, context=context, cutoff=effective_cutoff)
        selected_responses = tuple(r for r in selected_responses if r.submitted_at >= collection_round.open_at)
        for revision in selected_responses:
            encoded = encode_row(revision.row, spec.question_ids)
            rows.append(encoded)
            provenance.append({"revision_id": revision.revision_id, "revision_number": revision.revision_number,
                               "submitted_at": timestamp(revision.submitted_at), "row_hash": digest(encoded)})
    snapshot = collection_round.population_snapshot
    group_count = snapshot.counts_by_group.get(group.code)
    if group_count is None:
        raise ValidationError("Group is absent from the pinned population definition.")
    population = None
    # Never pair anonymous survey response IDs with the eligibility roster.
    if context.instrument_id in {"F05", "F06"}:
        ids = list(PopulationMember.objects.filter(snapshot=snapshot, group=group).order_by("eligible_unit_key").values_list("eligible_unit_key", flat=True))
        if len(ids) != group_count:
            raise ValidationError("This staff calculation needs a complete frozen population roster.")
        population = {"snapshot_id": str(snapshot.pk), "unit_ids": ids}
    elif len(rows) > group_count:
        raise ValidationError("Response units exceed the declared population for this group/context.")
    payload = {"schema_version": SCHEMA_VERSION, "spec": encode_spec(spec), "rows": rows,
               "attendances": records, "population": population, "source_revisions": provenance}
    result = replay_input(payload)
    expected_unit = binding.indicator_snapshot.get("unit")
    if result["unit"] != expected_unit:
        raise ValidationError("Result unit differs from the frozen indicator definition.")
    return {"round_instrument": selected, "binding": binding, "group": group,
            "series_key": digest(definition["series"]), "definition": definition, "payload": payload,
            "source_hash": digest(payload), "question_hash": digest(definition["questions"]),
            "formula_hash": digest(definition["formula"]), "result": result}


def _run_manifest(collection_round, cutoff, identity, prepared):
    population = collection_round.population_snapshot
    return {
        "schema_version": SCHEMA_VERSION, "round_id": str(collection_round.pk),
        "scope_id": str(collection_round.scope_id), "cutoff": timestamp(cutoff), "engine": identity,
        "period": {"id": str(collection_round.period_id), "code": collection_round.period.code,
                   "start_date": collection_round.period.start_date.isoformat(), "end_date": collection_round.period.end_date.isoformat()},
        "population": {"id": str(population.pk), "version": population.version, "definition": population.definition,
                       "counting_unit": population.counting_unit, "counts_by_group": population.counts_by_group,
                       "frozen_at": timestamp(population.frozen_at), "source_id": str(population.source_id)},
        "sources": [{"series_key": p["series_key"], "source_hash": p["source_hash"],
                     "definition_hash": digest(p["definition"]), "question_hash": p["question_hash"],
                     "formula_hash": p["formula_hash"]} for p in prepared],
    }


def _result_manifest(results):
    return [{"series_key": key, "result_hash": checksum} for key, checksum in sorted(results)]


def record_calculation(actor, *, round_id, inputs, cutoff, idempotency_key, dry_run=False):
    """Trusted typed-source intake retains its separate source permission."""
    return _record_calculation(actor, round_id=round_id, inputs=inputs, cutoff=cutoff,
        idempotency_key=idempotency_key, dry_run=dry_run,
        permissions=("calculation.run", "calculation.source"))


@transaction.atomic
def _record_calculation(actor, *, round_id, inputs, cutoff, idempotency_key, dry_run=False, permissions):
    collection_round = CollectionRound.objects.select_for_update(of=("self",)).select_related(
        "scope__organization", "period__calendar", "population_snapshot").get(pk=round_id)
    for permission in permissions:
        require_permission(actor, permission, collection_round.scope)
    if collection_round.status not in {"closed", "review", "approved"}:
        raise ValidationError("Close collection before creating a calculation snapshot.")
    aware_datetime(cutoff)
    if not collection_round.open_at <= cutoff <= timezone.now():
        raise ValidationError("Source cutoff must be after collection starts and not in the future.")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 160:
        raise ValidationError("Supply a bounded idempotency key.")
    inputs = tuple(inputs)
    if not inputs or any(not isinstance(item, SeriesInput) for item in inputs):
        raise ValidationError("Supply at least one typed input series.")
    if collection_round.population_snapshot_id is None or collection_round.population_snapshot.status != "frozen":
        raise ValidationError("The round must pin a frozen population.")
    catalog = Catalog()
    prepared = sorted((_prepare_input(collection_round, item, cutoff, catalog) for item in inputs), key=lambda p: p["series_key"])
    if len({p["series_key"] for p in prepared}) != len(prepared):
        raise ValidationError("Duplicate result series.")
    identity = engine_identity()
    manifest = _run_manifest(collection_round, cutoff, identity, prepared)
    input_hash = digest(manifest)
    previous_request = CalculationRequest.objects.filter(collection_round=collection_round, actor=actor, idempotency_key=idempotency_key).select_related("run").first()
    if previous_request and previous_request.request_hash != input_hash:
        raise IdempotencyConflict("This key was used for different sources, definitions or cutoff.")
    existing = CalculationRun.objects.filter(collection_round=collection_round, input_hash=input_hash, status="complete").first()
    for permission in permissions:
        require_permission(actor, permission, collection_round.scope)
    if dry_run:
        return RunReceipt(str(existing.pk) if existing else None, input_hash, len(prepared), "dry_run", existing is not None)
    if previous_request:
        return RunReceipt(str(previous_request.run_id), input_hash, previous_request.run.result_count, "complete", True)
    if existing:
        run = existing
    else:
        run = CalculationRun.objects.create(collection_round=collection_round, population_snapshot=collection_round.population_snapshot,
            created_by=actor, cutoff=cutoff, engine_commit=identity["commit"], engine_hash=identity["hash"], input_hash=input_hash, manifest=manifest)
        results = []
        for item in prepared:
            source = CalculationInputSnapshot.objects.create(run=run, **{k: item[k] for k in (
                "round_instrument", "binding", "group", "series_key", "definition", "payload", "source_hash", "question_hash", "formula_hash")})
            result_hash = digest(item["result"])
            IndicatorResult.objects.create(run=run, source=source, indicator_code=item["definition"]["series"]["indicator_code"],
                series_key=item["series_key"], payload=item["result"], result_hash=result_hash)
            results.append((item["series_key"], result_hash))
        # This is the sole mutable phase. DB guards validate counts and links before
        # sealing and reject all later writes, including raw SQL and child inserts.
        run.status, run.sealed_at = "complete", timezone.now()
        run.input_count = run.result_count = len(prepared)
        run.result_hash = digest(_result_manifest(results))
        run.full_clean()
        models.Model.save(run, update_fields=["status", "sealed_at", "input_count", "result_count", "result_hash"])
        _audit(actor, collection_round, "calculation.completed", run.pk, checksum=run.input_hash, count=run.result_count)
    CalculationRequest.objects.create(collection_round=collection_round, actor=actor, idempotency_key=idempotency_key,
                                       request_hash=input_hash, run=run)
    _audit(actor, collection_round, "calculation.requested", run.pk, checksum=input_hash, status="reused" if existing else "created")
    for permission in permissions:
        require_permission(actor, permission, collection_round.scope)
    return RunReceipt(str(run.pk), input_hash, run.result_count, run.status, existing is not None)


def validate_run(actor, *, run_id):
    """Replay solely from the snapshot; return a bounded receipt, never raw values."""
    run = CalculationRun.objects.select_related("collection_round__scope").get(pk=run_id)
    require_permission(actor, "calculation.validate", run.collection_round.scope)
    if run.status != "complete" or digest(run.manifest) != run.input_hash:
        raise ValidationError("Run is incomplete or its manifest has changed.")
    if run.engine_hash != run.manifest["engine"]["hash"] or engine_identity()["hash"] != run.engine_hash:
        raise ValidationError("Use the recorded engine version to replay this run.")
    expected_sources = {p["series_key"]: p for p in run.manifest["sources"]}
    sources = list(run.inputs.order_by("series_key"))
    results = list(run.results.select_related("source").order_by("series_key"))
    if len(sources) != run.input_count or len(results) != run.result_count or len(expected_sources) != run.input_count:
        raise ValidationError("Run source/result counts differ from its seal.")
    result_map = {r.series_key: r for r in results}
    for source in sources:
        expected = expected_sources.get(source.series_key)
        actual = {"series_key": source.series_key, "source_hash": digest(source.payload),
                  "definition_hash": digest(source.definition), "question_hash": digest(source.definition["questions"]),
                  "formula_hash": digest(source.definition["formula"])}
        if actual != expected or source.source_hash != actual["source_hash"] or source.question_hash != actual["question_hash"] or source.formula_hash != actual["formula_hash"]:
            raise ValidationError("Stored source or definition checksum mismatch.")
        stored = result_map.get(source.series_key)
        if stored is None or stored.source_id != source.pk or stored.result_hash != digest(stored.payload) or replay_input(source.payload) != stored.payload:
            raise ValidationError("Stored result differs from replay.")
    if digest(_result_manifest((r.series_key, r.result_hash) for r in results)) != run.result_hash:
        raise ValidationError("Result set checksum mismatch.")
    require_permission(actor, "calculation.validate", run.collection_round.scope)
    return {"run_id": str(run.pk), "status": "verified", "matched_results": len(results), "input_hash": run.input_hash,
            "engine_hash": run.engine_hash, "engine_commit": run.engine_commit}
