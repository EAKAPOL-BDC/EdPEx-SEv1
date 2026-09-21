from django.utils.translation import gettext_lazy as _
"""Organization portal; every scope and mutation uses persisted permissions."""
from django import forms
from django.conf import settings
from django.http import Http404
from django.views.decorators.cache import never_cache
from .workflow import collection_links, participation_enabled, SURVEY_ACTIONS
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from .models import AccessScope, Membership, Role, RoleAssignment, ALLOWED_PERMISSIONS
from .permissions import can_access, require_permission
from .services import assign_role, revoke_role, add_member


class MemberForm(forms.Form):
    username = forms.CharField(label=_("ชื่อผู้ใช้ที่มีอยู่แล้ว"), max_length=150)


class GrantForm(forms.Form):
    membership = forms.ModelChoiceField(label=_("สมาชิก"), queryset=Membership.objects.none())
    role = forms.ModelChoiceField(label=_("บทบาท"), queryset=Role.objects.none())
    active_until = forms.DateTimeField(
        label=_("วันและเวลาสิ้นสุดสิทธิ์"), required=False,
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={
            "type": "datetime-local", "step": "60", "aria-describedby": "expiry-help"}))
    include_descendants = forms.BooleanField(label=_("รวมขอบเขตย่อย"), required=False)

    def __init__(self, *args, scope, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['membership'].queryset = Membership.objects.filter(
            organization=scope.organization, is_active=True, user__is_active=True).select_related('user')
        self.fields['membership'].label_from_instance = lambda member: member.user.get_username()
        self.fields['role'].queryset = Role.objects.order_by('code')


def home(request):
    return render(request, 'portal/home.html', {'participation_enabled':participation_enabled(),
        'public_assessments_enabled':getattr(settings, 'NEXORA_PUBLIC_ASSESSMENTS_ENABLED', False)})


@login_required
@never_cache
def workspace(request):
    candidates = AccessScope.objects.filter(
        organization__membership__user=request.user,
        organization__membership__is_active=True, active=True).select_related('organization').distinct()
    scopes = []
    for scope in candidates:
        actions = [a for a in sorted(ALLOWED_PERMISSIONS) if can_access(request.user, a, scope, owner=request.user)]
        if actions:
            scopes.append({'scope': scope, 'actions': actions, 'manage': 'role.manage' in actions,
                'collection': bool(set(actions) & set(SURVEY_ACTIONS)),
                'insights': all(a in actions for a in ('result.review','calculation.validate'))})
    from apps.rounds.models import RoundInstrument
    from apps.selfassessments.services import list_own_assignments
    own = list_own_assignments(request.user)
    chosen = request.GET.get('scope', '')
    active_scope = next((item['scope'] for item in scopes if str(item['scope'].pk)==chosen), None)
    if chosen and active_scope is None:
        raise Http404
    if active_scope is None and len(scopes)==1:
        active_scope=scopes[0]['scope']
    visible_scopes = [item for item in scopes if active_scope is None or item['scope']==active_scope]
    collection_scopes = [item['scope'].pk for item in visible_scopes if item['collection']]
    rounds = RoundInstrument.objects.filter(collection_round__scope_id__in=collection_scopes,
        survey_profile__isnull=False).select_related(
            'collection_round__scope', 'instrument_version__instrument', 'translation_bundle', 'survey_profile').order_by('-collection_round__created_at', 'pk')
    recent = list(rounds[:8])
    action_map = {item['scope'].pk:item['actions'] for item in scopes}
    for selected in recent:
        selected.workflow = collection_links(request.user, selected, action_map[selected.collection_round.scope_id])
    return render(request, 'portal/workspace.html', {'scopes': scopes, 'scope': active_scope,
        'visible_scopes':visible_scopes, 'own_assignments': own,
        'participation_enabled':participation_enabled(),
        'public_assessments_enabled':getattr(settings, 'NEXORA_PUBLIC_ASSESSMENTS_ENABLED', False),
        'is_demo':settings.SETTINGS_MODULE in {'edpex.participation_demo','edpex.participation_lan'},
        'recent_rounds': recent, 'round_count': rounds.count(),
        'open_round_count': rounds.filter(collection_round__status='open').count()})


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
                form.add_error(None, _('ไม่สามารถบันทึกได้ กรุณาตรวจข้อมูลที่กรอก'))
            else:
                messages.success(request, _('บันทึกเรียบร้อยแล้ว'))
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
    messages.success(request, _('เพิกถอนสิทธิ์แล้ว ประวัติเดิมยังคงอยู่'))
    return redirect('portal-members', scope_id=scope.pk)


@require_POST
def language(request):
    from django.conf import settings
    from django.http import JsonResponse
    from .services import set_portal_language
    locale = request.POST.get('language')
    if locale not in {'th', 'en'}:
        return JsonResponse({'error': 'unsupported_language'}, status=400)
    if request.user.is_authenticated:
        set_portal_language(actor=request.user, locale=locale)
    response = JsonResponse({'language': locale})
    response.set_cookie(settings.LANGUAGE_COOKIE_NAME, locale, samesite='Lax', secure=request.is_secure())
    return response
