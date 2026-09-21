"""Read-only catalog management views, scoped independently of staff flags."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Prefetch
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET
from apps.accounts.models import AccessScope
from apps.accounts.permissions import require_permission, can_access
from .models import InstrumentVersion, Question, IndicatorBinding
from .presentation import title_search_aliases


def authorized_scope(request, scope_id):
    scope = get_object_or_404(AccessScope.objects.select_related('organization'), pk=scope_id)
    require_permission(request.user, 'catalog.read', scope)
    return scope


@login_required
@require_GET
def catalog(request, scope_id):
    scope = authorized_scope(request, scope_id)
    query = request.GET.get('q', '').strip()[:200]
    code = request.GET.get('code', '')
    status = request.GET.get('status', '')
    from .current import visible_versions
    versions=visible_versions(scope,request.GET.get('versions','current')).select_related('instrument').order_by('instrument__code','-created_at','pk')
    if query:
        versions = versions.filter(Q(title_th__icontains=query) | Q(version__icontains=query)
                                   | Q(title_th__in=title_search_aliases(query)))
    if code:
        versions = versions.filter(instrument__code=code)
    if status:
        versions = versions.filter(status=status)
    # Summaries use all filtered versions in this scope, before pagination and
    # without the question join that would multiply version/status counts.
    summary = versions.aggregate(
        total=Count('pk'), forms=Count('instrument_id', distinct=True),
        published=Count('pk', filter=Q(status='published')),
        draft=Count('pk', filter=Q(status='draft')),
        retired=Count('pk', filter=Q(status='retired')),
    )
    summary['questions'] = Question.objects.filter(version__in=versions).count()
    status_breakdown = [
        {'key': key, 'status': key, 'count': summary[key],
         'width': format(100 * summary[key] / summary['total'], '.6f') if summary['total'] else '0'}
        for key in ('published', 'draft', 'retired')
    ]
    versions = versions.annotate(question_count=Count('questions')).order_by('instrument__code', '-created_at', 'pk')
    page = Paginator(versions, 12).get_page(request.GET.get('page'))
    filters = request.GET.copy()
    filters.pop('page', None)
    return render(request, 'portal/catalog.html', {'scope': scope, 'page': page,
        'query': query, 'selected_code': code, 'selected_status': status,
        'selected_status_label': {
            'draft': 'ฉบับร่าง / Draft', 'published': 'เผยแพร่แล้ว / Published',
            'retired': 'ยุติการใช้งาน / Retired',
        }.get(status, 'ไม่พบสถานะนี้ / Unknown status'),
        'can_prepare':can_access(request.user,'catalog.edit',scope),'summary': summary, 'status_breakdown': status_breakdown,
        'has_filters': bool(query or code or status),
        'codes': [f'F0{i}' for i in range(1, 7)], 'filters': filters.urlencode()})


@login_required
@require_GET
def version_detail(request, scope_id, version_id):
    scope = authorized_scope(request, scope_id)
    version = get_object_or_404(InstrumentVersion.objects.select_related('instrument'),
        pk=version_id, instrument__scope=scope)
    # Read only the selected version's bindings in the authorized scope.
    bindings = IndicatorBinding.objects.filter(version=version, indicator__scope=scope).select_related('indicator').order_by('indicator__code')
    questions = version.questions.prefetch_related('options', Prefetch('bindings', queryset=bindings, to_attr='display_bindings')).order_by('question_id')
    total_questions = questions.count()
    query = request.GET.get('q', '').strip()[:200]
    if query:
        linked_questions = bindings.filter(indicator__code__icontains=query).values('questions')
        questions = questions.filter(Q(question_id__icontains=query) | Q(text_th__icontains=query)
                                     | Q(pk__in=linked_questions)).distinct()
    return render(request, 'portal/catalog_detail.html', {'scope': scope,
        'version': version, 'questions': questions, 'query': query, 'total_questions': total_questions,
        'can_edit': can_access(request.user, 'catalog.edit', scope),
        'can_publish': can_access(request.user, 'catalog.publish', scope),
        'can_prepare_wording': version.instrument.code in {'F01','F02','F03','F04','F06'},
        'editable': version.status == 'draft' and not version.translation_bundles.exclude(status='draft').exists(),
        'bundles': version.translation_bundles.order_by('-created_at')})
