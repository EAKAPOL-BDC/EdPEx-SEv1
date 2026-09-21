from apps.catalog.group_registry import group_display
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Count
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from urllib.parse import urlencode
from apps.accounts.permissions import can_access, require_permission
from apps.selfassessments.operator_web import page
from apps.catalog.management_web import errors
from apps.rounds.presentation import collection_listing
from .models import CollectionRound, PopulationMember
from .services import freeze_population, transition_round, delete_draft
from . import web_forms as forms, web_services as service


def round_in_scope(scope, round_id):
    return get_object_or_404(CollectionRound.objects.select_related('scope__organization', 'period', 'owner'), pk=round_id, scope=scope)


def form_page(request, scope, form, title, r=None, **extra):
    binding = r.round_instruments.select_related('instrument_version__instrument').first() if r else None
    return render(request, 'portal/manage_form.html', {'scope': scope, 'form': form, 'title': title,
                  'round': r, 'round_binding': binding, **extra}, status=422 if form.is_bound and form.errors else 200)


@page(['GET'])
def overview(request, scope):
    require_permission(request.user, 'round.manage', scope)
    rounds = CollectionRound.objects.filter(scope=scope).select_related('period').prefetch_related('round_instruments__instrument_version__instrument').order_by('-created_at')
    listing = collection_listing(request, rounds)
    return render(request, 'rounds/list.html', {'scope': scope, 'rounds': listing['page'], 'listing': listing,
        'can_period': can_access(request.user, 'calendar.manage', scope)})


@page(['GET', 'POST'])
def period_create(request, scope):
    require_permission(request.user, 'calendar.manage', scope)
    origin = request.GET.get('return_to', '')
    if origin not in {'survey', 'f06'}:
        origin = ''
    form = forms.PeriodForm(request.POST if request.method == 'POST' else None,
        initial={'reporting_year_be': timezone.localdate().year+543, 'return_to': origin})
    if request.method == 'POST' and form.is_valid():
        try:
            period = service.create_period(request.user, scope, form.cleaned_data)
        except (ValidationError, IntegrityError) as exc:
            errors(form, exc)
        else:
            messages.success(request, 'บันทึกและรับรองช่วงรายงานแล้ว / Reporting period saved and approved.')
            destination = {'survey': 'survey-new', 'f06': 'round-new'}.get(form.cleaned_data['return_to'], 'round-list')
            url = reverse(destination, kwargs={'scope_id': scope.pk})
            if destination != 'round-list':
                url += '?' + urlencode({'period': str(period.pk)})
            return redirect(url)
    return form_page(request, scope, form, 'เพิ่มช่วงรายงาน / Add reporting period',
        notice='วันแรกและวันสุดท้ายเป็นวันที่จริงตามปฏิทินของหน่วยงาน / Enter the actual first and last reporting dates.')


@page(['GET', 'POST'])
def edit(request, scope, round_id=None):
    if round_id is None:return redirect('survey-new',scope_id=scope.pk)
    require_permission(request.user, 'round.manage', scope)
    r = round_in_scope(scope, round_id) if round_id else None
    if r and service.survey_profile(r):
        return redirect('survey-collection',scope_id=scope.pk,selected_id=r.round_instruments.first().pk)
    binding = r.round_instruments.first() if r else None
    initial = {k: getattr(r, k) for k in ('code', 'period', 'owner', 'open_at', 'due_at', 'close_at', 'privacy_notice')} if r else {'owner': request.user, 'period': request.GET.get('period')}
    if binding:
        initial['bundle'] = binding.translation_bundle
    form = forms.RoundForm(request.POST if request.method == 'POST' else None, scope=scope, editing=bool(r), initial=initial, instrument_code=binding.instrument_version.instrument.code if binding else 'F06')
    if request.method == 'POST' and form.is_valid():
        try:
            saved = service.save_round(request.user, scope, form.cleaned_data, round_id)
        except (ValidationError, IntegrityError) as exc:
            errors(form, exc)
        else:
            messages.success(request, 'บันทึกรอบฉบับร่างแล้ว / Draft round saved.')
            return redirect('round-detail', scope_id=scope.pk, round_id=saved.pk)
    return form_page(request, scope, form, 'แก้ไขรอบ / Edit round' if r else 'สร้างรอบ F06 / Create F06 round', r,
        can_period=can_access(request.user, 'calendar.manage', scope), period_return_to='f06', notice='วันและเวลาตามเขตเวลา '+scope.organization.timezone+' / Times use '+scope.organization.timezone)


@page(['GET'])
def detail(request, scope, round_id):
    require_permission(request.user, 'round.manage', scope)
    r = round_in_scope(scope, round_id)
    from django.conf import settings
    if getattr(settings, 'NEXORA_PUBLIC_ASSESSMENTS_ENABLED', False) and service.survey_profile(r):
        return redirect('survey-collection', scope_id=scope.pk, selected_id=r.round_instruments.first().pk)
    snapshot = r.population_snapshots.order_by('-version').first()
    can_population = can_access(request.user, 'population.manage', scope)
    members = snapshot.members.select_related('group').order_by('group__code', 'eligible_unit_key') if snapshot and can_population else None
    counts = dict(members.values('group__code').annotate(n=Count('pk')).values_list('group__code', 'n')) if members is not None else {}
    binding = r.round_instruments.select_related('instrument_version').first()
    return render(request, 'rounds/detail.html', {'scope': scope, 'round': r, 'snapshot': snapshot,
        'survey': service.survey_profile(r), 'population_counts': list(snapshot.counts_by_group.items()) if snapshot else [], 'binding': binding, 'can_population': can_population, 'can_source': can_access(request.user, 'source.manage', scope),
        'members': Paginator(members, 30).get_page(request.GET.get('page')) if members is not None else None,
        'counts': counts, 'can_assign': can_population and can_access(request.user, 'selfassessment.assign', scope),
        'can_members': can_access(request.user, 'role.manage', scope)})


