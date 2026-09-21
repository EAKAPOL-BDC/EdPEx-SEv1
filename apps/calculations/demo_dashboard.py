"""Comparison of explicitly synthetic series; production approval lists stay separate."""
from apps.catalog.group_registry import group_label, export_group, EXPORT_COLUMNS
import csv
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render
from apps.selfassessments.operator_web import page
from .dashboard import authorize, csv_cell
from .models import DemoDataset
from apps.catalog.indicator_alignment import indicator_title, measurement_note
from .demo_data import DEMO_KEY, validated_series

UNITS={'percent':('%',100,'จุดร้อยละ'),'score_5':('/ 5',5,'คะแนน'),
       'score_10':('/ 10',10,'คะแนน'),'hours_per_person':('ชั่วโมง/คน',None,'ชั่วโมง/คน')}


def formatted(value):
    return format(Decimal(str(value)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP),'f')


def comparison_cards(series):
    buckets=defaultdict(list)
    for row in series:
        # Never compare different contexts, dimensions, formulas, versions or units.
        key=(row.indicator_code,row.dimension,row.form_code,row.context_key,row.formula_key,row.formula_version,row.unit)
        buckets[key].append(row)
    cards=[]
    for key,items in sorted(buckets.items()):
        first=items[0];suffix,maximum,difference_unit=UNITS[first.unit]
        values=[Decimal(r.result['value']) for r in items]
        maximum=maximum or max(1,int(max(values).to_integral_value(rounding=ROUND_CEILING)))
        bars=[]
        for r,value in sorted(zip(items,values),key=lambda pair:pair[0].group_code):
            bars.append({'label':group_label(r.group_code, r.group_label),'code':r.group_code,'value':formatted(value),
                'meter_value':str(value),'maximum':maximum,'numerator':formatted(r.result['numerator']),
                'denominator':formatted(r.result['denominator']),
                'breakdown':[{'label':{'T47S':'ความปลอดภัย','T47H':'อาชีวอนามัย','T47E':'พลังงาน'}.get(k,k),
                    'value':formatted(v['value'])} for k,v in sorted(r.result.get('breakdown',{}).items())]})
        cards.append({'code':first.indicator_code,'label':indicator_title(first.indicator_code, first.indicator_label),'measurement_note':measurement_note(first.indicator_code),'dimension':first.dimension_label,
            'form':first.form_code,'context':first.context_key,'suffix':suffix,'maximum':maximum,'bars':bars,
            'formula':first.formula_key,'direction':first.direction,'unit':first.unit,
            'formula_version':first.formula_version,'comparable':len(bars)>1,
            'difference':formatted(max(values)-min(values)),'difference_unit':difference_unit})
    return cards


@page(['GET'])
def overview(request,scope,export=False):
    authorize(request.user,scope)
    from apps.governance.models import WorkspaceRefresh
    if WorkspaceRefresh.objects.filter(scope=scope,status='completed').exists():
        from django.shortcuts import redirect
        from django.urls import reverse
        return redirect(reverse('visualization-home',args=[scope.pk])+'?source=demo')
    dataset=DemoDataset.objects.filter(scope=scope,key=DEMO_KEY).first()
    form=request.GET.get('form','');group=request.GET.get('group','');query=request.GET.get('q','').strip()[:100]
    series=dataset.series.all() if dataset else []
    all_series=list(series)
    groups=sorted({(r.group_code,group_label(r.group_code, r.group_label)) for r in all_series})
    selected=[r for r in all_series if (not form or r.form_code==form) and (not group or r.group_code==group)
        and (not query or query.casefold() in (r.indicator_code+' '+indicator_title(r.indicator_code,r.indicator_label)+' '+r.dimension_label).casefold())]
    selected, errors = validated_series(selected)
    cards=comparison_cards(selected)
    if export:
        if errors:
            return HttpResponse('Demo validation failed. Inspect the dataset before exporting.', status=409)
        response=HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition']='attachment; filename="NEXORA-DEMO-2569.csv"'
        response['X-Content-Type-Options']='nosniff';response.write('\ufeff')
        writer=csv.writer(response)
        writer.writerow(['data_kind','dataset','indicator','label','form','group','group_label','dimension','unit','value','numerator','denominator','formula','formula_version', *EXPORT_COLUMNS])
        for r in selected:
            writer.writerow([csv_cell(v) for v in ['SYNTHETIC_DEMO_NOT_ACTUAL',dataset.key,r.indicator_code,indicator_title(r.indicator_code,r.indicator_label),r.form_code,r.group_code,
                group_label(r.group_code, r.group_label, language='th'),r.dimension,r.unit,r.result['value'],r.result['numerator'],r.result['denominator'],r.formula_key,r.formula_version, *export_group(r.group_code, r.group_label)]])
        return response
    return render(request,'calculations/demo_dashboard.html',dict(scope=scope,dataset=dataset,
        cards=Paginator(cards,12).get_page(request.GET.get('page')),groups=groups,form_codes=['F01','F02','F03','F04','F05','F06'],
        form_code=form,group_code=group,query=query,filters=request.GET.urlencode(),
        indicator_count=len({r.indicator_code for r in all_series}),series_count=len(all_series),group_count=len(groups),
        error_count=errors, matched_count=len({r.indicator_code for r in selected})))
