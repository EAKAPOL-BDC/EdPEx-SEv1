"""Synthetic fixtures only; publish through the existing version/round services."""
from datetime import date, timedelta
import json
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.models import AccessScope, Membership, Organization, Role, RoleAssignment
from apps.catalog.models import (BindingQuestion, ContentTranslation, FormulaVersion, Indicator,
    IndicatorBinding, Instrument, InstrumentContent, InstrumentVersion, Question, QuestionOption, TranslationBundle, source_hash)
from apps.catalog.services import (approve_translation, publish_bundle, publish_instrument_version,
    source_texts, translation_review_snapshot)
from apps.rounds.models import (Calendar, CollectionRound, DataSource, PopulationMember, PopulationSnapshot,
    ReportingPeriod, RespondentGroup, RoundInstrument)
from apps.rounds.services import approve_period, freeze_population, transition_round
from apps.calculations.catalog import Catalog, CATALOG_DIR
from apps.calculations.revisions import ResponseContext, ResponseRevision
from apps.calculations.services import SeriesInput
from apps.calculations.types import Answer, AnswerRow


def grant(user, scope, actions, code):
    membership, _ = Membership.objects.get_or_create(user=user, organization=scope.organization)
    role = Role.objects.create(code=code, permissions=actions)
    return RoleAssignment.objects.create(membership=membership, scope=scope, role=role)


