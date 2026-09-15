"""Scoped staff workflow. Numeric disclosure belongs exclusively to review_summary."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.accounts.models import AccessScope
from apps.accounts.permissions import can_access, require_permission
from apps.calculations.models import CalculationRun
from apps.calculations.review import decide_results, request_review, review_summary
from apps.calculations.services import IdempotencyConflict
from apps.calculations.types import CalculationInputError
from apps.rounds.models import PopulationMember, RoundInstrument
from apps.rounds.services import transition_round
from .models import SelfAssessmentAssignment
from .operator_forms import AssignmentForm, CalculationForm, DecisionForm, ReasonForm, wording
from .services import assign_self_assessment, calculate_self_assessments

PREVIEW_SALT = 'f06-operator-calculation-v1'
PREVIEW_MAX_AGE = 1800
RESULT_ACTIONS = ('calculation.run', 'result.submit', 'result.review')
OPERATOR_ACTIONS = ('selfassessment.assign', 'round.manage', *RESULT_ACTIONS)


def page(methods):
    def decorate(view):
        @login_required
        @never_cache
        @require_http_methods(methods)
        @wraps(view)
        def wrapped(request, scope_id, **kwargs):
            scope = get_object_or_404(AccessScope.objects.select_related('organization'), pk=scope_id)
            with timezone.override(scope.organization.timezone):
                return view(request, scope, **kwargs)
        return wrapped
    return decorate


def allowed(user, scope, *actions):
    return all(can_access(user, action, scope) for action in actions)


def require_any(user, scope, actions):
    if not any(can_access(user, action, scope) for action in actions):
        raise PermissionDenied


def selected_in_scope(scope, selected_id):
    return get_object_or_404(RoundInstrument.objects.select_related('collection_round__scope',
        'collection_round__population_snapshot', 'instrument_version__instrument', 'translation_bundle'),
        pk=selected_id, collection_round__scope=scope, instrument_version__instrument__code='F06')


def message(request, th, en):
    return wording(request.LANGUAGE_CODE == 'en', th, en)


def failed_form(request, form, conflict=False):
    form.add_error(None, message(request,
        'ข้อมูลหรือสถานะเปลี่ยนแล้ว กรุณาเปิดหน้าใหม่เพื่อตรวจอีกครั้ง' if conflict else
        'บันทึกไม่ได้ กรุณาตรวจข้อมูล รุ่นแบบฟอร์ม และสถานะของรอบ',
        'The data or state changed. Reload and review again.' if conflict else
        'Unable to save. Check the fields, pinned form version and round status.'))
    return 409 if conflict else 422


def run_metadata(run):
    # Exclude source payloads, manifests, response counts and user identities.
    review = getattr(run, 'review_request', None)
    decision = getattr(review, 'decision', None) if review else None
    return {'id': run.pk, 'cutoff': run.cutoff, 'created_at': run.created_at,
        'status': decision.outcome if decision else ('review' if review else run.status),
        'superseded': bool(decision and decision.successors.exists())}


def runs_for(selected):
    return CalculationRun.objects.filter(stored_source__round_instrument=selected).defer(
        'manifest').select_related('review_request__decision').order_by('-created_at', '-pk')


@page(['GET'])
def overview(request, scope):
    require_any(request.user, scope, OPERATOR_ACTIONS)
    selections = RoundInstrument.objects.filter(collection_round__scope=scope,
        instrument_version__instrument__code='F06').select_related('collection_round', 'instrument_version').order_by(
        '-collection_round__created_at', 'pk')
    return render(request, 'selfassessments/operator_list.html', {'scope': scope,
        'selections': Paginator(selections, 20).get_page(request.GET.get('page'))})


@page(['GET', 'POST'])
def collection(request, scope, selected_id):
    require_any(request.user, scope, OPERATOR_ACTIONS)
    selected = selected_in_scope(scope, selected_id)
    round_ = selected.collection_round
    english = request.LANGUAGE_CODE == 'en'
    reason = ReasonForm(request.POST if request.method == 'POST' else None, english=english)
    code = 200
    if request.method == 'POST':
        require_permission(request.user, 'round.manage', scope)
        action = request.POST.get('action')
        if action not in {'open', 'closed'}:
            code = failed_form(request, reason)
        elif reason.is_valid():
            try:
                transition_round(request.user, round_, action, reason=reason.cleaned_data['reason'])
            except ValidationError:
                code = failed_form(request, reason)
            else:
                messages.success(request, message(request, 'เปลี่ยนสถานะทั้งรอบแล้ว', 'Round status updated.'))
                return redirect('operator-collection', scope_id=scope.pk, selected_id=selected.pk)
        else:
            code = 422
    can_results = any(can_access(request.user, a, scope) for a in RESULT_ACTIONS)
    history = Paginator(runs_for(selected), 20).get_page(request.GET.get('page')) if can_results else None
    return render(request, 'selfassessments/operator_collection.html', {'scope': scope, 'selected': selected,
        'reason_form': reason, 'can_assign': allowed(request.user, scope, 'selfassessment.assign', 'population.manage'),
        'can_manage': allowed(request.user, scope, 'round.manage'),
        'can_calculate': allowed(request.user, scope, 'calculation.run') and round_.status in {'closed', 'review', 'approved'},
        'history': history, 'runs': [run_metadata(run) for run in history] if history else []}, status=code)


@page(['GET'])
def roster(request, scope, selected_id):
    for action in ('selfassessment.assign', 'population.manage'):
        require_permission(request.user, action, scope)
    selected = selected_in_scope(scope, selected_id)
    assignments = SelfAssessmentAssignment.objects.filter(round_instrument=selected, member_id=OuterRef('pk'))
    members = PopulationMember.objects.filter(snapshot_id=selected.collection_round.population_snapshot_id,
        group__code__in=['ST1', 'ST2']).select_related('group').annotate(assigned=Exists(assignments)).order_by(
        'group__code', 'eligible_unit_key', 'pk')
    return render(request, 'selfassessments/operator_roster.html', {'scope': scope, 'selected': selected,
        'members': Paginator(members, 30).get_page(request.GET.get('page'))})


@page(['GET', 'POST'])
def assign(request, scope, selected_id, member_id):
    for action in ('selfassessment.assign', 'population.manage'):
        require_permission(request.user, action, scope)
    selected = selected_in_scope(scope, selected_id)
    member = get_object_or_404(PopulationMember.objects.select_related('group'), pk=member_id,
        snapshot_id=selected.collection_round.population_snapshot_id, group__code__in=['ST1', 'ST2'])
    if selected.collection_round.status != 'ready' or SelfAssessmentAssignment.objects.filter(
            round_instrument=selected, member=member).exists():
        messages.error(request, message(request, 'มอบหมายได้ครั้งเดียวก่อนเปิดรอบเท่านั้น',
                                       'Assignments can be created once, before opening collection.'))
        return redirect('operator-roster', scope_id=scope.pk, selected_id=selected.pk)
    try:
        form = AssignmentForm(request.POST if request.method == 'POST' else None, selected=selected,
            member=member, english=request.LANGUAGE_CODE == 'en')
    except ValidationError:
        messages.error(request, message(request, 'รุ่นแบบฟอร์มนี้ยังไม่รองรับการมอบหมาย',
                                       'This form version does not support assignment.'))
        return redirect('operator-roster', scope_id=scope.pk, selected_id=selected.pk)
    code = 200
    if request.method == 'POST':
        if form.is_valid():
            try:
                with transaction.atomic():
                    assign_self_assessment(request.user, round_instrument_id=selected.pk,
                        member_id=member.pk, **form.assignment_data())
                    require_permission(request.user, 'population.manage', scope)
            except ValidationError:
                code = failed_form(request, form)
            else:
                messages.success(request, message(request, 'บันทึกการมอบหมายและระดับที่คาดหวังแล้ว',
                    'Assignment and expected levels saved.'))
                return redirect('operator-roster', scope_id=scope.pk, selected_id=selected.pk)
        else:
            code = 422
    return render(request, 'selfassessments/operator_assign.html', {'scope': scope, 'selected': selected,
        'member': member, 'form': form}, status=code)


def preview_token(actor, scope, selected, data, receipt):
    return signing.dumps({'actor': actor.pk, 'scope': str(scope.pk), 'selected': str(selected.pk),
        'cutoff': data['cutoff'].isoformat(), 'idempotency_key': data['idempotency_key'],
        'input_hash': receipt['input_hash']}, salt=PREVIEW_SALT)


@transaction.atomic
def commit_preview(actor, scope, selected, token):
    require_permission(actor, 'calculation.run', scope)
    if not isinstance(token, str) or len(token) > 4096:
        raise ValidationError('Invalid preview.')
    try:
        data = signing.loads(token, salt=PREVIEW_SALT, max_age=PREVIEW_MAX_AGE)
    except signing.BadSignature as exc:
        raise ValidationError('Preview expired or changed.') from exc
    if (data['actor'], data['scope'], data['selected']) != (actor.pk, str(scope.pk), str(selected.pk)):
        raise PermissionDenied
    receipt = calculate_self_assessments(actor, round_instrument_id=selected.pk,
        cutoff=datetime.fromisoformat(data['cutoff']), idempotency_key=data['idempotency_key'])
    if receipt['input_hash'] != data['input_hash']:
        # Outer transaction rolls back run, source link, results and audit together.
        raise IdempotencyConflict('Source changed since preview.')
    return receipt


@page(['GET', 'POST'])
def calculate(request, scope, selected_id):
    require_permission(request.user, 'calculation.run', scope)
    selected = selected_in_scope(scope, selected_id)
    english = request.LANGUAGE_CODE == 'en'
    form = CalculationForm(request.POST if request.method == 'POST' else None,
                           english=english)
    code, preview, token = 200, None, None
    if request.method == 'POST':
        try:
            if request.POST.get('action') == 'commit':
                receipt = commit_preview(request.user, scope, selected, request.POST.get('preview_token'))
                messages.success(request, message(request, 'บันทึกชุดผลแล้ว', 'Result set saved.'))
                return redirect('operator-run', scope_id=scope.pk, run_id=receipt['run_id'])
            if request.POST.get('action') != 'preview':
                raise ValidationError('Choose an action.')
            if form.is_valid():
                preview = calculate_self_assessments(request.user, round_instrument_id=selected.pk,
                    **form.cleaned_data, dry_run=True)
                token = preview_token(request.user, scope, selected, form.cleaned_data, preview)
            else:
                code = 422
        except IdempotencyConflict:
            code = failed_form(request, form, conflict=True)
        except (ValidationError, CalculationInputError):
            code = failed_form(request, form)
    return render(request, 'selfassessments/operator_calculate.html', {'scope': scope, 'selected': selected,
        'form': form, 'preview': preview, 'preview_token': token,
        'ready': selected.collection_round.status in {'closed', 'review', 'approved'}}, status=code)


@page(['GET', 'POST'])
def result(request, scope, run_id):
    require_any(request.user, scope, RESULT_ACTIONS)
    run = get_object_or_404(CalculationRun.objects.select_related('review_request__decision',
        'stored_source__round_instrument__collection_round', 'stored_source__round_instrument__instrument_version'),
        pk=run_id, collection_round__scope=scope, stored_source__round_instrument__instrument_version__instrument__code='F06')
    review = getattr(run, 'review_request', None)
    decision = getattr(review, 'decision', None) if review else None
    can_submit = allowed(request.user, scope, 'result.submit', 'calculation.validate')
    can_review = allowed(request.user, scope, 'result.review', 'calculation.validate')
    can_decide = (review is not None and can_review and allowed(request.user, scope, 'result.approve')
                  and request.user.pk not in {run.created_by_id, review.requested_by_id})
    english = request.LANGUAGE_CODE == 'en'
    submit_form = ReasonForm(request.POST if request.method == 'POST' and request.POST.get('action') == 'submit' else None,
                             english=english)
    decision_form = DecisionForm(request.POST if request.method == 'POST' and request.POST.get('action') == 'decide' else None,
        english=english, initial={'reviewed_token': review.review_token if review else ''})
    code, packet, packet_error = 200, None, False
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'submit':
            if not can_submit:
                raise PermissionDenied
            form = submit_form
        elif action == 'decide':
            if not can_decide:
                raise PermissionDenied
            form = decision_form
        else:
            raise Http404
        if form.is_valid():
            try:
                if action == 'submit':
                    request_review(request.user, run_id=run.pk, **form.cleaned_data)
                else:
                    decide_results(request.user, run_id=run.pk, **form.cleaned_data)
            except IdempotencyConflict:
                code = failed_form(request, form, conflict=True)
            except (ValidationError, CalculationInputError, ObjectDoesNotExist):
                code = failed_form(request, form)
            else:
                messages.success(request, message(request, 'บันทึกการตรวจผลแล้ว', 'Review action saved.'))
                return redirect('operator-run', scope_id=scope.pk, run_id=run.pk)
        else:
            code = 422
    if can_review and review:
        try:
            packet = review_summary(request.user, run_id=run.pk)
            for row in packet['results']:
                if row['status'] != 'suppressed':
                    row['display_value'] = ('—' if row['value'] is None else
                        str(Decimal(row['value']).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)))
        except (ValidationError, CalculationInputError, ObjectDoesNotExist):
            packet_error = True
            code = 422
    history = None
    if (can_review or can_submit) and review:
        history = {'requested_at': review.created_at, 'reason': review.reason}
        if decision:
            history.update(decided_at=decision.created_at, decision_reason=decision.reason,
                previous_run_id=decision.previous_approval.review.run_id if decision.previous_approval_id else None)
    return render(request, 'selfassessments/operator_result.html', {'scope': scope,
        'selected': run.stored_source.round_instrument, 'run': run_metadata(run), 'history': history,
        'packet': packet, 'packet_error': packet_error, 'submit_form': submit_form, 'decision_form': decision_form,
        'can_submit': can_submit and review is None, 'can_decide': can_decide and decision is None and packet is not None,
        'independence_notice': can_review and review is not None and not can_decide and decision is None}, status=code)
