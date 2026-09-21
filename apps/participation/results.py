"""Scoped result-workflow metadata, without answers, scores or bearer proofs."""
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from apps.accounts.permissions import can_access
from apps.calculations.models import CalculationRun, ResultDecision
from apps.selfassessments.operator_web import page, require_any, RESULT_ACTIONS
from apps.surveys.models import AnonymousResponse
from apps.surveys.operator import selected_for
from . import admission, services
from .models import AccessPool, ReceiptPolicy
from .operator import secure

STATUS_LABELS = {
    'complete': 'คำนวณแล้ว · รอส่งตรวจ / Calculated · awaiting submission',
    'building': 'กำลังจัดทำ / Building',
    'review': 'รอผู้ตรวจรับรอง / Awaiting review',
    'approved': 'รับรองแล้ว / Approved',
    'returned': 'ส่งกลับให้ตรวจแก้ / Returned for correction',
    'superseded': 'มีชุดใหม่แทนแล้ว / Superseded',
}


@page(['GET'])
def overview(request, scope, selected_id):
    require_any(request.user, scope, ('round.manage', *RESULT_ACTIONS))
    try:
        admission.enabled()
    except services.ReceiptError:
        raise Http404 from None
    selected = selected_for(scope, selected_id)
    r = selected.collection_round
    if (r.data_kind != 'synthetic' or selected.instrument_version.instrument.code != 'F01'
        or selected.survey_profile.group_code != 'C1'
        or not AccessPool.objects.filter(binding=selected).exists()
        or not ReceiptPolicy.objects.filter(binding=selected, realm='test').exists()):
        raise Http404
    can_results = any(can_access(request.user, action, scope) for action in RESULT_ACTIONS)
    can_manage = all(can_access(request.user, action, scope) for action in ('round.manage','population.manage'))
    can_calculate = can_access(request.user, 'calculation.run', scope)
    can_reports = all(can_access(request.user, action, scope) for action in ('result.review','calculation.validate'))
    closed = r.status in {'closed','review','approved'}
    responses = AnonymousResponse.objects.filter(binding=selected)
    has_responses = responses.exists() if can_calculate or can_manage else None
    participation = None
    if can_manage:
        eligible = r.population_snapshot.counts_by_group.get('C1',0) if r.population_snapshot_id else 0
        submitted = responses.count()
        participation = {'eligible': eligible, 'submitted': submitted,
                         'percent': round(submitted*100/eligible,1) if eligible else None}
    runs = CalculationRun.objects.none()
    if can_results:
        runs = CalculationRun.objects.filter(stored_source__round_instrument=selected).defer('manifest').select_related(
            'review_request__decision').annotate(superseded=Exists(
                ResultDecision.objects.filter(previous_approval_id=OuterRef('review_request__decision__pk')))).order_by('-created_at','-pk')
    page_obj = Paginator(runs,12).get_page(request.GET.get('page'))
    rows = []
    for run in page_obj:
        review = getattr(run,'review_request',None)
        decision = getattr(review,'decision',None) if review else None
        state = 'superseded' if run.superseded else (decision.outcome if decision else ('review' if review else run.status))
        rows.append({'id':run.pk,'created_at':run.created_at,'cutoff':run.cutoff,'state':state,
                     'label':STATUS_LABELS.get(state,state),
                     'report_available':can_reports and state=='approved'})
    active_approved = (runs.filter(review_request__decision__outcome='approved',superseded=False).exists() if can_results else False)
    phase = 1 if not closed else (4 if active_approved else (3 if runs.exists() else 2))
    return secure(render(request,'participation/results.html',{
        'scope':scope,'selected':selected,'round':r,'closed':closed,'phase':phase,
        'can_manage':can_manage,'can_results':can_results,'can_calculate':can_calculate,
        'can_reports':can_reports,'has_responses':has_responses,'participation':participation,
        'page_obj':page_obj,'runs':rows,'checked_at':timezone.now(),
    }))
