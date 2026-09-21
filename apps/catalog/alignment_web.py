"""Scoped indicator crosswalk. Contains catalog metadata, never survey responses."""
import csv
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET
from apps.accounts.permissions import require_permission
from apps.selfassessments.operator_web import page
from .indicator_alignment import reference, measurement_note, source_warning
from .models import InstrumentVersion, IndicatorBinding
from .web import authorized_scope
from .management_services import editor_token
from .management_web import selected, form_page, errors
from . import indicator_wording


def crosswalk(scope, versions):
    selected_by_form = {v.instrument.code:v for v in versions}
    bindings = {(b.version_id,b.indicator.code):b for b in IndicatorBinding.objects.filter(
        version__in=versions, indicator__scope=scope).select_related('indicator','formula').prefetch_related('questions')}
    rows = []
    for ref in reference()['indicators']:
        version = selected_by_form.get(ref['form'])
        binding = bindings.get((version.pk,ref['code'])) if version else None
        row = dict(ref, version=version, period='ปีการศึกษา / Academic year' if ref['form']=='F01' else 'ปีงบประมาณ / Fiscal year',
            questions=[], groups=[], formula_key='', formula_version='', formula_definition='', issues=[], warning=source_warning(ref['code']))
        row['unit_label'] = {'percent':'ร้อยละ / Percentage','score_5':'คะแนนเต็ม 5 / Score out of 5',
            'score_10':'คะแนนเต็ม 10 / Score out of 10','hours_per_person':'ชั่วโมงต่อคน / Hours per person'}.get(ref['unit'],ref['unit'])
        expected_questions = ref['baseline_questions']
        method = ''
        if version and ref['form']=='F05' and version.assessment_method=='self_report':
            method = 'anonymous_self_report'
            from apps.governance.f05_registry import for_version
            try:
                expected_questions = for_version(version.version).MAP[ref['code']][1]
            except ValidationError:
                row['issues'].append('รุ่น F05 นี้ยังไม่มีสูตรที่รองรับ / Unsupported F05 version')
        if not version:
            row['issues'].append('ยังไม่มีแบบฟอร์มในพื้นที่นี้ / No form in this scope')
        elif not binding:
            row['issues'].append('ยังไม่ผูกตัวชี้วัดในรุ่นนี้ / No binding in this version')
        else:
            row.update(questions=sorted(q.question_id for q in binding.questions.all()),
                groups=binding.group_rules.get('group_codes', []), formula_key=binding.formula.key,
                formula_version=binding.formula.version, formula_definition=binding.formula.definition_th)
            if set(row['questions']) != set(expected_questions):
                row['issues'].append('ชุดคำถามต่างจากโครงสร้างที่รองรับ / Question set differs from the supported schema')
            if set(row['groups']) != set(ref['baseline_groups']):
                row['issues'].append('กลุ่มที่ผูกต่างจากกลุ่มอ้างอิง / Bound groups differ from the reference')
            if binding.formula.key != ref['formula'] or binding.indicator.unit != ref['unit']:
                row['issues'].append('สูตรหรือหน่วยต่างจากข้อมูลอ้างอิง / Formula or unit differs from the reference')
        row['note'] = measurement_note(ref['code'], method=method, formula_version=version.version if version else '')
        rows.append(row)
    return rows