def scenario():
    actor = get_user_model().objects.create_user(username="synthetic-calculation-operator")
    org = Organization.objects.create(name="Synthetic calculation organization")
    scope = AccessScope.objects.create(organization=org, code="SYNTHETIC", name="Synthetic scope")
    grant(actor, scope, ["catalog.read", "catalog.edit", "catalog.publish", "translation.review", "round.manage",
                        "calendar.manage", "population.manage", "calculation.run", "calculation.source", "calculation.validate"], "synthetic-m2-operator")
    now = timezone.now()
    calendar = Calendar.objects.create(scope=scope, code="FY", label="Synthetic year", calendar_type="calendar")
    period = ReportingPeriod.objects.create(calendar=calendar, code=f"SYN-{now.year}", reporting_year_be=now.year+543,
        start_date=date(now.year, 1, 1), end_date=date(now.year+1, 1, 1))
    period = approve_period(actor, period, reason="Synthetic period")
    collection_round = CollectionRound.objects.create(scope=scope, period=period, code="synthetic-round", owner=actor,
        open_at=now-timedelta(hours=2), due_at=now+timedelta(hours=1), close_at=now+timedelta(hours=2), privacy_notice="Synthetic notice")
    groups = {code: RespondentGroup.objects.create(scope=scope, code=code, label="Synthetic "+code) for code in ("ST1", "C5.3")}
    provenance = DataSource.objects.create(scope=scope, title="Synthetic population", location="test fixture", source_type="raw", original_method="Synthetic roster")
    population = PopulationSnapshot.objects.create(collection_round=collection_round, definition="Synthetic frozen population",
        counting_unit="per-group defined unit", counts_by_group={"ST1": 2, "C5.3": 2}, source=provenance)
    for code, ids in (("ST1", ("staff-A", "staff-B")), ("C5.3", ("eligibility-org-A", "eligibility-org-B"))):
        for identifier in ids:
            PopulationMember.objects.create(snapshot=population, group=groups[code], eligible_unit_key=identifier)
    freeze_population(actor, population)
    catalog = Catalog()
    scales = {s["scale_id"]: s for s in json.loads((CATALOG_DIR / "scales.json").read_text())}
    versions, round_instruments, bindings = {}, {}, {}
    for instrument_code, codes in (("F06", ("7.4-3", "7.3-43")), ("F02", ("7.2-13", "7.2-17")), ("F05", ("7.3-44", "7.3-49"))):
        instrument = Instrument.objects.create(scope=scope, code=instrument_code)
        version = InstrumentVersion.objects.create(instrument=instrument, version="1.1", title_th="Synthetic "+instrument_code,
            assessment_method="self_report" if instrument_code=="F06" else "verified_activity" if instrument_code=="F05" else "survey",
            response_unit="person" if instrument_code!="F02" else "organization", instructions_curated=True)
        InstrumentContent.objects.create(version=version, content_key="instructions", kind="instruction", text_th="Synthetic instructions", audience="respondent")
        questions = {}
        required_ids = sorted({qid for code in codes for qid in catalog.indicators[code]["binding"]["source_question_ids"]})
        for qid in required_ids:
            item = catalog.questions[qid]
            q = Question.objects.create(version=version, question_id=qid, text_th=item["text"]["th"], answer_type=item["answer_type"],
                scale=scales.get(item.get("scale_id"), {}), group_codes=item["group_codes"], answer_statuses=item["answer_statuses"], source_metadata=item)
            for position, option in enumerate(item["options"]):
                QuestionOption.objects.create(question=q, code=option["code"], score=option.get("score"), position=position,
                    label_th=option["label"]["th"], answer_status="not_applicable" if option["code"]=="NA" else "answered")
            questions[qid] = q
        for code in codes:
            item = catalog.indicators[code]
            b = item["binding"]
            f = catalog.formulas[b["formula_id"]]
            formula, _ = FormulaVersion.objects.get_or_create(scope=scope, key=b["formula_id"], version="1.1",
                defaults={"definition_th": f["definition_th"], "parameters": f, "source_hash": "a"*64})
            indicator = Indicator.objects.create(scope=scope, code=code, original_name_status="synthetic", display_name_th="Synthetic "+code,
                display_name_status="synthetic", unit=item["unit"], direction=item["direction"])
            binding = IndicatorBinding.objects.create(version=version, indicator=indicator, formula=formula,
                group_rules={"group_codes": b["group_codes"]}, dimensions=b.get("series_dimensions", []), source_metadata=b, indicator_snapshot=item)
            for qid in b["source_question_ids"]:
                BindingQuestion.objects.create(binding=binding, question=questions[qid])
            bindings[code] = binding
        bundle = TranslationBundle.objects.create(instrument_version=version, bundle_version="synthetic-1")
        for key, text in source_texts(version).items():
            for locale in ("th", "en"):
                entry = ContentTranslation.objects.create(bundle=bundle, content_key=key, locale=locale,
                    text=text if locale=="th" else "Synthetic reviewed translation", source_hash=source_hash(text))
                preview = translation_review_snapshot(actor, entry)
                approve_translation(actor, entry, reviewed_token=preview["reviewed_token"])
        publish_bundle(actor, bundle)
        version = publish_instrument_version(actor, version)
        versions[instrument_code] = version
        round_instruments[instrument_code] = RoundInstrument.objects.create(collection_round=collection_round,
            instrument_version=version, translation_bundle=bundle, context="synthetic-"+instrument_code)
    collection_round = transition_round(actor, collection_round, "ready")
    collection_round = transition_round(actor, collection_round, "open")
    collection_round = transition_round(actor, collection_round, "closed", reason="Synthetic manual close")
    return SimpleNamespace(actor=actor, org=org, scope=scope, round=collection_round, groups=groups,
        versions=versions, round_instruments=round_instruments, bindings=bindings, cutoff=now-timedelta(minutes=10), catalog=catalog)


def response_context(fixture, instrument="F06"):
    return ResponseContext(str(fixture.scope.pk), str(fixture.round.pk), instrument, "1.1", fixture.round_instruments[instrument].context)


def packet(fixture, code="7.4-3", *, unit="staff-A", values=None, revision=1):
    binding = fixture.bindings[code]
    instrument = binding.version.instrument.code
    group = "C5.3" if instrument=="F02" else "ST1"
    spec = fixture.catalog.spec(code, group_code=group)
    values = values or [4]*len(spec.question_ids)
    row = AnswerRow(unit, {qid: Answer("answered", value) for qid, value in zip(spec.question_ids, values)})
    response = ResponseRevision(f"synthetic-revision-{instrument}-{unit}-{revision}", response_context(fixture, instrument), row,
        revision, "submitted", fixture.cutoff-timedelta(minutes=2), fixture.cutoff-timedelta(minutes=1))
    return SeriesInput(fixture.round_instruments[instrument].pk, binding.pk, fixture.groups[group].pk, responses=(response,))
