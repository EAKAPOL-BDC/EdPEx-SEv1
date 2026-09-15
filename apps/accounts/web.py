"""Organization portal; every scope and mutation uses persisted permissions."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from .models import AccessScope, Membership, Role, RoleAssignment, ALLOWED_PERMISSIONS
from .permissions import can_access, require_permission
from .services import assign_role, revoke_role, add_member


class MemberForm(forms.Form):
    username = forms.CharField(label="ชื่อผู้ใช้ที่มีอยู่แล้ว", max_length=150)


class GrantForm(forms.Form):
    membership = forms.ModelChoiceField(label="สมาชิก", queryset=Membership.objects.none())
    role = forms.ModelChoiceField(label="บทบาท", queryset=Role.objects.none())
    active_until = forms.DateTimeField(label="สิ้นสุดสิทธิ์ (เวลาไทย เช่น 2027-09-30 17:00)", required=False)
    include_descendants = forms.BooleanField(label="รวมขอบเขตย่อย", required=False)

    def __init__(self, *args, scope, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['membership'].queryset = Membership.objects.filter(
            organization=scope.organization, is_active=True, user__is_active=True).select_related('user')
        self.fields['membership'].label_from_instance = lambda member: member.user.get_username()
        self.fields['role'].queryset = Role.objects.order_by('code')


def home(request):
    return render(request, 'portal/home.html')


@login_required
def workspace(request):
    candidates = AccessScope.objects.filter(
        organization__membership__user=request.user,
        organization__membership__is_active=True, active=True).select_related('organization').distinct()
    scopes = []
    for scope in candidates:
        actions = [a for a in sorted(ALLOWED_PERMISSIONS) if can_access(request.user, a, scope, owner=request.user)]
        if actions:
            scopes.append({'scope': scope, 'actions': actions, 'manage': 'role.manage' in actions})
    return render(request, 'portal/workspace.html', {'scopes': scopes})


@login_required
def members(request, scope_id):
    scope = get_object_or_404(AccessScope, pk=scope_id)
    require_permission(request.user, 'role.manage', scope)
    member_form = MemberForm(request.POST if request.method == 'POST' and request.POST.get('operation') == 'member' else None)
    grant_form = GrantForm(request.POST if request.method == 'POST' and request.POST.get('operation') == 'grant' else None, scope=scope)
    if request.method == 'POST':
        form = member_form if request.POST.get('operation') == 'member' else grant_form
        if form.is_valid():
            try:
                if request.POST.get('operation') == 'member':
                    add_member(actor=request.user, scope=scope, username=form.cleaned_data['username'])
                elif request.POST.get('operation') == 'grant':
                    assign_role(actor=request.user, scope=scope, **form.cleaned_data)
                else:
                    return redirect('portal-members', scope_id=scope.pk)
            except ValidationError as exc:
                form.add_error(None, '; '.join(exc.messages))
            else:
                messages.success(request, 'บันทึกเรียบร้อยแล้ว')
                return redirect('portal-members', scope_id=scope.pk)
    grants = RoleAssignment.objects.filter(scope=scope).select_related('membership__user', 'role').order_by('-created_at')
    return render(request, 'portal/members.html', {'scope': scope, 'member_form': member_form,
        'grant_form': grant_form, 'grants': grants})


@login_required
@require_POST
def revoke(request, scope_id, assignment_id):
    scope = get_object_or_404(AccessScope, pk=scope_id)
    require_permission(request.user, 'role.manage', scope)
    grant = get_object_or_404(RoleAssignment, pk=assignment_id, scope=scope)
    revoke_role(actor=request.user, assignment=grant)
    messages.success(request, 'เพิกถอนสิทธิ์แล้ว ประวัติเดิมยังคงอยู่')
    return redirect('portal-members', scope_id=scope.pk)
