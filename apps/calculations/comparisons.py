"""Cross-group approved results, grouped only on compatible frozen definitions."""
from apps.catalog.group_registry import group_label
from collections import defaultdict
from uuid import UUID
from decimal import Decimal
from datetime import timezone as datetime_timezone
from django.shortcuts import render
from django.core.exceptions import ValidationError,ObjectDoesNotExist
from django.utils import timezone
from apps.selfassessments.operator_web import page
from apps.rounds.models import ReportingPeriod,RespondentGroup
from .dashboard import approved,authorize,presentation_rows
from .review import review_summary
from .codec import canonical
from .types import CalculationInputError
from apps.leadership.services import target_context
from apps.governance.f05_registry import is_quantitative_version


def compatibility_key(run,row):
    binding=run.stored_source.round_instrument
    context=binding.context
    from apps.governance.f05_quantitative import VERSION as F05_VERSION
    if binding.instrument_version.instrument.code=='F05' and is_quantitative_version(binding.instrument_version.version):
        profile=binding.survey_profile
        context=canonical({'context_th':profile.context_th,'context_en':profile.context_en,'unit':profile.counting_unit})
    return (str(run.collection_round.period_id),str(binding.instrument_version_id),context,
        run.cutoff.astimezone(datetime_timezone.utc).isoformat(),row['indicator'],row['dimension'] or '',row['unit'],row['method'],canonical(row['formula']),run.collection_round.data_kind)


@page(['GET'])
def overview(request,scope):
    authorize(request.user,scope)
    periods=ReportingPeriod.objects.filter(calendar__scope=scope,approved=True,collection_rounds__isnull=False).distinct().order_by('-start_date')
    try:
        period=periods.filter(pk=UUID(request.GET['period'])).first() if request.GET.get('period') else periods.first()
    except (ValueError,TypeError):
        period=None
    query=request.GET.get('q','').strip()[:100]
    result,errors=approved_cards(request.user,scope,period,query=query)
    from django.core.paginator import Paginator
    return render(request,'calculations/comparisons.html',dict(scope=scope,periods=periods,selected_period=period,
        cards=Paginator(result,12).get_page(request.GET.get('page')),query=query,error_count=errors))


def approved_cards(user,scope,period,*,query='',form='',group='',data_kind=''):
    """Shared disclosure-safe comparison input; never read raw answer snapshots."""
    authorize(user,scope)
    group_labels=dict(RespondentGroup.objects.filter(scope=scope).values_list('code','label'))
    cards=defaultdict(list);errors=0;rosters={}
    if period:
        decisions=approved(scope).filter(review__run__collection_round__period=period)
        if data_kind:decisions=decisions.filter(review__run__collection_round__data_kind=data_kind)
        if form:
            decisions=decisions.filter(review__run__stored_source__round_instrument__instrument_version__instrument__code=form)
        for decision in decisions:
            run=decision.review.run
            try:packet=review_summary(user,run_id=run.pk)
            except (ValidationError,ObjectDoesNotExist,CalculationInputError):errors+=1;continue
            rows=presentation_rows(packet['results'],scope,run.stored_source.round_instrument.instrument_version_id)
            from apps.governance.f05_quantitative import VERSION as F05_VERSION
            if is_quantitative_version(run.stored_source.round_instrument.instrument_version.version):
                rosters[str(run.pk)]=set(run.collection_round.population_snapshot.members.values_list('eligible_unit_key',flat=True))
            for row in rows:
                if group and row['group'] != group:continue
                if row.get('leadership_status') == 'superseded':continue
                if query and query.casefold() not in (row['indicator']+' '+row['label']+' '+(row['dimension_label'] or '')+' '+str(row.get('leadership',{}))).casefold():continue
                row.update(data_kind=run.collection_round.data_kind,round=run.collection_round.code,run_id=run.pk,cutoff=run.cutoff,group_label=group_label(row['group'], group_labels.get(row['group'], '')),
                    form=run.stored_source.round_instrument.instrument_version.instrument.code,
                    form_version=run.stored_source.round_instrument.instrument_version.version,
                    context_label=(run.stored_source.round_instrument.survey_profile.context_th if is_quantitative_version(run.stored_source.round_instrument.instrument_version.version) else ''))
                cards[compatibility_key(run,row)].append(row)
    result=[]
    for key,rows in sorted(cards.items()):
        first=rows[0]
        from apps.governance.f05_reporting import pooled_result
        combined=pooled_result(rows,rosters)
        result.append(dict(data_kind=first['data_kind'],label=first['label'],measurement_note=first.get('measurement_note',''),indicator=first['indicator'],dimension=first['dimension_label'],unit=first['suffix'],
            context=(target_context(first['leadership'],'th') if first.get('leadership') else first.get('context_label') or key[2]),cutoff=first['cutoff'],form=first['form'],version=first['form_version'],rows=rows,combined=combined))
    return result,errors
