"""Authenticated operating documentation, with self-contained illustrated downloads."""
import base64
from copy import deepcopy
from pathlib import Path
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.views.decorators.http import require_safe
from .operations_guides import GUIDES
from apps.participation.public_catalog import GROUPS

def context(key, offline=False):
    if key not in GUIDES:
        raise Http404
    guide = deepcopy(GUIDES[key])
    base = Path(settings.BASE_DIR)/'apps/manuals/static'
    for chapter in guide['chapters']:
        relative = 'manuals/actual-20260919/'+chapter['image']
        path = base/relative
        if chapter['image'] and path.is_file():
            chapter['image_url'] = ('data:image/jpeg;base64,'+base64.b64encode(path.read_bytes()).decode()) if offline else static(relative)
    return {'guide':guide,'guide_key':key,'guides':GUIDES,
        'groups':[{'code':code,'th':row[0],'en':row[1]} for code,row in GROUPS.items()]}

@require_safe
@login_required
def guide(request, key):
    return render(request,'manuals/operations.html',context(key))

def export_html(key):
    data=context(key,offline=True)
    data['guide_css']=(Path(settings.BASE_DIR)/'apps/manuals/static/manuals/operations.css').read_text(encoding='utf-8')
    return render_to_string('manuals/operations_export.html',data)

@require_safe
@login_required
def download(request,key):
    response=HttpResponse(export_html(key),content_type='text/html; charset=utf-8')
    response['Content-Disposition']=f'attachment; filename="Nexora-{key}-guide-20260919.html"'
    response['Cache-Control']='no-store, private'
    response['X-Content-Type-Options']='nosniff'
    return response
