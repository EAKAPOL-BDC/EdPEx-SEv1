"""Internal approved-result browsing; all numeric disclosure uses review_summary."""
from apps.catalog.group_registry import export_group, EXPORT_COLUMNS
import csv
from django.db.models import Q
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from apps.catalog.models import Indicator, Question
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from apps.accounts.permissions import require_permission
from apps.selfassessments.operator_web import page
from .models import ResultDecision
from .review import review_summary
from .types import CalculationInputError
from apps.catalog.indicator_alignment import indicator_title, measurement_note


def approved(scope):
    return ResultDecision.objects.filter(outcome='approved', successors__isnull=True,
        review__run__collection_round__scope=scope,
        review__run__stored_source__round_instrument__instrument_version__instrument__code__in=['F01','F02','F03','F04','F05','F06']).select_related(
        'review__run__collection_round__period',
        'review__run__stored_source__round_instrument__survey_profile__annual_target',
        'review__run__stored_source__round_instrument__instrument_version__instrument').order_by('-created_at','-pk')


def authorize(user,scope):
    for action in ('result.review','calculation.validate'):
        require_permission(user,action,scope)


@page(['GET'])
def overview(request,scope):
    authorize(request.user,scope)
    decisions=approved(scope)
    kind=request.GET.get('kind','')
    year=request.GET.get('year','')
    if kind in {'real','synthetic'}:decisions=decisions.filter(review__run__collection_round__data_kind=kind)
    if year.isdigit():decisions=decisions.filter(review__run__collection_round__period__reporting_year_be=int(year))
    code=request.GET.get('form','')
    query=request.GET.get('q','').strip()[:100]
    if code:
        decisions=decisions.filter(review__run__stored_source__round_instrument__instrument_version__instrument__code=code)
    if query:
        decisions=decisions.filter(Q(review__run__collection_round__code__icontains=query)|Q(review__run__stored_source__round_instrument__survey_profile__annual_target__snapshot__person_th__icontains=query)|Q(review__run__stored_source__round_instrument__survey_profile__annual_target__title_th__icontains=query))
    return render(request,'calculations/dashboard.html',{'scope':scope,'decisions':Paginator(decisions,20).get_page(request.GET.get('page')),
        'form_code':code,'query':query,'data_kind':kind,'year':year,'form_codes':['F01','F02','F03','F04','F05','F06']})


def csv_cell(value):
    text='' if value is None else str(value)
    return "'"+text if text.lstrip().startswith(('=','+','-','@')) or text.startswith(('\t','\r','\n')) else text


