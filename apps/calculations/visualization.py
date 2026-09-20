"""Native NEXORA visualization modes; read-only, with identical disclosure rules."""
from apps.catalog.group_registry import group_label, export_group, EXPORT_COLUMNS
import csv
from decimal import Decimal, ROUND_CEILING
from uuid import UUID

from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render

from apps.rounds.models import ReportingPeriod, RespondentGroup
from apps.selfassessments.operator_web import page
from .comparisons import approved_cards
from .dashboard import authorize, csv_cell
from .demo_dashboard import comparison_cards, formatted, UNITS
from .demo_data import DEMO_KEY, validated_series
from .models import DemoDataset
from apps.catalog.indicator_alignment import indicator_title


FORM_LABELS = {
    'F01': 'ประสบการณ์ผู้เรียน / Learner experience',
    'F02': 'ลูกค้าและคู่ความร่วมมือ / Customers & partners',
    'F03': 'ความผูกพันบุคลากร / Staff experience',
    'F04': 'การบริหารและธรรมาภิบาล / Governance',
    'F05': 'การพัฒนาบุคลากร / Staff development',
    'F06': 'สมรรถนะบุคลากร / Staff competencies',
}


def visual_summary(cards, params):
    """Summarize safe result entries, never scores across unlike indicators.

    Ring denominators are the filtered result entries, not people, targets or
    expected submissions. All rows here have passed the disclosure projection.
    """
    forms = []
    total = sum(len(c['rows']) for c in cards)
    for i, (code, label) in enumerate(FORM_LABELS.items()):
        if params.get('form') and params['form'] != code:
            continue
        matching = [c for c in cards if c['form'] == code]
        rows = [r for c in matching for r in c['rows']]
        visible = sum(r['value'] is not None for r in rows)
        link = params.copy()
        link['form'] = code
        link.pop('focus', None)
        link.pop('page', None)
        radius = 230 - i * 29
        forms.append(dict(code=code, label=label, total=len(rows), visible=visible,
            hidden=len(rows)-visible, indicators=len({c['indicator'] for c in matching}),
            groups=len({r['group'] for r in rows}), examples=matching[:3],
            coverage=round(visible / len(rows) * 100, 1) if rows else None,
            share=format(len(rows) / total * 100, '.3f') if total else '0',
            filters=link.urlencode(), color_index=i+1, radius=90-i*12,
            arc=f'M {280-radius} 24 A {radius} {radius} 0 0 0 {280+radius} 24'))
    default = next((i for i, c in enumerate(cards) if c['comparable']), 0)
    try:
        focus_index = int(params.get('focus', default))
    except (ValueError, TypeError):
        focus_index = default
    if focus_index < 0 or focus_index >= len(cards):
        focus_index = default
    selection = params.copy()
    selection.pop('focus', None)
    selection.pop('page', None)
    return dict(form_summaries=forms, focus_card=cards[focus_index] if cards else None,
        focus_index=focus_index, focus_options=cards, focus_params=list(selection.items()))


def chart_card(card, rows):
    """Project only safe display fields. Null/hidden values never become zero."""
    unit = rows[0]['unit']
    suffix, maximum, difference_unit = UNITS.get(unit, (unit, None, unit))
    visible = [Decimal(r['value']) for r in rows if r['value'] is not None]
    if unit == 'hours_per_person':
        maximum = max(1, int(max(visible, default=Decimal(0)).to_integral_value(rounding=ROUND_CEILING)))
    for row in rows:
        value = Decimal(row['value']) if row['value'] is not None else None
        row['display'] = formatted(value) if value is not None else None
        row['width'] = format(value / Decimal(maximum) * 100, '.3f') if value is not None and maximum and 0 <= value <= maximum else None
    # Compare only one value per group. Multiple rounds in the same group are
    # shown individually without claiming a between-group difference.
    visible_rows = [r for r in rows if r['value'] is not None]
    comparable = len(visible_rows) > 1 and len({r['group'] for r in visible_rows}) == len(visible_rows)
    return dict(card, rows=rows, suffix=suffix, maximum=maximum, unit=unit,
                comparable=comparable, difference=formatted(max(visible)-min(visible)) if comparable else None,
                difference_unit=difference_unit, visible_count=len(visible_rows))


def actual_cards(user, scope, period, **filters):
    cards, errors = approved_cards(user, scope, period, **filters)
    result = []
    for card in cards:
        rows = []
        for row in card['rows']:
            rows.append(dict(group=row['group'], label=row['group_label'], unit=row['unit'],
                data_kind=row['data_kind'],value=str(row['value']) if row['has_value'] else None,
                status=row['status'], round=row['round'], run_id=row['run_id']))
        metadata = {k: card[k] for k in ('indicator', 'label', 'dimension', 'context', 'cutoff', 'form', 'version')}
        metadata['data_kind']=card['data_kind']
        metadata['measurement_note'] = card.get('measurement_note','')
        result.append(chart_card(metadata, rows))
    return result, errors


