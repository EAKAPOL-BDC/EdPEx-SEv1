"""Read-only reference; listing a code never makes it eligible for an instrument."""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET
from .web import authorized_scope
from .group_registry import registry, group_info
from .models import InstrumentVersion


@login_required
@require_GET
def overview(request, scope_id):
    scope = authorized_scope(request, scope_id)
    query = request.GET.get('q', '').strip()[:200]
    category = request.GET.get('category', '')
    from .current import visible_versions
    versions=visible_versions(scope).select_related('instrument')
    usage = {}
    for version in versions:
        for code in version.group_codes:
            usage.setdefault(code, set()).add(version.instrument.code)
    rows = []
    for raw in registry()['groups']:
        row = group_info(raw['code'])
        text = ' '.join(str(v) for lang in ('th', 'en') for v in group_info(raw['code'], lang).values())
        if category and raw['category'] != category:
            continue
        if query and query.casefold() not in text.casefold():
            continue
        row['forms'] = sorted(usage.get(raw['code'], set()))
        rows.append(row)
    return render(request, 'portal/group_registry.html', dict(scope=scope, rows=rows,
        categories=registry()['categories'], selected_category=category, query=query,
        source=registry()['source']))
