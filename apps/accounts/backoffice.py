"""Scoped administration hub; never exposes credentials or respondent payloads."""
from datetime import timedelta
from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from apps.accounts.models import AccessScope, RoleAssignment
from apps.accounts.permissions import require_permission, can_access
from apps.auditlog.services import record_event, events_for_scope
from apps.rounds.models import CollectionRound
from apps.selfassessments.operator_web import page


TOOL_ICONS = {'portal-members':'people','backoffice-settings':'settings','round-period-new':'calendar','round-list':'calendar','assessment-preview-list':'forms','portal-catalog':'library','activity-list':'people','backoffice-audit':'history'}


class SettingsForm(forms.Form):
    name = forms.CharField(label='ชื่อพื้นที่ทำงาน / Workspace name', max_length=255)
    revision = forms.CharField(widget=forms.HiddenInput)
    reason = forms.CharField(label='เหตุผลการแก้ไข / Reason', max_length=500)


@page(['GET'])
def overview(request, scope):
    require_permission(request.user, 'role.manage', scope)
    tools = []
    for permission, route, title, detail in [
        ('role.manage','portal-members','สมาชิกและสิทธิ์ / Members and access','เพิ่มบัญชี มอบบทบาท และเพิกถอนสิทธิ์ / Create accounts, assign and revoke access'),
        ('role.manage','backoffice-settings','ตั้งค่าพื้นที่ทำงาน / Workspace settings','แก้ไขชื่อที่แสดง พร้อมบันทึกเหตุผล / Change the workspace name with a recorded reason'),
        ('round.manage','annual-policy','ปีและความพร้อม / Years and readiness','ตรวจปี แบบ และช่วงเวลา / Check reporting years, forms and dates'),
        ('round.manage','f04-register','ทะเบียนผู้บริหาร F04 / F04 leadership register','บุคลากร หลักสูตร ตำแหน่ง และช่วงดำรงตำแหน่ง / People, programmes, positions and appointments'),
        ('calendar.manage','round-period-new','ช่วงรายงาน / Reporting periods','กำหนดปีและช่วงเวลารายงาน / Define reporting years and periods'),
        ('round.manage','round-list','ตั้งค่ารอบเพิ่มเติม / Advanced round settings','ตรวจข้อมูลตั้งต้น ปี และจำนวนผู้มีสิทธิ์ / Inspect collection metadata, reporting years and eligible populations'),
        ('catalog.read','assessment-preview-list','ดูแบบประเมิน / Preview assessments','ตรวจแบบฟอร์มและคำถามตามกลุ่มผู้ประเมิน / Inspect forms and questions by assessor group'),
        ('catalog.read','portal-catalog','คลังแบบฟอร์ม / Form library','จัดการรุ่น เนื้อหา และคำแปล / Manage versions, wording and translations'),
        ('round.manage','survey-list','รอบสาธารณะและติดตามผล / Public collections and results','ตั้งค่าเข้าร่วม เปิดรับ ปิดรอบ คำนวณ และตรวจผล / Configure entry, open, close, calculate and review results'),
        ('role.manage','workspace-refresh','ล้างและเตรียมข้อมูลทดสอบ / Refresh test data','ตรวจรายการล้างและประวัติการสร้างข้อมูลสมมุติ / Review cleanup instructions and simulation history'),
        ('catalog.read','group-register','ทะเบียนกลุ่ม / Respondent groups','ตรวจรหัสและความหมายของกลุ่ม / Check group codes and definitions'),
        ('role.manage','access-requests','คำขอใช้งานเจ้าหน้าที่ / Staff access requests','ตรวจและอนุมัติบัญชีเจ้าหน้าที่ ไม่ใช่ผู้ตอบสาธารณะ / Review staff accounts, not public respondents'),
        ('result.review','insights-list','สรุปผลที่รับรอง / Approved reports','รายงานและการส่งออกตามสิทธิ์ / Reports and authorised exports'),
        ('audit.read','backoffice-audit','ประวัติการดำเนินงาน / Activity history','ค้นหาประวัติในพื้นที่นี้ / Search this workspace history'),
    ]:
        if can_access(request.user, permission, scope):
            tools.append({'title':title,'detail':detail,'icon':TOOL_ICONS.get(route,'forms'),'url':reverse(route,kwargs={'scope_id':scope.pk})})
    if all(can_access(request.user, action, scope) for action in ('result.review','calculation.validate')):
        tools.append({'icon':'check','title':'คุณภาพและความพร้อมข้อมูล / Data quality and availability','detail':'ตรวจรหัสตัวชี้วัด ผลรับรอง และรายการที่ต้องติดตาม / Check indicator codes, approved results and follow-up items','url':reverse('quality-home',kwargs={'scope_id':scope.pk})})
    now = timezone.now()
    grants = RoleAssignment.objects.filter(scope=scope, revoked_at__isnull=True,
        membership__is_active=True, membership__user__is_active=True, active_from__lte=now,
        active_until__gt=now, active_until__lte=now+timedelta(days=30)).select_related('membership__user','role').order_by('active_until')
    rounds = CollectionRound.objects.filter(scope=scope).order_by('close_at','pk')
    queue = request.GET.get('queue','overdue')
    if queue not in {'overdue','draft','review','open'}: queue='overdue'
    rounds = rounds.filter(status='open',close_at__lte=now) if queue=='overdue' else rounds.filter(status=queue)
    may_round = can_access(request.user,'round.manage',scope)
    from .workflow import collection_links
    menu_actions={a for a in ('round.manage','population.manage','source.manage','calculation.run','result.submit','result.review') if can_access(request.user,a,scope)}
    page = Paginator(rounds if may_round else rounds.none(),15).get_page(request.GET.get('page'))
    for collection in page:
        bindings = list(collection.round_instruments.filter(survey_profile__isnull=False).select_related(
            'collection_round__scope','instrument_version__instrument','translation_bundle','survey_profile')[:2])
        collection.work_url = (collection_links(request.user,bindings[0],menu_actions).get('primary') if len(bindings)==1 else None)
        if not collection.work_url:
            collection.work_url=reverse('round-detail',args=[scope.pk,collection.pk])
    return render(request,'portal/backoffice.html',{'scope':scope,'tools':tools,'queue':queue,
        'rounds':page,
        'may_round':may_round,'grants':grants[:20],'grant_count':grants.count()})


