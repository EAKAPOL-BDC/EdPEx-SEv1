"""Read-only list presentation. Call only after authorizing and scoping a queryset."""
from django.core.paginator import Paginator
from django.db.models import Count
from .models import CollectionRound


def collection_listing(request, queryset, *, bindings=False):
    prefix = 'collection_round__' if bindings else ''
    query = request.GET.get('q', '').strip()[:100]
    status = request.GET.get('status', '')
    year=request.GET.get('year','')
    kind=request.GET.get('kind','')
    if year.isdigit():queryset=queryset.filter(**{prefix+'period__reporting_year_be':int(year)})
    if kind in {'real','synthetic'}:queryset=queryset.filter(**{prefix+'data_kind':kind})
    choices = CollectionRound.Status.choices
    if status not in CollectionRound.Status.values:
        status = ''
    if query:
        queryset = queryset.filter(**{prefix+'code__icontains': query})
    if status:
        queryset = queryset.filter(**{prefix+'status': status})
    counts = dict(queryset.order_by().values_list(prefix+'status').annotate(total=Count('pk')))
    total = sum(counts.values())
    breakdown = [{'key': key, 'count': counts.get(key, 0),
                  'width': format(100*counts.get(key, 0)/total, '.6f') if total else '0'}
                 for key, _ in choices if counts.get(key, 0)]
    filters = request.GET.copy()
    for key in list(filters):
        if key not in {'q','status','year','kind'}:
            filters.pop(key)
    filters['q'], filters['status'] = query, status
    return {
        'page': Paginator(queryset.order_by('-'+prefix+'created_at', 'pk'), 20).get_page(request.GET.get('page')),
        'year':year,'data_kind':kind,'query': query, 'status': status, 'choices': choices, 'total': total,
        'breakdown': breakdown, 'filters': filters.urlencode(),
        'bindings': bindings,
    }
