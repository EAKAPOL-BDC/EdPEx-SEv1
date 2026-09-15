"""Explicit, transactional import of the checked-in M0 specification only."""
import hashlib
import json
import re
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.permissions import require_permission
from .models import (BindingQuestion, ContentTranslation, FormulaVersion, Indicator, IndicatorBinding,
                     Instrument, InstrumentContent, InstrumentVersion, Question, QuestionOption,
                     TranslationBundle, LocalizedLabel, FORMULA_KEYS, source_hash)
from .services import _audit, source_texts


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


@transaction.atomic
def seed_catalog(scope, actor, version="1.1", catalog_dir=None):
    """Never runs during migrate. Existing versions are compared, never overwritten."""
    require_permission(actor, "catalog.edit", scope)
    catalog_dir = Path(catalog_dir or settings.BASE_DIR / "catalog")
    loaded = {p.stem: json.loads(p.read_text(encoding="utf-8-sig")) for p in catalog_dir.glob("*.json")}
    manifest = loaded["manifest"]
    if version != "1.1" or manifest["catalog_version"] != version or manifest["blueprint_version"] != "1.2":
        raise ValidationError("This seed imports only the checked Blueprint 1.2 / Instruments 1.1 catalog.")
    for document in manifest["source_documents"]:
        path = catalog_dir.parent / document["path"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != document["sha256"]:
            raise ValidationError(f"Source document checksum mismatch: {document['path']}.")
    if {row["formula_id"] for row in loaded["formulas"]} != set(FORMULA_KEYS):
        raise ValidationError("Formula keys differ from the reviewed M0 allowlist.")
    seed_hash = _digest(loaded)
    versions = {}
    created_codes = []
    # First reject conflicts for the entire scope before adding anything.
    for item in loaded["instruments"]:
        instrument, _ = Instrument.objects.get_or_create(scope=scope, code=item["instrument_id"])
        existing = InstrumentVersion.objects.filter(instrument=instrument, version=version).first()
        if existing:
            if existing.status != "draft":
                raise ValidationError("Seeding cannot overwrite or reseed published versions.")
            if existing.source_metadata.get("seed_hash") != seed_hash:
                raise ValidationError("Existing seed differs; create a new instrument version.")
            versions[instrument.code] = existing
        else:
            versions[instrument.code] = InstrumentVersion.objects.create(
                instrument=instrument, version=version, title_th=item["title_th"], checksum=seed_hash,
                assessment_method=item["assessment_method"], response_unit=item["response_unit"],
                identity_domain=item["identity_domain"], group_codes=item["group_codes"],
                workflow=item["workflow"], requirements=item["blueprint_requirements"],
                source_metadata={"seed_hash": seed_hash, "manifest": manifest, "catalog_instrument": item},
            )
            created_codes.append(instrument.code)
    for namespace, rows, code_key, text_key in (
        ("group", loaded["groups"], "code", "label"),
        ("indicator", loaded["indicators"], "code", "display_name"),
    ):
        for row in rows:
            LocalizedLabel.objects.get_or_create(scope=scope, namespace=namespace, key=row[code_key], version=version,
                defaults={"source_th": row[text_key]["th"], "text_en": row[text_key].get("en") or "",
                    "source_hash": source_hash(row[text_key]["th"]), "source_metadata": row})
    if not created_codes:
        return {"created_instruments": 0, "instrument_versions": versions}
    scales = {scale["scale_id"]: scale for scale in loaded["scales"]}
    questions = {}
    for row in loaded["questions"]:
        current_version = versions[row["instrument_id"]]
        if row["instrument_id"] not in created_codes:
            questions[row["question_id"]] = current_version.questions.get(question_id=row["question_id"])
            continue
        scale = scales.get(row.get("scale_id"), {})
        question = Question.objects.create(
            version=current_version, question_id=row["question_id"], text_th=row["text"]["th"],
            answer_type=row["answer_type"], required_rule={"required": row["required"], **row.get("required_condition", {})},
            visibility_rule=row.get("visibility_condition", {}), scale=scale,
            group_codes=row.get("group_codes", []), answer_statuses=row.get("answer_statuses", []),
            audience=row.get("audience", "respondent"), source_metadata=row, requirements=row.get("blueprint_requirements", []),
        )
        questions[row["question_id"]] = question
        for position, option in enumerate(row.get("options") or scale.get("options", [])):
            na_status = "unable_to_assess" if row.get("scale_id") in ("AGR", "ADM") else "not_applicable"
            status = option.get("answer_status") or (na_status if option["code"] == "NA" else "answered")
            QuestionOption.objects.create(question=question, code=option["code"], label_th=option["label"]["th"],
                score=option.get("score"), answer_status=status, position=position)
    for item in loaded["instruments"]:
        code = item["instrument_id"]
        if code not in created_codes:
            continue
        current_version = versions[code]
        InstrumentContent.objects.create(version=current_version, content_key=f"{code}.title", kind="title",
            text_th=item["title_th"], audience="respondent")
        active_code = None
        for section in loaded["instrument_sections"]:
            match = re.match(r"# (F0[1-6])\b", section["heading_th"])
            if match:
                active_code = match.group(1)
            elif section["heading_th"].startswith("# "):
                active_code = None  # Shared K and administrator material remain private for every form.
            if active_code is None or active_code == code:
                InstrumentContent.objects.create(version=current_version, content_key=f"{section['section_id']}.content",
                    kind="source_section", text_th=section["content_th"], audience="configuration_only", source_metadata=section)
        # Keep non-baseline implementation fields private, including optional F06 examples/plans.
        for ancillary in loaded["ancillary_fields"]["fields"]:
            prefix = ancillary["field_key"].split(".")[0]
            if (prefix == "self" and code == "F06") or (prefix == "development" and code == "F05") or (prefix == "survey" and code in ("F01", "F02", "F03", "F04")):
                InstrumentContent.objects.create(version=current_version, content_key=ancillary["field_key"], kind="ancillary",
                    text_th=ancillary.get("source_text_th", ancillary["field_key"]), audience="configuration_only", source_metadata=ancillary)
    formula_map = {}
    for row in loaded["formulas"]:
        formula, created = FormulaVersion.objects.get_or_create(scope=scope, key=row["formula_id"], version=row["formula_version"], defaults={
            "definition_th": row["definition_th"], "parameters": row, "source_hash": _digest(row),
            "requirements": row["blueprint_requirements"], "source_metadata": row.get("source", {}),
        })
        if not created and formula.source_hash != _digest(row):
            raise ValidationError("Existing formula version differs from the checked seed.")
        formula_map[row["formula_id"]] = formula
    for row in loaded["indicators"]:
        binding = row["binding"]
        source_questions = [questions[key] for key in binding["source_question_ids"]]
        version_ids = {question.version_id for question in source_questions}
        if len(version_ids) != 1:
            raise ValidationError("A seed binding must reference one instrument version.")
        current_version = source_questions[0].version
        if current_version.instrument.code not in created_codes:
            continue
        indicator, _ = Indicator.objects.get_or_create(scope=scope, code=row["code"], defaults={
            "original_name": row["original_name"], "original_name_status": row["original_name_status"],
            "display_name_th": row["display_name"]["th"], "display_name_status": row["display_name_status"],
            "unit": row["unit"], "direction": row["direction"], "requirements": row["blueprint_requirements"],
        })
        record = IndicatorBinding.objects.create(version=current_version, indicator=indicator, formula=formula_map[binding["formula_id"]],
            group_rules={"group_codes": binding["group_codes"]}, dimensions=binding.get("series_dimensions", []),
            source_metadata=binding, indicator_snapshot=row)
        for question in source_questions:
            BindingQuestion.objects.create(binding=record, question=question)
    inventory = {item["key"]: item for item in loaded["translations"]["inventory"]}
    for code in created_codes:
        current_version = versions[code]
        bundle = TranslationBundle.objects.create(instrument_version=current_version, bundle_version=loaded["translations"]["bundle_version"])
        for key, original in source_texts(current_version).items():
            entry = inventory.get(key, {})
            for locale in ("th", "en"):
                ContentTranslation.objects.create(bundle=bundle, content_key=key, locale=locale,
                    text=original if locale == "th" else (entry.get("en") or ""),
                    status="needs_review" if locale == "th" else "draft", source_hash=source_hash(original),
                    source_metadata={"seed_status": entry.get("status", "missing"), "source": entry.get("source", {})})
        _audit(actor, current_version, "catalog.seeded", checksum=seed_hash, new_version=version)
    return {"created_instruments": len(created_codes), "instrument_versions": versions}