def demo_cards(series):
    result = []
    for card in comparison_cards(series):
        rows = [dict(group=b['code'], label=b['label'], unit=card['unit'], value=b['meter_value'],
                     status='computed', round='', run_id=None) for b in card['bars']]
        result.append(chart_card(dict(indicator=card['code'], label=card['label'], dimension=card['dimension'],
            form=card['form'], context=card['context'], cutoff=None, version=card['formula_version'],
            measurement_note=card.get('measurement_note','')), rows))
    return result


@page(['GET'])
def overview(request, scope, mode='home', export=False):
    authorize(request.user, scope)
    from .dashboard import approved
    from apps.governance.models import WorkspaceRefresh
    current_simulation=WorkspaceRefresh.objects.filter(scope=scope,status='completed').exists()
    default_source='demo' if current_simulation and not approved(scope).filter(review__run__collection_round__data_kind='real').exists() else 'actual'
    source = request.GET.get('source', default_source)
    if source not in ('actual', 'demo'):
        return HttpResponse('Invalid data source', status=400)
    query = request.GET.get('q', '').strip()[:100]
    form = request.GET.get('form', '')
    group = request.GET.get('group', '')
    periods = ReportingPeriod.objects.filter(calendar__scope=scope, approved=True).order_by('-start_date', 'pk')
    period = None
    if current_simulation or source=='actual':
        kind='synthetic' if source=='demo' else 'real'
        periods=periods.filter(collection_rounds__scope=scope,collection_rounds__data_kind=kind).distinct()
        try:
            period = periods.filter(pk=UUID(request.GET['period'])).first() if request.GET.get('period') else periods.first()
        except (ValueError, TypeError):
            pass
        groups = [(g.code, group_label(g.code, g.label)) for g in RespondentGroup.objects.filter(scope=scope).order_by('code')]
        cards, errors = actual_cards(request.user, scope, period, query=query, form=form, group=group,data_kind=kind)
    else:
        dataset = DemoDataset.objects.filter(scope=scope, key=DEMO_KEY).first()
        all_series = list(dataset.series.all()) if dataset else []
        groups = sorted({(r.group_code, group_label(r.group_code, r.group_label)) for r in all_series})
        series = [r for r in all_series if (not form or r.form_code == form) and (not group or r.group_code == group)
            and (not query or query.casefold() in (r.indicator_code+' '+indicator_title(r.indicator_code,r.indicator_label)+' '+r.dimension_label).casefold())]
        series, errors = validated_series(series)
        cards = demo_cards(series)
    params = request.GET.copy()
    params.pop('page', None)
    params['source'] = source
    if period:
        params['period'] = str(period.pk)
    if export:
        # A failing replay must not silently produce an apparently complete CSV.
        if errors:
            return HttpResponse('Result validation failed. Refresh and review the source results.', status=409)
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="nexora-visualization-{source}.csv"'
        response['X-Content-Type-Options'] = 'nosniff'
        response.write('\ufeff')
        writer = csv.writer(response)
        writer.writerow(['data_kind', 'period', 'indicator', 'label', 'dimension', 'form', 'context', 'version',
                         'cutoff', 'group', 'group_label', 'round', 'run_id', 'unit', 'status', 'value', *EXPORT_COLUMNS, 'interpretation'])
        for card in cards:
            for row in card['rows']:
                writer.writerow([csv_cell(v) for v in [
                    'SYNTHETIC_DEMO_NOT_ACTUAL' if source == 'demo' else 'APPROVED_INTERNAL_UNPUBLISHED',
                    period.code if period else 'DEMO-2569' if source == 'demo' else '', card['indicator'],
                    card['label'], card['dimension'], card['form'], card['context'], card['version'],
                    card['cutoff'].isoformat() if card['cutoff'] else '', row['group'], row['label'],
                    row['round'], row['run_id'], row['unit'], row['status'], row['value'], *export_group(row['group'], row['label']),card.get('measurement_note','')]])
        return response
    rows = [r for c in cards for r in c['rows']]
    visible = sum(r['value'] is not None for r in rows)
    context = dict(scope=scope, mode=mode, source=source,current_simulation=current_simulation, groups=groups, periods=periods, selected_period=period,
        form_codes=['F01','F02','F03','F04','F05','F06'], form_code=form, group_code=group, query=query,
        filters=params.urlencode(), error_count=errors, chart_count=len(cards),
        indicator_count=len({c['indicator'] for c in cards}), series_count=len(rows), visible_count=visible,
        group_count=len({r['group'] for r in rows}), hidden_count=len(rows)-visible,
        coverage=round(visible / len(rows) * 100) if rows else 0,
        comparison_count=sum(c['comparable'] for c in cards))
    context['cards'] = Paginator(cards, 8).get_page(request.GET.get('page')) if mode == 'finereport' else cards
    context.update(visual_summary(cards, params))
    return render(request, 'calculations/visualization.html', context)
