"""Same-origin session-authenticated endpoints; Django CSRF middleware stays enabled."""
from functools import wraps
import json
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.http import JsonResponse
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods
from apps.calculations.services import IdempotencyConflict
from apps.calculations.review import request_review, review_summary, decide_results
from .services import (assign_self_assessment, calculate_self_assessments,
                       list_own_assignments, read_own_assignment, save_revision)


def endpoint(methods):
    def decorate(func):
        @require_http_methods(methods)
        @wraps(func)
        def guarded(request, *args, **kwargs):
            if not request.user.is_authenticated:
                response = JsonResponse({'error': 'authentication_required'}, status=401)
            else:
                try:
                    response = JsonResponse(func(request, *args, **kwargs))
                except IdempotencyConflict:
                    response = JsonResponse({'error': 'revision_or_request_conflict'}, status=409)
                except PermissionDenied:
                    response = JsonResponse({'error': 'forbidden'}, status=403)
                except ObjectDoesNotExist:
                    response = JsonResponse({'error': 'not_found'}, status=404)
                except (ValidationError, ValueError, TypeError):
                    response = JsonResponse({'error': 'invalid_request'}, status=422)
            response['Cache-Control'] = 'private, no-store'
            return response
        return guarded
    return decorate


def body(request, fields):
    if request.content_type != 'application/json' or len(request.body) > 65536:
        raise ValidationError('Use a bounded JSON request.')
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValidationError('Duplicate JSON keys are not allowed.')
            result[key] = value
        return result
    result = json.loads(request.body, object_pairs_hook=unique_pairs,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    if not isinstance(result, dict) or set(result) != set(fields):
        raise ValidationError('Supply exactly the documented fields.')
    return result


@endpoint(['GET'])
def mine(request):
    return {'assignments': [{'id': str(a.pk), 'round': a.round_instrument.collection_round.code,
        'instrument_version': a.round_instrument.instrument_version.version, 'method': 'self_report'}
        for a in list_own_assignments(request.user)]}


@endpoint(['GET'])
def own_schema(request, assignment_id):
    return read_own_assignment(request.user, assignment_id=assignment_id,
                               locale='en' if request.LANGUAGE_CODE == 'en' else 'th')


def write(request, assignment_id, status):
    data = body(request, ['expected_revision', 'answers', 'idempotency_key'])
    return save_revision(request.user, assignment_id=assignment_id, status=status, **data)


@endpoint(['PUT'])
def draft(request, assignment_id):
    return write(request, assignment_id, 'draft')


@endpoint(['POST'])
def submit(request, assignment_id):
    return write(request, assignment_id, 'submitted')


@endpoint(['POST'])
def assign(request):
    data = body(request, ['round_instrument_id', 'member_id', 'user_id', 'duties', 'expected_levels', 'applicable_question_ids'])
    return {'assignment_id': assign_self_assessment(request.user, **data)}


@endpoint(['POST'])
def calculate(request, round_instrument_id):
    data = body(request, ['cutoff', 'idempotency_key', 'dry_run'])
    if not isinstance(data['cutoff'], str) or type(data['dry_run']) is not bool:
        raise ValidationError('Use a timestamp and boolean dry_run flag.')
    data['cutoff'] = parse_datetime(data['cutoff'])
    return calculate_self_assessments(request.user, round_instrument_id=round_instrument_id, **data)


@endpoint(['POST'])
def review_request(request, run_id):
    return request_review(request.user, run_id=run_id, **body(request, ['reason']))


@endpoint(['GET'])
def review_packet(request, run_id):
    return review_summary(request.user, run_id=run_id)


@endpoint(['POST'])
def review_decision(request, run_id):
    return decide_results(request.user, run_id=run_id, **body(request, ['outcome', 'reason', 'reviewed_token']))
