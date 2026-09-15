"""Aggregate result review only. No F06 respondent ever waits for approval."""
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.permissions import require_permission
from apps.rounds.models import CollectionRound
from .codec import digest
from .models import CalculationRun, ResultDecision, ResultReviewRequest, StoredSourceSelection
from .services import IdempotencyConflict, _audit, validate_run


def _lock_run(run_id):
    run = CalculationRun.objects.select_related('collection_round__scope').get(pk=run_id)
    CollectionRound.objects.select_for_update().get(pk=run.collection_round_id)
    return run


def _reviewable(actor, run):
    validate_run(actor, run_id=run.pk)
    selection = StoredSourceSelection.objects.select_related('round_instrument__collection_round__population_snapshot',
        'round_instrument__instrument_version__instrument').get(run=run)
    from apps.selfassessments.services import stored_series
    from .catalog import Catalog
    from .services import _prepare_input
    # Reconstruct every expected series from the stored source at the original cutoff.
    # A typed/ad-hoc subset cannot become a complete instrument review.
    prepared = [_prepare_input(run.collection_round, item, run.cutoff, Catalog())
                for item in stored_series(selection.round_instrument, run.cutoff)]
    current = {p['series_key']: p['source_hash'] for p in prepared}
    sealed = dict(run.inputs.values_list('series_key', 'source_hash'))
    if current != sealed:
        raise ValidationError('Stored source coverage no longer matches this run. Create a new calculation.')
    return selection


@transaction.atomic
def request_review(actor, *, run_id, reason):
    run = _lock_run(run_id)
    require_permission(actor, 'result.submit', run.collection_round.scope)
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise ValidationError('Record why this result set is ready for review.')
    _reviewable(actor, run)
    token = digest({'run_id': str(run.pk), 'input_hash': run.input_hash, 'result_hash': run.result_hash})
    existing = ResultReviewRequest.objects.filter(run=run).first()
    if existing:
        if existing.requested_by_id != actor.pk or existing.reason != reason or existing.review_token != token:
            raise IdempotencyConflict('This run already has a review request.')
        decision = ResultDecision.objects.filter(review=existing).first()
        return {'run_id': str(run.pk), 'status': decision.outcome if decision else 'review', 'review_token': token, 'reused': True}
    request = ResultReviewRequest.objects.create(run=run, requested_by=actor, reason=reason, review_token=token)
    require_permission(actor, 'result.submit', run.collection_round.scope)
    _audit(actor, run.collection_round, 'result.review_requested', run.pk, checksum=token)
    return {'run_id': str(run.pk), 'status': 'review', 'review_token': request.review_token, 'reused': False}


def review_summary(actor, *, run_id):
    run = CalculationRun.objects.select_related('collection_round__scope').get(pk=run_id)
    require_permission(actor, 'result.review', run.collection_round.scope)
    request = ResultReviewRequest.objects.get(run=run)
    selection = _reviewable(actor, run)
    # Multiple generations can reveal a person's correction by differencing.
    # Keep all generation values restricted until a disclosure-reviewed release exists.
    repeated = StoredSourceSelection.objects.filter(round_instrument=selection.round_instrument).count() > 1
    results = []
    for result in run.results.select_related('source').order_by('series_key'):
        series = result.source.definition['series']
        counts = result.payload.get('counts', {})
        small = counts.get('valid_n', 0) < 5
        row = {'indicator': result.indicator_code, 'group': series['group_code'], 'dimension': series['dimension'],
               'method': series['method'], 'formula': series['spec'], 'unit': result.payload['unit']}
        if small or repeated:
            row['status'] = 'suppressed'
            row['reason'] = 'restricted_revision' if repeated else 'small_group'
        else:
            row.update({key: result.payload[key] for key in ('status', 'value', 'numerator', 'denominator')})
            row['quality_counts'] = counts
        results.append(row)
    decision = ResultDecision.objects.filter(review=request).first()
    require_permission(actor, 'result.review', run.collection_round.scope)
    return {'run_id': str(run.pk), 'status': decision.outcome if decision else 'review',
            'review_token': request.review_token, 'results': results, 'publication_status': 'unpublished',
            'review_scope': 'aggregate_formula_and_data_completeness', 'reason': request.reason}


@transaction.atomic
def decide_results(actor, *, run_id, outcome, reason, reviewed_token):
    run = _lock_run(run_id)
    for action in ('result.review', 'result.approve'):
        require_permission(actor, action, run.collection_round.scope)
    if outcome not in {'approved', 'returned'} or not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise ValidationError('Approve or return the result set with a reason.')
    review = ResultReviewRequest.objects.get(run=run)
    if reviewed_token != review.review_token:
        raise IdempotencyConflict('The reviewed token differs from the current immutable result set.')
    _reviewable(actor, run)
    existing = ResultDecision.objects.filter(review=review).first()
    if existing:
        if (existing.actor_id, existing.outcome, existing.reason, existing.reviewed_token) != (actor.pk, outcome, reason, reviewed_token):
            raise IdempotencyConflict('A final decision is retained; create a correction run.')
        return {'run_id': str(run.pk), 'status': outcome, 'publication_status': 'unpublished', 'reused': True}
    previous = ResultDecision.objects.filter(outcome='approved',
        review__run__stored_source__round_instrument_id=run.stored_source.round_instrument_id).order_by('-created_at', '-pk').first()
    if previous and (run.cutoff < previous.review.run.cutoff or run.created_at < previous.review.run.created_at):
        raise ValidationError('An older calculation cannot replace a newer approval.')
    decision = ResultDecision.objects.create(review=review, actor=actor, outcome=outcome, reason=reason,
        reviewed_token=reviewed_token, previous_approval=previous if outcome == 'approved' else None)
    for action in ('result.review', 'result.approve'):
        require_permission(actor, action, run.collection_round.scope)
    _audit(actor, run.collection_round, 'result.'+outcome, run.pk, checksum=reviewed_token,
           decision_id=str(decision.pk))
    return {'run_id': str(run.pk), 'status': outcome, 'publication_status': 'unpublished', 'reused': False}
