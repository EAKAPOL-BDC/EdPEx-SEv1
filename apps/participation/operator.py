"""Scoped management of configured, test-only unassigned invitation pools."""
from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core import signing
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import get_language
from django.utils.safestring import mark_safe
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from apps.selfassessments.operator_web import page
from apps.surveys.operator import selected_for
from apps.surveys.services import require_manager, SurveyConflict
from apps.surveys.models import Invitation
from apps.rounds.models import CollectionRound
from apps.accounts.permissions import can_access
from . import admission, services
from .models import AccessPool, AccessPass
from .qr import receipt_svg
from . import collection_control

SALT='nexora.unlinked.operator.batch.v1'


class LocalizedForm(forms.Form):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        from apps.accounts.templatetags.portal_ui import ui_wording
        for field in self.fields.values():
            if field.label:field.label=ui_wording(field.label,get_language())


class BatchForm(LocalizedForm):
    count=forms.IntegerField(min_value=1,max_value=100,label='จำนวนคำเชิญ / Invitation count',initial=1)
    stamp=forms.CharField(widget=forms.HiddenInput,max_length=1000)
    confirm=forms.BooleanField(label='แจกแบบสุ่มโดยไม่เก็บรายชื่อคู่กับรหัส และเก็บชุดรหัสนี้เป็นความลับ / Distribute randomly without recording recipients; keep codes private')


class PauseForm(LocalizedForm):
    confirm=forms.BooleanField(label='ยืนยันการเปลี่ยนสถานะช่องทางคำเชิญ / Confirm access change',widget=forms.CheckboxInput(attrs={'id':'pause-confirm'}))


class CollectionControlForm(LocalizedForm):
    stamp=forms.CharField(widget=forms.HiddenInput(attrs={'id':'control-stamp'}),max_length=1000)
    collection_name=forms.CharField(widget=forms.HiddenInput,max_length=255)
    reason=forms.CharField(max_length=500,label='เหตุผลที่ปิดรอบ / Reason for closing',widget=forms.Textarea(attrs={'rows':2,'id':'control-reason'}))
    confirm=forms.BooleanField(label='ตรวจข้อมูลและเข้าใจผลของการเปลี่ยนสถานะรอบแล้ว / I reviewed the details and understand the collection status change',widget=forms.CheckboxInput(attrs={'id':'control-confirm'}))

    def __init__(self,*args,closing=False,**kwargs):
        super().__init__(*args,**kwargs)
        if not closing:self.fields.pop('reason')
        else:
            from apps.accounts.templatetags.portal_ui import ui_wording
            self.fields['reason'].widget.attrs['placeholder']=ui_wording('เช่น สิ้นสุดระยะเวลาเก็บข้อมูลตามแผน / Example: The planned collection period has ended',get_language())
            self.fields['reason'].help_text=ui_wording('บันทึกเหตุผลเพื่อทบทวนการดำเนินงาน ไม่ต้องใส่ชื่อหรือข้อมูลผู้ตอบ / This reason is retained for operational review. Do not include respondent details.',get_language())


def snapshot(binding):
    pool=get_object_or_404(AccessPool,binding=binding)
    tally=AccessPass.objects.filter(binding=binding).aggregate(
        issued=Count('pk'),used=Count('pk',filter=Q(spent=True)),
        revoked_count=Count('pk',filter=Q(revoked=True,spent=False)),
        waiting=Count('pk',filter=Q(spent=False,revoked=False,expires_at__gt=timezone.now())))
    legacy=Invitation.objects.filter(binding=binding).count()
    tally['revoked']=tally.pop('revoked_count')
    tally.update(capacity=pool.capacity,legacy=legacy,remaining=max(0,pool.capacity-tally['issued']-legacy))
    tally['percent']=round(100*tally['used']/pool.capacity) if pool.capacity else 0
    return pool,tally


def context(binding):
    pool,tally=snapshot(binding)
    r=binding.collection_round
    label=({'draft':'Draft','ready':'Ready','open':'Open','closed':'Closed'}.get(r.status,r.status)
           if get_language()=='en' else r.get_status_display())
    ready=collection_control.readiness(binding,pool)
    return {'scope':r.scope,'selected':binding,'round':r,'pool':pool,'tally':tally,'readiness':ready,
            'round_status':label,
            'can_mint':pool.enabled and ready['receipt_ready'] and r.status in {'ready','open'} and r.close_at>timezone.now() and tally['remaining']>0}


def secure(response):
    response['Cache-Control']='no-store, private'
    response['Referrer-Policy']='same-origin'
    response['X-Robots-Tag']='noindex, nofollow'
    response['Content-Security-Policy']="default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    return response