@page(['GET'])
def detail(request,scope,run_id,export=False):
    authorize(request.user,scope)
    decision=get_object_or_404(approved(scope),review__run_id=run_id)
    run=decision.review.run
    try:
        packet=review_summary(request.user,run_id=run.pk)
    except (ValidationError,CalculationInputError,ObjectDoesNotExist):
        return render(request,'calculations/dashboard_detail.html',{'scope':scope,'decision':decision,'invalid':True},status=409)
    rows=packet['results']
    public_intake = run.manifest.get('intake', {})
    intake_columns = [public_intake.get('method', 'legacy'), public_intake.get('limitation', '')]
    if export:
        response=HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition']=f'attachment; filename="nexora-results-{run.pk}.csv"'
        response['X-Content-Type-Options']='nosniff'
        response.write('\ufeff')
        writer=csv.writer(response)
        writer.writerow(['data_kind','round','run_id','cutoff','approved_at','indicator','group','dimension','unit','status','value','numerator','denominator','restriction','publication_status', *EXPORT_COLUMNS, 'fiscal_year','evaluatee_code','evaluatee_name','position_code','position_title','programme_code','programme_name','assessed_from','assessed_until','target_id','target_status','indicator_title','interpretation','intake_method','participation_limitations'])
        for row in rows:
            writer.writerow([csv_cell(v) for v in [run.collection_round.data_kind,run.collection_round.code,run.pk,run.cutoff.isoformat(),decision.created_at.isoformat(),
                row['indicator'],row['group'],row['dimension'],row['unit'],row['status'],row.get('value'),row.get('numerator'),row.get('denominator'),row.get('reason',''),'unpublished', *export_group(row['group']), *[row.get('leadership',{}).get(k,'') for k in ('fiscal_year','person_code','person_th','position_code','title_th','programme_code','programme_th','start_date','last_date','target_id')],row.get('leadership_status',''),indicator_title(row['indicator']),measurement_note(row['indicator'],method=row.get('method',''),formula_version=row.get('formula',{}).get('instrument_version','')), *intake_columns]])
            for category,part in row.get('breakdown',{}).items():
                writer.writerow([csv_cell(v) for v in [run.collection_round.data_kind,run.collection_round.code,run.pk,run.cutoff.isoformat(),decision.created_at.isoformat(),row['indicator'],row['group'],category,row['unit'],part['status'],part.get('value'),part.get('numerator'),part.get('denominator'),'small_group' if part['status']=='suppressed' else '','unpublished',*export_group(row['group']),*['']*11,indicator_title(row['indicator']),measurement_note(row['indicator'],method=row.get('method',''),formula_version=row.get('formula',{}).get('instrument_version','')), *intake_columns]])
        return response
    cards = presentation_rows(rows, scope, run.stored_source.round_instrument.instrument_version_id)
    restricted = sum(r['status'] == 'suppressed' for r in rows)
    return render(request,'calculations/dashboard_detail.html',{'scope':scope,'decision':decision,'rows':cards,'public_intake':public_intake,
        'restricted_count':restricted, 'visible_count':sum(r['has_value'] for r in cards),
        'unavailable_count':sum(not r['has_value'] and r['status'] != 'suppressed' for r in cards),
        'f04_target':next((r.get('leadership') for r in rows if r.get('leadership')),None),
        'f04_target_status':next((r.get('leadership_status') for r in rows if r.get('leadership')),None)})


def presentation_rows(rows, scope, version_id):
    # Labels are metadata; numeric values come only from the disclosure-filtered packet.
    labels = dict(Indicator.objects.filter(scope=scope, code__in=[r['indicator'] for r in rows]).values_list('code', 'display_name_th'))
    questions = dict(Question.objects.filter(version_id=version_id).values_list('question_id', 'text_th'))
    units = {'percent': ('ร้อยละ', '%', 100), 'score_10': ('คะแนนเต็ม 10', '/ 10', 10),
             'score_5': ('คะแนนเต็ม 5', '/ 5', 5), 'hours_per_person': ('ชั่วโมง/คน','ชั่วโมง/คน',None)}
    cards = []
    for source in rows:
        row = dict(source)
        row['label'] = indicator_title(row['indicator'], labels.get(row['indicator']))
        row['measurement_note'] = measurement_note(row['indicator'], method=row.get('method',''), formula_version=row.get('formula',{}).get('instrument_version',''))
        if row.get('method')=='anonymous_self_report':
            from apps.governance.f05_registry import for_version
            MAP=for_version(row['formula']['instrument_version']).MAP
            if row['indicator'] in MAP:row['label']=MAP[row['indicator']][2]
        row['dimension_label'] = questions.get(row['dimension'], row['dimension'])
        unit, suffix, maximum = units.get(row['unit'], (row['unit'], row['unit'], None))
        row.update(unit_label=unit, suffix=suffix, has_value=False, chart=False)
        if row['status'] != 'suppressed' and row.get('value') is not None:
            try:
                value = Decimal(str(row['value']))
                if value.is_finite():
                    row['has_value'] = True
                    row['display_value'] = format(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), 'f').rstrip('0').rstrip('.') if value else '0'
                    if maximum is not None and 0 <= value <= maximum:
                        row.update(chart=True, chart_value=str(value), chart_max=maximum)
            except (InvalidOperation, ValueError):
                pass
        row['breakdown_rows']=[]
        for code,part in row.get('breakdown',{}).items():
            item={'code':code,'label':{'T47S':'ความปลอดภัย / Safety','T47H':'อาชีวอนามัย / Occupational health','T47E':'พลังงาน / Energy'}.get(code,code),**part}
            if item.get('value') is not None:item['display_value']=format(Decimal(item['value']).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP),'f')
            row['breakdown_rows'].append(item)
        cards.append(row)
    return sorted(cards, key=lambda r: (r['indicator'], r['dimension'] or '', r['group']))
