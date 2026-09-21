"""Only loaded by participation_demo settings; never in normal application URLs."""
from django.conf import settings
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.urls import path
from django.utils.html import format_html
from apps.surveys.web import public_page
from apps.participation.models import ReceiptPolicy
from .urls import urlpatterns as application_urls


@public_page
def demo(request):
    if settings.SETTINGS_MODULE != 'edpex.participation_demo' or request.META.get('REMOTE_ADDR') not in {'127.0.0.1','::1'}:
        return HttpResponse(status=404)
    if request.method == 'POST':
        from apps.participation import admission
        from apps.participation.qr import receipt_svg
        from django.urls import reverse
        from django.utils.safestring import mark_safe
        policy=ReceiptPolicy.objects.select_related('binding__collection_round').get(activity_code='f01-unlinked-demo',realm='test',enabled=True)
        r=policy.binding.collection_round
        if r.data_kind != 'synthetic':
            return HttpResponse(status=403)
        try:
            code=admission.mint(r.owner,policy.binding_id,1)[0]
        except admission.proofs.ReceiptError:
            return HttpResponse('คำเชิญทดสอบไม่พร้อมใช้ หรือแจกครบแล้ว / Demo invitation unavailable or capacity reached.',status=409)
        link=reverse('participation-entry')+'#'+code
        qr=receipt_svg(request.build_absolute_uri(link))
        return HttpResponse(format_html('''<!doctype html><html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NEXORA · คำเชิญทดสอบ</title><link rel="stylesheet" href="/static/participation/demo.css"></head><body><main><header><div class="logo"><img src="/static/portal/branding/nexora-logo.png" alt="NEXORA"></div><span>TEST INVITATION</span></header><section class="card"><p class="eyebrow">F01 · C1</p><h1>คำเชิญของท่านพร้อมแล้ว<br>Your invitation is ready</h1><p>กลุ่มนิสิตปริญญาตรี · ไม่ต้องสมัครสมาชิก<br>Undergraduate students · no account needed</p><p class="muted">หนึ่งรหัสใช้ส่งได้หนึ่งครั้ง ระบบไม่บันทึกว่ารหัสนี้แจกให้ใคร เก็บรหัสเป็นความลับ<br>One submission per code. No recipient mapping is stored. Keep this code private.</p><code class="invitation-code">{}</code><div class="invitation-qr">{}</div><div class="actions"><a class="open-invitation" href="{}" target="_blank" rel="noopener">เปิดแบบประเมินในแท็บใหม่ → / Open in a new tab</a></div><p class="muted">QR ในเครื่องนี้เปิดได้เฉพาะเครื่องที่รันระบบ / Local-computer test QR</p></section><footer>NEXORA · School of Education University of Phayao<br>© 2026 NEXORA · Mr.Eakapol Bodhichandra</footer></main></body></html>''',code,mark_safe(qr),link))
    return HttpResponse(format_html('''<!doctype html><html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NEXORA · F01 integration test</title><link rel="stylesheet" href="/static/participation/demo.css"></head><body><main><header><div class="logo"><img src="/static/portal/branding/nexora-logo.png" alt="NEXORA"></div><span>DEVELOPMENT · TEST ONLY</span></header><section class="card"><p class="eyebrow">F01 / CONNECTED ASSESSMENT</p><h1>ทดลองตอบแบบประเมิน<br>พร้อมเก็บหลักฐานการเข้าร่วม</h1><p>ฐานพัฒนาแยก ใช้ข้อมูลสมมุติเท่านั้น ไม่เชื่อมฐานใช้งานจริง</p><p class="muted">Development database only. Please use synthetic answers.<br>เลือกภาษาไทยหรืออังกฤษได้ในแบบประเมิน / Choose Thai or English in the form.</p><p class="muted">กดสร้างคำเชิญหนึ่งครั้งต่อการทดลอง จำนวนสิทธิ์มีจำกัด คำตอบที่ส่งแล้วแก้ไขไม่ได้<br>หากเคยส่งแล้ว โปรดใช้เมนูตรวจผลจากรหัสเดิม</p><div class="actions"><form method="post"><input type="hidden" name="csrfmiddlewaretoken" value="{}"><button type="submit">สร้างคำเชิญทดสอบ → / Create invitation</button></form><a href="/survey/participation/receipt/">ตรวจผลจากรหัสเดิม / Check receipt</a></div></section><footer><strong>NEXORA</strong> · เชื่อมโยงข้อมูล ขับเคลื่อนองค์กรสู่ความเป็นเลิศ<br>School of Education University of Phayao · Mr.Eakapol Bodhichandra<br>© 2026 NEXORA สงวนลิขสิทธิ์ / All rights reserved.</footer></main></body></html>''',get_token(request)))


@public_page
def invitation_preview(request):
    # Read-only inspection of synthetic totals; this does not grant a staff session.
    if (request.method!='GET' or settings.SETTINGS_MODULE!='edpex.participation_demo'
        or request.META.get('REMOTE_ADDR') not in {'127.0.0.1','::1'}):return HttpResponse(status=404)
    from django.shortcuts import get_object_or_404, render
    from django.urls import reverse
    from apps.participation.operator import context, secure
    policy=get_object_or_404(ReceiptPolicy,activity_code='f01-unlinked-demo',realm='test',binding__collection_round__data_kind='synthetic')
    ctx=context(policy.binding)
    ctx.update(preview=True,manage_url=reverse('participation-manage',args=[policy.binding.collection_round.scope_id,policy.binding_id]))
    return secure(render(request,'participation/operator.html',ctx))


urlpatterns=[path('demo/',demo,name='participation-demo'),path('demo/invitations/',invitation_preview,name='participation-demo-invitations')]+application_urls
