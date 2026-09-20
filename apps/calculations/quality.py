"""Read-only quality/availability audit over disclosure-checked actual results."""
import csv
import json
from collections import Counter
from uuid import UUID
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from apps.catalog.models import Indicator, IndicatorBinding
from apps.rounds.models import CollectionRound, ReportingPeriod, RoundInstrument
from apps.selfassessments.operator_web import page
from .dashboard import approved, authorize, csv_cell
from .review import review_summary
from .types import CalculationInputError
from apps.catalog.indicator_alignment import indicator_title

STATUSES = {
    'available': 'มีค่าผลรับรอง / Approved values available',
    'restricted': 'มีผลรับรอง แต่ซ่อนค่า / Approved, values restricted',
    'unavailable': 'มีชุดผล แต่ยังไม่มีค่า / Result exists, value unavailable',
    'invalid': 'ชุดผลตรวจสอบไม่ผ่าน / Result validation failed',
    'pending': 'ยังไม่มีผลรับรอง / No approved result',
    'unconfigured': 'ยังไม่ได้ผูกแบบฟอร์มในช่วงนี้ / No form configured in this period',
    'missing_catalog': 'ยังไม่มีรหัสในคลัง / Missing from catalog',
}


def audit_quality(user, scope, period, data_kind=None):
    authorize(user, scope)
    kinds=sorted(set(CollectionRound.objects.filter(scope=scope,period=period).values_list('data_kind',flat=True))) if period else []
    if data_kind not in {'real','synthetic'}:data_kind=kinds[0] if len(kinds)==1 else 'real'
    reference = json.loads((settings.BASE_DIR / 'catalog/indicator_reference.json').read_text(encoding='utf-8'))
    if period:
        from apps.catalog.indicator_alignment import by_code
        allowed_forms={'F01'} if period.calendar.calendar_type=='academic' else {'F02','F03','F04','F05','F06'}
        reference['indicators']=[i for i in reference['indicators'] if by_code().get(i['code'],{}).get('form') in allowed_forms]
    indicators = {r.code: r for r in Indicator.objects.filter(scope=scope)}
    configured = set()
    forms = {}
    if period:
        versions = RoundInstrument.objects.filter(collection_round__scope=scope,
            collection_round__period=period,collection_round__data_kind=data_kind).values_list('instrument_version_id', flat=True)
        for binding in IndicatorBinding.objects.filter(version_id__in=versions, indicator__scope=scope).select_related('indicator','version__instrument'):
            configured.add(binding.indicator.code)
            forms.setdefault(binding.indicator.code, set()).add(binding.version.instrument.code)
    outcomes, failures, methods = {}, set(), {}
    valid_sets = invalid_sets = 0
    latest = None
    decisions = approved(scope).filter(review__run__collection_round__period=period,review__run__collection_round__data_kind=data_kind) if period else approved(scope).none()
    for decision in decisions:
        run = decision.review.run
        try:
            packet = review_summary(user, run_id=run.pk)
        except (ValidationError, ObjectDoesNotExist, CalculationInputError):
            invalid_sets += 1
            # Metadata from the pinned form, never from a corrupt result payload.
            failures.update(run.stored_source.round_instrument.instrument_version.bindings.values_list('indicator__code',flat=True))
            continue
        valid_sets += 1
        latest = max(latest, decision.created_at) if latest else decision.created_at
        for row in packet['results']:
            kind = 'restricted' if row['status'] == 'suppressed' else 'available' if row.get('value') is not None else 'unavailable'
            outcomes.setdefault(row['indicator'], Counter())[kind] += 1
            methods.setdefault(row['indicator'],set()).add(row['method'])
    rows = []
    reference_codes = {r['code'] for r in reference['indicators']}
    for ref in reference['indicators']:
        code = ref['code']; item = indicators.get(code); counts = outcomes.get(code, Counter())
        status = ('invalid' if code in failures else 'available' if counts['available'] else
            'restricted' if counts['restricted'] else 'unavailable' if counts['unavailable'] else
            'missing_catalog' if item is None else 'pending' if code in configured else 'unconfigured')
        rows.append(dict(code=code, label=indicator_title(code,item.display_name_th if item else code),
            unit=item.unit if item else '', forms=sorted(forms.get(code, [])), pages=ref['pdf_pages'],
            status=status, status_label=STATUSES[status], visible=counts['available'],
            restricted=counts['restricted'], unavailable=counts['unavailable']))
    from apps.governance.f05_quantitative import MAP
    for row in rows:
        kinds=methods.get(row['code'],set())
        if kinds=={'anonymous_self_report'} and row['code'] in MAP:row['label']=MAP[row['code']][2]
        elif 'anonymous_self_report' in kinds and row['code'] in MAP:row['label'] += ' (มีหลายวิธีเก็บข้อมูล ต้องดูผลแยกวิธี)'
    now = timezone.now()
    overdue = CollectionRound.objects.filter(scope=scope, period=period, data_kind=data_kind, status='open',close_at__lte=now).count() if period else 0
    states = Counter(r['status'] for r in rows)
    data_kinds=[data_kind]
    return dict(data_kind=data_kind,data_kinds=data_kinds,rows=rows, reference=reference, checked_at=now, reference_count=len(rows),
        catalog_count=len(reference_codes & indicators.keys()), extra_codes=sorted(indicators.keys()-{i['code'] for i in json.loads((settings.BASE_DIR/'catalog/indicator_reference.json').read_text(encoding='utf-8'))['indicators']}),
        available_count=states['available'], restricted_count=states['restricted'],
        pending_count=sum(states[s] for s in ('pending','unconfigured','missing_catalog','unavailable')),
        valid_sets=valid_sets, invalid_sets=invalid_sets, latest_approved=latest, overdue=overdue)


@page(['GET'])
def overview(request, scope, export=False):
    authorize(request.user, scope)
    periods = ReportingPeriod.objects.filter(calendar__scope=scope, approved=True,collection_rounds__isnull=False).distinct().order_by('-start_date','pk')
    try:
        period = periods.filter(pk=UUID(request.GET['period'])).first() if request.GET.get('period') else periods.first()
    except (ValueError, TypeError):
        period = None
    report = audit_quality(request.user, scope, period,request.GET.get('kind'))
    query = request.GET.get('q','').strip()[:100]
    status = request.GET.get('status','')
    rows = [r for r in report['rows'] if (not status or r['status']==status) and
            (not query or query.casefold() in (r['code']+' '+r['label']).casefold())]
    if export:
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="nexora-data-quality.csv"'
        response.write('\ufeff'); writer = csv.writer(response)
        writer.writerow(['data_kinds','period','indicator','label','status','visible_entries','restricted_entries','unavailable_entries','source_pdf_pages','checked_at'])
        for r in rows:
            writer.writerow([csv_cell(v) for v in [','.join(report['data_kinds']),period.code if period else '', r['code'],r['label'],r['status'],r['visible'],r['restricted'],r['unavailable'],','.join(map(str,r['pages'])),report['checked_at'].isoformat()]])
        return response
    return render(request, 'calculations/quality.html', dict(report, rows=rows, scope=scope,
        periods=periods, selected_period=period, query=query, selected_status=status,
        statuses=STATUSES.items(), filters=request.GET.urlencode()))
