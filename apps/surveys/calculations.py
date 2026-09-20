from dataclasses import asdict
from django.core.exceptions import ValidationError
from django.db import transaction
from apps.accounts.permissions import require_permission
from apps.calculations.services import SeriesInput, _record_calculation
from apps.calculations.types import Answer,AnswerRow
from apps.calculations.revisions import ResponseContext,ResponseRevision
from apps.calculations.models import StoredSourceSelection
from apps.rounds.models import RoundInstrument,CollectionRound,RespondentGroup
from .models import AnonymousResponse


def stored_series(selected,cutoff):
    r=selected.collection_round
    profile=selected.survey_profile
    from apps.leadership.services import validate_binding
    validate_binding(selected, r.population_snapshot)
    group=RespondentGroup.objects.get(scope=r.scope,code=profile.group_code)
    context=ResponseContext(str(r.scope_id),str(r.pk),selected.instrument_version.instrument.code,selected.instrument_version.version,selected.context)
    responses=[]
    for record in AnonymousResponse.objects.filter(binding=selected,submitted_at__lte=cutoff).order_by('pk'):
        # Free text and multichoice are not inputs to the implemented numeric formulas.
        answers={qid:Answer(v['status'],v.get('value'),v.get('reason','')) for qid,v in record.answers.items() if not isinstance(v.get('value'),list)}
        responses.append(ResponseRevision(str(record.pk),context,AnswerRow(str(record.pk),answers),1,'submitted',record.submitted_at,record.submitted_at))
    inputs=[]
    for binding in selected.instrument_version.bindings.select_related('formula').prefetch_related('questions').order_by('indicator__code'):
        if group.code not in binding.group_rules.get('group_codes',[]):continue
        if selected.instrument_version.instrument.code=='F04':
            roles={q.visibility_rule.get('role') for q in binding.questions.all()}
            if profile.assessor_role not in roles:continue
        dimensions = binding.dimensions if binding.formula.key in {'DIMENSION_SAT','SELF_DIMENSION','SELF_BEHAVIOUR'} else [None]
        for dimension in dimensions:
            inputs.append(SeriesInput(selected.pk,binding.pk,group.pk,dimension,responses=tuple(responses)))
    if not inputs:raise ValidationError('No applicable result series.')
    return inputs


@transaction.atomic
def calculate(actor,selected_id,cutoff,idempotency_key,dry_run=False):
    selected=RoundInstrument.objects.select_related('instrument_version__instrument','survey_profile').get(pk=selected_id)
    r=CollectionRound.objects.select_for_update(of=('self',)).select_related('scope','population_snapshot').get(pk=selected.collection_round_id)
    require_permission(actor,'calculation.run',r.scope)
    selected.collection_round=r
    receipt=_record_calculation(actor,round_id=r.pk,inputs=stored_series(selected,cutoff),cutoff=cutoff,idempotency_key=idempotency_key,dry_run=dry_run,permissions=('calculation.run',))
    if not dry_run:
        StoredSourceSelection.objects.get_or_create(run_id=receipt.run_id,defaults={'round_instrument':selected,'source_kind':'anonymous_surveys'})
    require_permission(actor,'calculation.run',r.scope)
    return asdict(receipt)
