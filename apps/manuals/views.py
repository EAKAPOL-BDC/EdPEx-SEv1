"""Read-only, versioned documentation. No questionnaire data is loaded here."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from django.templatetags.static import static

from apps.accounts.models import AccessScope
from apps.accounts.permissions import can_access


def source_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


@lru_cache(maxsize=4)
def _catalog(root):
    folder = Path(root) / 'docs/manuals'
    data = json.loads((folder / 'content/manuals.json').read_text(encoding='utf-8'))
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    return data, manifest


def catalog():
    return _catalog(str(settings.BASE_DIR))


def permitted(user, item):
    return item['access'] == 'public' or bool(user.is_authenticated and user.is_active)


def find_manual(slug):
    data, manifest = catalog()
    item = next((m for m in data['manuals'] if m['slug'] == slug), None)
    if item is None:
        raise Http404
    return item, manifest['manuals'].get(slug, {})


def authorized_links(user, slug):
    """Deep links remain scoped; reading a guide never grants an action."""
    routes = {
        'system-administrator': ('backoffice-home', ('role.manage',)),
        'form-manager': ('assessment-preview-list', ('catalog.read',)),
        'collection-officer': ('round-list', ('round.manage',)),
        'activity-officer': ('survey-list', ('round.manage',)),
        'calculation-operator': ('survey-list', ('calculation.run',)),
        'result-reviewer': ('insights-list', ('result.review', 'calculation.validate')),
        'executive-reader': ('visualization-home', ('result.review', 'calculation.validate')),
        'audit-reader': ('backoffice-audit', ('audit.read',)),
    }
    if not user.is_authenticated or slug not in routes:
        return []
    route, actions = routes[slug]
    links = []
    for scope in AccessScope.objects.filter(active=True).order_by('name', 'pk'):
        if all(can_access(user, action, scope) for action in actions):
            links.append({'label': scope.name, 'url': reverse(route, args=[scope.pk])})
    return links


@require_safe
@never_cache
def index(request):
    data, manifest = catalog()
    query = request.GET.get('q', '').strip()[:100]
    category = request.GET.get('category', '')
    items = []
    for item in data['manuals']:
        if category and item['category'] != category:
            continue
        if query and query.casefold() not in json.dumps(item, ensure_ascii=False).casefold():
            continue
        items.append(dict(item, available=permitted(request.user, item),
                          pages=manifest['manuals'].get(item['slug'], {}).get('pages')))
    return render(request, 'manuals/index.html', {'manuals': items, 'query': query,
        'category': category, 'total': len(data['manuals']), 'version': data['version']})


@require_safe
@never_cache
def detail(request, slug):
    item, record = find_manual(slug)
    if not permitted(request.user, item):
        return redirect_to_login(request.get_full_path())
    # Resolve individual files for manifest-based static storage, without
    # changing the cached canonical source used to verify PDF downloads.
    web_item = dict(item, sections=[dict(section, figures=[
        dict(figure, url=static('manuals/illustrations/'+figure['filename']))
        for figure in section.get('figures', [])]) for section in item['sections']])
    for index, section in enumerate(web_item['sections']):
        # Navigation belongs to the web copy, never the signed PDF source.
        for name, neighbor in [('previous', index - 1), ('next', index + 1)]:
            if 0 <= neighbor < len(item['sections']):
                target = item['sections'][neighbor]
                section[name] = {'id': target['id'], 'title': target['title']}
    return render(request, 'manuals/detail.html', {'manual': web_item, 'pdf': record,
        'work_links': authorized_links(request.user, slug)})


@require_safe
@never_cache
def download(request, slug):
    item, record = find_manual(slug)
    if not permitted(request.user, item):
        return redirect_to_login(request.get_full_path())
    filename = 'nexora-' + item['slug'] + '.pdf'
    path = settings.BASE_DIR / 'docs/manuals/pdf' / filename
    try:
        payload = path.read_bytes()
    except OSError:
        payload = b''
    if (not payload.startswith(b'%PDF-') or source_digest(item) != record.get('source_sha256')
            or hashlib.sha256(payload).hexdigest() != record.get('sha256')):
        return HttpResponse('คู่มือ PDF ยังไม่พร้อม กรุณาอ่านบนเว็บหรือติดต่อผู้ดูแล / PDF unavailable. Read the web guide or contact the administrator.', status=503)
    # Serve the bytes just verified; never open a user-supplied filesystem path.
    from io import BytesIO
    response = FileResponse(BytesIO(payload), content_type='application/pdf', as_attachment=True, filename=filename)
    response['X-Content-Type-Options'] = 'nosniff'
    return response

@require_safe
@never_cache
def current(request):
    return render(request,'manuals/current.html')
