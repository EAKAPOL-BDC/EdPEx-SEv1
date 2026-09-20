"""Catalog previews contain definitions only, never respondent records or writes."""
from django import forms
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from apps.accounts.permissions import require_permission
from apps.selfassessments.operator_web import page
from .models import InstrumentVersion, source_hash
from .group_registry import registry, group_label, group_display
from .services import source_texts
from .assessment_ui import sections

ROLES=[('all','ทุกตำแหน่ง / All roles'),('DE','คณบดี / Dean'),('BO','กรรมการ / Board'),
       ('VD','รองคณบดี / Vice dean'),('AS','ผู้ช่วยคณบดี / Assistant dean'),('PC','ประธานหลักสูตร / Program chair')]

def group_labels():
    return {g['code']: group_label(g['code']) for g in registry()['groups']}


def labels(scope):
    from apps.rounds.models import RespondentGroup
    return {**dict(RespondentGroup.objects.filter(scope=scope).values_list('code','label')), **group_labels()}


@page(['GET'])
def overview(request, scope):
    require_permission(request.user,'catalog.read',scope)
    from .current import visible_versions
    versions=visible_versions(scope,request.GET.get('versions','current')).select_related('instrument').order_by('instrument__code','-created_at','pk')
    names=labels(scope)
    group=request.GET.get('group',''); code=request.GET.get('form','')
    all_versions=list(versions)
    groups=sorted({g for v in all_versions for g in v.group_codes})
    cards=[{'version':v,'groups':[{'code':g,'label':names.get(g,g)} for g in v.group_codes if not group or group==g]}
        for v in all_versions if (not code or v.instrument.code==code) and (not group or group in v.group_codes)]
    query=request.GET.copy();query.pop('page',None)
    return render(request,'portal/assessment_previews.html',dict(scope=scope,
        cards=Paginator(cards,12).get_page(request.GET.get('page')),group=group,form_code=code,
        groups=[(g,names.get(g,g)) for g in groups],group_count=len(groups),form_codes=[f'F0{i}' for i in range(1,7)],filters=query.urlencode()))