@page(['GET', 'POST'])
def population_edit(request, scope, round_id):
    require_permission(request.user, 'population.manage', scope)
    require_permission(request.user, 'source.manage', scope)
    r = round_in_scope(scope, round_id)
    snapshot = r.population_snapshots.select_related('source').order_by('-version').first()
    initial = {'captured_at': timezone.now()}
    if snapshot:
        initial.update(definition=snapshot.definition, captured_at=snapshot.captured_at,
            st1=snapshot.counts_by_group.get('ST1', 0), st2=snapshot.counts_by_group.get('ST2', 0),
            source_title=snapshot.source.title if snapshot.source else '', source_location=snapshot.source.location if snapshot.source else '')
    profile = service.survey_profile(r)
    from apps.surveys.forms import SurveyPopulationForm
    if profile and snapshot:
        initial['count'] = snapshot.counts_by_group.get(profile.group_code,0)
    form = (SurveyPopulationForm if profile else forms.PopulationForm)(request.POST if request.method == 'POST' else None, initial=initial)
    if snapshot:
        form.fields['reason'].required = True
    if request.method == 'POST' and form.is_valid():
        try:
            service.save_population(request.user, r, form.cleaned_data)
        except (ValidationError, IntegrityError) as exc:
            errors(form, exc)
        else:
            messages.success(request, 'บันทึกข้อมูลประชากรแล้ว เพิ่มรายชื่อให้ครบตามจำนวน / Population saved. Add the complete roster.')
            return redirect('round-detail', scope_id=scope.pk, round_id=r.pk)
    return form_page(request, scope, form, 'กำหนดผู้มีสิทธิ์ตอบ / Define eligible respondents', r)


@page(['GET', 'POST'])
def member_edit(request, scope, round_id, member_id=None):
    require_permission(request.user, 'population.manage', scope)
    r = round_in_scope(scope, round_id)
    member = get_object_or_404(PopulationMember, pk=member_id, snapshot__collection_round=r) if member_id else None
    form = forms.MemberForm(request.POST if request.method == 'POST' else None, scope=scope, editing=bool(member), groups=service.group_codes(r),
        initial={'eligible_unit_key': member.eligible_unit_key, 'group': member.group_id} if member else None)
    if request.method == 'POST' and form.is_valid():
        try:
            service.save_member(request.user, r, form.cleaned_data, member_id)
        except (ValidationError, IntegrityError) as exc:
            errors(form, exc)
        else:
            messages.success(request, 'บันทึกรายชื่อแล้ว / Roster entry saved.')
            if request.POST.get('save_another'):
                return redirect('round-member-new', scope_id=scope.pk, round_id=r.pk)
            return redirect('round-detail', scope_id=scope.pk, round_id=r.pk)
    return form_page(request, scope, form, 'แก้ไขผู้ตอบ / Edit respondent' if member else 'เพิ่มผู้ตอบ / Add respondent', r, save_another=not member)


@page(['GET', 'POST'])
def action(request, scope, round_id, action, member_id=None):
    r = round_in_scope(scope, round_id)
    titles = {'open':'เปิดรอบ / Open round', 'closed':'ปิดรอบ / Close round', 'freeze': 'ยืนยันรายชื่อครบและตรึงประชากร / Freeze complete roster', 'ready': 'เตรียมพร้อมเปิดรอบ / Mark round ready',
              'draft': 'กลับเป็นฉบับร่าง / Return to draft', 'delete': 'ลบรอบที่ยังไม่ใช้งาน / Delete unused round', 'remove': 'ลบผู้ตอบจากรายชื่อร่าง / Remove draft roster entry'}
    if action in {'open','closed'} and not r.round_instruments.filter(instrument_version__instrument__code='F05').exists():
        from django.http import Http404
        raise Http404
    if action not in titles:
        from django.http import Http404
        raise Http404
    require_permission(request.user, 'population.manage' if action in {'freeze', 'remove'} else 'round.manage', scope)
    member = get_object_or_404(PopulationMember, pk=member_id, snapshot__collection_round=r) if action == 'remove' else None
    snapshot = r.population_snapshots.order_by('-version').first()
    form = forms.ActionForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            if action == 'freeze':
                if snapshot is None:
                    raise ValidationError('ยังไม่มีประชากร / No population has been defined.')
                freeze_population(request.user, snapshot)
            elif action == 'remove':
                delete_draft(request.user, member, reason=form.cleaned_data['reason'])
            elif action == 'delete':
                service.remove_empty_draft_round(request.user, r, form.cleaned_data['reason'])
            else:
                transition_round(request.user, r, action, reason=form.cleaned_data['reason'])
        except (ValidationError, IntegrityError) as exc:
            errors(form, exc)
        else:
            messages.success(request, 'ดำเนินการเรียบร้อย / Action completed.')
            if action == 'delete':
                return redirect('round-list', scope_id=scope.pk)
            return redirect('round-detail', scope_id=scope.pk, round_id=r.pk)
    notice = member.eligible_unit_key if member else r.code
    if action == 'freeze' and snapshot:
        counts_text = '; '.join(f'{group_display(code)}: {count}' for code, count in snapshot.counts_by_group.items())
        notice += f" · รายชื่อ {snapshot.members.count()} หน่วย · จำนวนที่กำหนด {counts_text} · เมื่อตรึงแล้วแก้รายชื่อชุดนี้ไม่ได้"
    return form_page(request, scope, form, titles[action], r, notice=notice, destructive=action in {'delete', 'remove'})