@page(['GET','POST'])
def settings(request, scope):
    require_permission(request.user,'role.manage',scope)
    form = SettingsForm(request.POST if request.method=='POST' else None,
        initial={'name':scope.name,'revision':scope.updated_at.isoformat()})
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                current = AccessScope.objects.select_for_update().get(pk=scope.pk)
                require_permission(request.user,'role.manage',current)
                if current.updated_at.isoformat()!=form.cleaned_data['revision']:
                    raise ValidationError('ข้อมูลเปลี่ยนแล้ว กรุณาโหลดหน้าใหม่ก่อนแก้ไข')
                current.name=form.cleaned_data['name']
                current.save(update_fields=['name','updated_at'])
                record_event(current.organization,request.user,'workspace.settings_updated','AccessScope',current.pk,
                    reason=form.cleaned_data['reason'],metadata={'scope_id':str(current.pk),'changed_fields':['name']})
        except ValidationError as exc: form.add_error(None,exc)
        else:
            messages.success(request,'บันทึกการตั้งค่าแล้ว')
            return redirect('backoffice-home',scope_id=scope.pk)
    return render(request,'portal/backoffice_settings.html',{'scope':scope,'form':form},status=422 if form.errors else 200)


class AuditFilter(forms.Form):
    action=forms.CharField(label='การดำเนินการ / Action',required=False,max_length=100)
    start=forms.DateField(label='ตั้งแต่วันที่ / From date',required=False,widget=forms.DateInput(attrs={'type':'date'}))
    end=forms.DateField(label='ถึงวันที่ / To date',required=False,widget=forms.DateInput(attrs={'type':'date'}))
    def clean(self):
        data=super().clean()
        if data.get('start') and data.get('end') and data['start']>data['end']:
            raise ValidationError('วันเริ่มต้นต้องไม่เกินวันสิ้นสุด')
        return data


@page(['GET'])
def audit(request, scope):
    events=events_for_scope(request.user,scope).select_related('actor').order_by('-created_at','pk')
    form=AuditFilter(request.GET)
    if form.is_valid():
        data=form.cleaned_data
        if data.get('action'): events=events.filter(action__icontains=data['action'])
        if data.get('start'): events=events.filter(created_at__date__gte=data['start'])
        if data.get('end'): events=events.filter(created_at__date__lte=data['end'])
    else: events=events.none()
    params=request.GET.copy(); params.pop('page',None)
    return render(request,'portal/backoffice_audit.html',{'scope':scope,'form':form,
        'events':Paginator(events,25).get_page(request.GET.get('page')),'filters':params.urlencode()})