@login_required
@require_GET
def overview(request, scope_id, export=False):
    scope = authorized_scope(request, scope_id)
    versions = list(InstrumentVersion.objects.filter(instrument__scope=scope).select_related('instrument').order_by('instrument__code','-created_at','-pk'))
    selected_version = None
    if request.GET.get('version'):
        selected_version = next((v for v in versions if str(v.pk)==request.GET['version']), None)
        if selected_version is None:
            from django.http import Http404
            raise Http404
        chosen = [selected_version]
    else:
        latest = {}
        for version in versions:
            if version.source_metadata.get('synthetic_only') or version.status=='retired':continue
            latest.setdefault(version.instrument.code,version)
        chosen = list(latest.values())
    rows = crosswalk(scope,chosen)
    if selected_version:
        rows = [r for r in rows if r['form']==selected_version.instrument.code]
    query = request.GET.get('q','').strip()[:200]
    rows = [r for r in rows if not query or query.casefold() in ' '.join([r['code'],r['title_th'],r['form'],*r['questions'],*r['groups']]).casefold()]
    if export:
        from apps.calculations.dashboard import csv_cell
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition']='attachment; filename="nexora-indicator-crosswalk.csv"'
        response.write('\ufeff')
        writer=csv.writer(response)
        writer.writerow(['indicator','source_title','display_title','pdf_pages','form','period_type','selected_version','version_status','questions','groups','formula','formula_version','formula_definition','unit','interpretation','issues','source_warning','source_sha256'])
        for r in rows:
            v=r['version']
            writer.writerow([csv_cell(x) for x in [r['code'],r['original_title'],r['title_th'],','.join(map(str,r['pages'])),r['form'],r['period'],v.version if v else '',v.status if v else '',','.join(r['questions']),','.join(r['groups']),r['formula_key'],r['formula_version'],r['formula_definition'],r['unit'],r['note'],'; '.join(r['issues']),r['warning'],reference()['source']['sha256']]])
        return response
    return render(request,'portal/indicator_alignment.html',dict(scope=scope,rows=rows,versions=versions,
        selected_version=selected_version,query=query,filters=request.GET.urlencode(),reference=reference(),
        issue_count=sum(bool(r['issues']) for r in rows)))


@page(['GET','POST'])
def prepare_wording(request, scope, version_id):
    from django import forms
    from .management_forms import SnapshotForm
    class WordingForm(SnapshotForm):
        new_version = forms.CharField(label='ชื่อรุ่นใหม่ / New version name',max_length=40)
        confirm = forms.BooleanField(label='ยืนยันสร้างฉบับร่างเพื่อตรวจทานก่อนใช้กับรอบใหม่ / Create a draft for review before using it in a new round')
    require_permission(request.user,'catalog.edit',scope)
    version=selected(scope,version_id)
    if version.instrument.code not in indicator_wording.SUPPORTED:
        from django.http import Http404
        raise Http404
    form=WordingForm(request.POST if request.method=='POST' else None,initial={
        'snapshot':editor_token(request.user,version),'new_version':'1.2-readable'})
    if request.method=='POST' and form.is_valid():
        try:
            target=indicator_wording.prepare(request.user,version,form.cleaned_data['new_version'],form.cleaned_data['snapshot'])
        except (ValidationError,IntegrityError) as exc:
            errors(form,exc)
        else:
            messages.success(request,'สร้างฉบับร่างแล้ว ตรวจคำชี้แจงและภาษาไทย–อังกฤษก่อนเผยแพร่ ข้อความที่เคยแก้เองยังคงไว้ / Draft created. Review instructions and both languages before publication; custom question wording was preserved.')
            return redirect('portal-catalog-detail',scope_id=scope.pk,version_id=target.pk)
    return form_page(request,scope,version,form,'เตรียมฉบับอ่านง่าย / Prepare clearer wording',
        notice='สร้างสำเนารุ่นใหม่ เติมคำถามความพึงพอใจ/ไม่พึงพอใจให้ครบประโยค และเพิ่มคำชี้แจงตามตัวชี้วัด คงรหัส กลุ่ม คะแนน สูตร และรอบเดิมไว้ เนื้อหาฉบับใหม่ต้องตรวจทานทั้งสองภาษาก่อนเผยแพร่ หากใช้ข้อความต่างกันควรพิจารณาความเทียบเคียงก่อนเปรียบเทียบผลข้ามรุ่น / Creates a separate draft with fuller questions and instructions. Codes, groups, scores, formulas and existing rounds remain fixed. Review both languages; wording changes may affect comparisons across versions.')
