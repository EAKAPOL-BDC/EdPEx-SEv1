"""Anonymous pages never use the staff login to identify the respondent."""
from functools import wraps
from urllib.parse import urlsplit
from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect,render
from django.utils.crypto import salted_hmac
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from apps.catalog.assessment_ui import sections
from . import services
from .forms import AccessForm,ResponseForm,posted_payload

COOKIE=getattr(settings, 'SURVEY_SESSION_COOKIE_NAME', 'nexora_survey_session')


def public_page(view):
    @wraps(view)
    @sensitive_post_parameters('__ALL__')
    @csrf_protect
    def wrapped(request,*args,**kwargs):
        if request.method not in {'GET','POST'}:
            return HttpResponse(status=405)
        try:
            host=urlsplit('//'+request.get_host()).hostname
            loopback = host in {'127.0.0.1','localhost','::1'} and request.META.get('REMOTE_ADDR') in {'127.0.0.1','::1'}
            test_http = host == 'testserver' and getattr(settings,'SURVEY_ALLOW_TEST_HTTP',False)
            from apps.participation.lan_preview import permits_http
            if not request.is_secure() and not (loopback or test_http or permits_http(request)):
                return HttpResponse('HTTPS required',status=400)
            response=view(request,*args,**kwargs)
        except services.SurveyConflict as exc:
            response=render(request,'surveys/problem.html',{'message':' '.join(exc.messages)},status=409)
        except Exception:
            # Never render DEBUG traceback (which could contain code/draft) on anonymous paths.
            response=render(request,'surveys/problem.html',{'message':'ยังดำเนินการไม่ได้ กรุณาลองใหม่ / Unable to continue. Please retry.'},status=503)
        response['Cache-Control']='no-store, private'
        # HTML form POSTs need their same-origin Origin for Django CSRF checks.
        # Suppress referrers to other origins; codes/answers remain out of URLs.
        response['Referrer-Policy']='same-origin'
        response['X-Robots-Tag']='noindex, nofollow'
        response['Content-Security-Policy']="default-src 'self'; style-src 'self'; img-src 'self'; script-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
        return response
    return wrapped


@public_page
def access(request):
    services.cleanup()
    form=AccessForm(request.POST if request.method=='POST' else None)
    if request.method=='POST':
        # Forwarded headers are intentionally ignored; configure trusted ingress separately.
        key=salted_hmac('survey-access',request.META.get('REMOTE_ADDR','unknown')).hexdigest()
        if not services.throttle(key):
            response=render(request,'surveys/problem.html',{'message':'ลองหลายครั้งแล้ว กรุณารอ 10 นาที / Too many attempts; wait 10 minutes.'},status=429)
            response['Retry-After']='600'
            return response
        if form.is_valid():
            secret=services.exchange(form.cleaned_data['code'])
            destination = 'survey-answer'
            if getattr(settings,'NEXORA_PARTICIPATION_ENABLED',False):
                from apps.participation.models import ReceiptPolicy
                session = services.read_session(secret)
                binding = session.invitation.binding
                if (binding.instrument_version.instrument.code == 'F01' and binding.survey_profile.group_code == 'C1'
                    and ReceiptPolicy.objects.filter(binding=binding,enabled=True,realm='test').exists()):
                    destination = 'participation-form'
            response=redirect(destination)
            response.set_cookie(COOKIE,secret,max_age=86400,httponly=True,secure=request.is_secure(),samesite='Strict',path='/survey/')
            return response
    return render(request,'surveys/access.html',{'form':form},status=422 if form.is_bound and form.errors else 200)


@public_page
def answer(request):
    if request.COOKIES.get(COOKIE,'').startswith('NXS1-'):
        return redirect('participation-form')
    session=services.read_session(request.COOKIES.get(COOKIE,''))
    profile=session.invitation.binding.survey_profile
    locale='en' if request.GET.get('lang')=='en' else 'th'
    draft={}
    form=ResponseForm(profile,draft,session.revision,locale)
    status=200
    if request.method=='POST':
        payload=posted_payload(profile,request.POST)
        form=ResponseForm(profile,payload,session.revision,locale,request.POST)
        action=request.POST.get('action')
        if form.is_valid() and action in {'draft','submit'}:
            try:
                revision=int(form.cleaned_data['revision'])
                if action=='submit':
                    if request.POST.get('confirm')!='on':
                        raise ValidationError('ตรวจคำตอบและเลือกยืนยันก่อนส่ง / Check your answers and confirm submission.')
                    receipt,completion=services.save(request.COOKIES[COOKIE],payload,revision,submit=True)
                    response=render(request,'surveys/receipt.html',{'receipt':receipt,'completion':completion})
                    response.delete_cookie(COOKIE,path='/survey/')
                    return response
                services.save(request.COOKIES[COOKIE],payload,revision)
                normalized,_=services.normalize(profile,payload)
                form=ResponseForm(profile,normalized,session.revision,locale)
                return render(request,'surveys/answer.html',{'form':form,'schema':form.schema,'locale':locale,'question_sections':sections(form,english=locale=='en'),'saved':True})
            except services.SurveyConflict:
                raise
            except ValidationError as exc:
                form.add_error(None,' '.join(exc.messages))
        status=422
    return render(request,'surveys/answer.html',{'form':form,'schema':form.schema,'locale':locale,'saved':request.GET.get('saved')=='1','question_sections':sections(form,english=locale=='en')},status=status)
