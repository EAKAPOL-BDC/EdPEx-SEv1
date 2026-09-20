from django.shortcuts import render
from apps.accounts.permissions import require_permission
from apps.selfassessments.operator_web import page
from .models import WorkspaceRefresh

@page(['GET'])
def overview(request,scope):
    require_permission(request.user,'role.manage',scope)
    recent=WorkspaceRefresh.objects.filter(scope=scope).order_by('-created_at').first()
    return render(request,'governance/refresh.html',{'scope':scope,'latest_refresh':recent})
