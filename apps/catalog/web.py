"""Read-only catalog management views, scoped independently of staff flags."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET
from apps.accounts.models import AccessScope
from apps.accounts.permissions import require_permission
from .models import InstrumentVersion


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
    versions = InstrumentVersion.objects.filter(instrument__scope=scope).select_related('instrument')
    if query:
        versions = versions.filter(Q(title_th__icontains=query) | Q(version__icontains=query))
    if code:
        versions = versions.filter(instrument__code=code)
    if status:
        versions = versions.filter(status=status)
    versions = versions.annotate(question_count=Count('questions')).order_by('instrument__code', '-created_at', 'pk')
    page = Paginator(versions, 12).get_page(request.GET.get('page'))
    filters = request.GET.copy()
    filters.pop('page', None)
    return render(request, 'portal/catalog.html', {'scope': scope, 'page': page,
        'query': query, 'selected_code': code, 'selected_status': status,
        'codes': [f'F0{i}' for i in range(1, 7)], 'filters': filters.urlencode()})


@login_required
@require_GET
def version_detail(request, scope_id, version_id):
    scope = authorized_scope(request, scope_id)
    version = get_object_or_404(InstrumentVersion.objects.select_related('instrument'),
        pk=version_id, instrument__scope=scope)
    questions = version.questions.prefetch_related('options').order_by('question_id')
    return render(request, 'portal/catalog_detail.html', {'scope': scope,
        'version': version, 'questions': questions})