def build_preview(version, group, locale, role='all'):
    """Use only current approved translations; clearly mark source fallback."""
    original=source_texts(version)
    translated={}
    bundle=version.translation_bundles.filter(status__in=['published','retired']).order_by('-created_at').first()
    if bundle:
        for t in bundle.translations.filter(locale=locale,status='approved'):
            if t.content_key in original and t.reviewed_by_id and t.reviewed_at and t.source_hash==source_hash(original[t.content_key]):
                translated[t.content_key]=t.text
    missing=[]
    def wording(key,source):
        if key in translated:return translated[key]
        missing.append(key)
        return source
    code=version.instrument.code
    form=forms.Form(auto_id='preview_%s')
    notes={}
    questions=list(version.questions.filter(active=True).prefetch_related('options').order_by('question_id'))
    questions.sort(key=lambda q:(0 if q.question_id.split('-')[1].startswith('P') and not q.question_id.startswith('F04-PC') else 2 if q.question_id.split('-')[1].startswith('O') else 1,q.question_id))
    by_id={q.question_id:q for q in questions}
    for q in questions:
        if group not in q.group_codes or q.question_id.startswith('F06-P'):continue
        if q.audience!='respondent' and code!='F05':continue
        rule=q.visibility_rule
        if role!='all' and rule.get('op')=='context_role_and_information' and rule.get('role')!=role:continue
        opts=[(o.code,wording(q.question_id+'.option.'+o.code,o.label_th)) for o in sorted(q.options.all(),key=lambda o:(o.position,o.code))]
        if q.answer_type=='context_reference' or (code in ['F01','F02','F03','F04'] and q.question_id==code+'-P01'):
            field=forms.CharField(required=False,disabled=True,initial=group_display(group, language=locale) if code in ['F01','F02','F03','F04'] and q.question_id==code+'-P01' else ('Set by the collection round' if locale=='en' else 'กำหนดจากรอบเก็บข้อมูล'))
        elif q.answer_type=='multi_choice':
            field=forms.MultipleChoiceField(required=False,choices=opts,widget=forms.CheckboxSelectMultiple(attrs={'class':'answer-options'}))
        elif opts:
            choices=[('', 'ยังไม่ตอบ / Not answered'),*opts]
            if code in ['F01','F02','F03','F04','F06'] and (code=='F06' or '-K' not in q.question_id):
                if code=='F06' and q.question_id.startswith(('F06-M','F06-T')) and not any(o[0]=='NA' for o in opts):
                    choices.append(('not_applicable','ไม่เกี่ยวข้อง / Not applicable'))
                choices.append(('unable_to_assess','ยังประเมินไม่ได้ / Unable to assess'))
            if code=='F06':choices.append(('skipped','เลือกข้าม / Prefer to skip'))
            field=forms.ChoiceField(required=False,choices=choices,widget=forms.RadioSelect(attrs={'class':'answer-options'}))
        elif q.answer_type=='decimal':
            field=forms.DecimalField(required=False,min_value=0)
        elif q.answer_type=='date':
            field=forms.DateField(required=False,widget=forms.DateInput(attrs={'type':'date'}))
        else:
            field=forms.CharField(required=False,widget=forms.Textarea(attrs={'rows':3}))
        field.label=q.question_id+' · '+wording(q.question_id+'.text',q.text_th)
        form.fields[q.question_id]=field
        if rule.get('op')=='eq':
            parent=by_id.get(rule['question_id'])
            option=next((o for o in parent.options.all() if o.code==str(rule['value'])),None) if parent else None
            value=wording(parent.question_id+'.option.'+option.code,option.label_th) if option else str(rule['value'])
            notes[q.question_id]=(('Shown when ' if locale=='en' else 'แสดงเมื่อเลือกคำตอบในข้อ ')+rule['question_id']+' → '+value)
        elif rule.get('op')=='context_role_and_information':
            notes[q.question_id]=('แสดงตามตำแหน่งและข้อมูลที่ผู้ตอบมี / Depends on role and available information: '+dict(ROLES).get(rule['role'],rule['role']))
        elif q.audience!='respondent':
            notes[q.question_id]='ส่วนสำหรับผู้จัดเก็บหรือตรวจรับข้อมูล / Data collection or verification field'
        if q.answer_type in ['evidence_reference','review_metadata','date_time_range']:
            notes[q.question_id]=notes.get(q.question_id,'')+' · รายการอ้างอิงสำหรับตรวจโครงสร้าง F05 / F05 field reference'
    instructions=[wording(c.content_key,c.text_th) for c in version.contents.filter(active=True,audience='respondent',kind='instruction')]
    parts=sections(form,english=locale=='en',notes=notes)
    if code=='F06':
        for part in parts:
            for item in part['items']:
                q=by_id[item['id']]
                if not q.question_id.startswith(('F06-M','F06-T')):continue
                extras=[]
                for suffix,label in [('reason','เหตุผลกรณีไม่เกี่ยวข้อง (ไม่ระบุข้อมูลที่บอกตัวตน) / Reason when not applicable, without identifying details')]:
                    name=q.question_id+'__'+suffix
                    form.fields[name]=forms.CharField(label=label,required=False,widget=forms.Textarea(attrs={'rows':2}))
                    extras.append(form[name])
                item['extras']=extras
    return form,parts,instructions,bool(missing)


@page(['GET'])
def detail(request, scope, version_id, group_code):
    require_permission(request.user,'catalog.read',scope)
    version=get_object_or_404(InstrumentVersion.objects.select_related('instrument'),pk=version_id,instrument__scope=scope)
    if group_code not in version.group_codes:raise Http404
    locale='en' if request.GET.get('lang')=='en' else 'th'
    role=request.GET.get('role','all')
    if role not in dict(ROLES):raise Http404
    form,parts,instructions,fallback=build_preview(version,group_code,locale,role)
    return render(request,'portal/assessment_preview.html',dict(scope=scope,version=version,
        group_code=group_code,group_label=group_label(group_code, labels(scope).get(group_code, ''), language=locale),form=form,
        question_sections=parts,instructions=instructions,source_fallback=fallback,locale=locale,
        english=locale=='en',preview_mode=True,roles=ROLES,role=role))