@page(['GET','POST'])
@sensitive_post_parameters()
@sensitive_variables('codes','cards')
def manage(request,scope,selected_id):
    try:admission.enabled()
    except services.ReceiptError:raise Http404 from None
    binding=selected_for(scope,selected_id)
    require_manager(request.user,binding)
    pool=get_object_or_404(AccessPool,binding=binding)
    # A disabled pool remains manageable, but no other form or live policy does.
    if (binding.instrument_version.instrument.code!='F01' or binding.survey_profile.group_code!='C1'
        or not services.ReceiptPolicy.objects.filter(binding=binding,realm='test').exists()):raise Http404
    batch=BatchForm(request.POST if request.method=='POST' and request.POST.get('action')=='mint' else None)
    pause=PauseForm(request.POST if request.method=='POST' and request.POST.get('action') in {'pause','resume'} else None)
    control=CollectionControlForm(request.POST if request.method=='POST' and request.POST.get('action') in {'open_collection','close_collection'} else None,
                                  closing=binding.collection_round.status=='open',initial={'stamp':collection_control.stamp(request.user,binding),'collection_name':binding.collection_round.code})
    cards=[];error='';status=200
    if request.method=='POST':
        action=request.POST.get('action')
        try:
            if action in {'open_collection','close_collection'} and control.is_valid():
                collection_control.change(request.user,binding.pk,action,control.cleaned_data['stamp'],collection_name=control.cleaned_data['collection_name'],reason=control.cleaned_data.get('reason',''))
                from apps.accounts.templatetags.portal_ui import ui_wording
                message=('เปิดรอบแล้ว ผู้ถือรหัสคำเชิญเข้าตอบได้ตามช่วงเวลา / Collection opened. Invitation holders can respond within its schedule.'
                         if action=='open_collection' else 'ปิดรอบแล้ว ไม่รับคำตอบเพิ่ม คำตอบและหลักฐานเดิมยังอยู่ / Collection closed. Further submissions are blocked; existing answers and proofs are retained.')
                messages.success(request,ui_wording(message,get_language()))
                return redirect('participation-manage',scope_id=scope.pk,selected_id=binding.pk)
            elif action=='mint' and batch.is_valid():
                stamp=signing.loads(batch.cleaned_data['stamp'],salt=SALT,max_age=900)
                if stamp.get('actor')!=str(request.user.pk) or stamp.get('binding')!=str(binding.pk):
                    raise signing.BadSignature
                # Render before commit: template/QR failures must not consume quota.
                with transaction.atomic():
                    codes=admission.mint(request.user,binding.pk,batch.cleaned_data['count'],expected_total=stamp['total'])
                    for code in codes:
                        link=request.build_absolute_uri(reverse('participation-entry'))+'#'+code
                        cards.append({'code':code,'link':link,'qr':mark_safe(receipt_svg(link))})
                    ctx=context(binding);ctx.update(cards=cards,batch=None,pause=None)
                    return secure(render(request,'participation/operator.html',ctx))
            elif action in {'pause','resume'} and pause.is_valid():
                with transaction.atomic():
                    r=CollectionRound.objects.select_for_update().get(pk=binding.collection_round_id)
                    if r.status not in {'ready','open'} or r.close_at<=timezone.now():raise services.ReceiptError('round_unavailable')
                    admission.set_enabled(request.user,binding.pk,action=='resume')
                return redirect('participation-manage',scope_id=scope.pk,selected_id=binding.pk)
            else:status=422
        except (signing.BadSignature,KeyError,TypeError):
            error=('หน้าควบคุมรอบหมดอายุหรือสถานะเปลี่ยนไป กรุณาตรวจรายการใหม่ / Collection controls expired or changed. Review the current state.' if action in {'open_collection','close_collection'} else 'หน้านี้หมดอายุหรือเปลี่ยนไป กรุณาเปิดหน้าใหม่ก่อนออกชุดคำเชิญ / Page expired or changed. Reload before issuing a batch.');status=409
        except (services.ReceiptError,SurveyConflict) as exc:
            error=('สถานะหรือความพร้อมเปลี่ยนไป กรุณาตรวจรายการอีกครั้งก่อนเปิดหรือปิดรอบ / Status or readiness changed. Review the checks before opening or closing.' if action in {'open_collection','close_collection'} else
                   'สถานะหรือจำนวนสิทธิ์เปลี่ยนไป กรุณาตรวจยอดอีกครั้ง ชุดที่เคยออกแล้วจะไม่ออกซ้ำ / State or quota changed. Review totals. An earlier batch will not be issued again.')
            status=getattr(exc,'status',409)
        except ValidationError:
            error='ยังเปลี่ยนสถานะรอบไม่ได้ กรุณาตรวจรายการความพร้อมและเหตุผล / Unable to change collection status. Check readiness and the required reason.';status=422
    binding.collection_round.refresh_from_db()
    ctx=context(binding)
    ctx['can_setup']=(binding.collection_round.data_kind=='synthetic' and can_access(request.user,'source.manage',scope))
    stamp=signing.dumps({'actor':str(request.user.pk),'binding':str(binding.pk),'total':ctx['tally']['issued']+ctx['tally']['legacy']},salt=SALT)
    if not batch.is_bound:batch=BatchForm(initial={'stamp':stamp,'count':1})
    ctx.update(batch=batch,pause=pause,control=control,error=error,cards=cards)
    return secure(render(request,'participation/operator.html',ctx,status=status))
