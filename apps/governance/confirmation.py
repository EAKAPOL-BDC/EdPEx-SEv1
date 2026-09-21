"""Server-side review, expiring single-use confirmation, and atomic execution."""
from datetime import timedelta
from hashlib import sha256
import json
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin
from .models import Confirmation,Notification

EXCLUDE={'csrfmiddlewaretoken','operation_ticket','operation_ack','operation_edit'}

def digest(data):return sha256(json.dumps(data,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()

def context(request):
    # Detect intervening changes to the objects explicitly addressed by this URL.
    from django.apps import apps
    values=[]
    ids={str(v) for k,v in request.resolver_match.kwargs.items() if k.endswith('_id') or k=='pk'}
    for label in ['rounds.CollectionRound','rounds.PopulationSnapshot','catalog.InstrumentVersion','catalog.Question','catalog.TranslationBundle','catalog.ContentTranslation','rounds.RoundInstrument','governance.RegistrationPolicy','accounts.RoleAssignment','leadership.AnnualTarget','governance.AccessRequest']:
        try:model=apps.get_model(label)
        except LookupError:continue
        for pk in ids:
            try:rows=list(model.objects.filter(pk=pk).values())
            except (ValueError,TypeError,ValidationError):continue
            values.extend([(label,row) for row in rows])
    return digest(values)

def risk(route, action):
    if route == 'assessment-batch-new' or (route == 'survey-new' and getattr(settings, 'NEXORA_PUBLIC_ASSESSMENTS_ENABLED', False)):
        return 'สร้างรอบทดสอบสาธารณะใหม่แยกกลุ่มและหลักสูตร โดยไม่มีรายชื่อผู้ตอบ เก็บรอบเดิมไว้ ยังไม่เปิดรับหรือเผยแพร่ / Creates a new public test batch with separate groups and programmes, no respondent roster. Existing collections remain unchanged; saving does not open or publish.'
    if route == 'f04-plan':
        return 'เปิดรับและเผยแพร่ หรือปิดรับ ตามคำสั่งที่เลือกสำหรับผู้บริหารทุกตำแหน่งทั้ง ST1 และ ST2 ในปีนี้ หากรายการใดไม่พร้อมจะไม่เปลี่ยนรายการใด / Applies the selected action atomically to all leaders and both staff groups in this year.'
    if route == 'assessment-batch-manage':
        return 'คำสั่งนี้มีผลกับทุกกลุ่มและหลักสูตรในรอบหลัก หากกลุ่มใดผิดพลาด ระบบจะไม่เปลี่ยนรายการใด การปิดรอบจะหยุดรับคำตอบเพิ่ม / This action applies atomically to all groups and programmes in the batch. Closing stops further submissions.'
    if route=='f04-generate' and getattr(settings, 'NEXORA_PUBLIC_ASSESSMENTS_ENABLED', False):
        return 'สร้างรอบทดสอบ F04 ครบทุกผู้บริหารทุกตำแหน่งทั้ง ST1 และ ST2 โดยแยกจำนวนอ้างอิง ไม่ใช้รายชื่อผู้ตอบ รอบเดิมคงค่าเดิม ยังไม่เปิดหรือเผยแพร่อัตโนมัติ / Creates synthetic F04 collections for all leaders in both staff groups with separate reference counts and no respondent roster. Existing settings remain; no automatic opening or publication.'
    if route=='public-assessment-setup':return 'สร้างรอบทดสอบสาธารณะใหม่พร้อมจำนวนอ้างอิงรวม ไม่เก็บรายชื่อ ไม่เปิดรับหรือเผยแพร่อัตโนมัติ กรณี F04 สร้างครบทุกผู้บริหารในทะเบียนปีทั้ง ST1 และ ST2 / Creates new synthetic public collections with aggregate reference counts, without respondent rosters. Does not open or publish automatically. F04 includes all leaders in both ST1 and ST2.'
    if route=='public-assessment-manage':return 'เปลี่ยนสถานะการเปิดรับหรือเผยแพร่ในหน้าสาธารณะตามที่เลือก กรณี F04 มีผลกับทุกผู้บริหารทั้ง ST1 และ ST2 ในปีเดียวกัน การพักเผยแพร่ยุติช่วงตอบที่ยังไม่ส่ง การปิดหยุดรับคำตอบเพิ่ม / Changes collection or public visibility as selected. F04 affects all leaders in both staff groups for this year. Withdrawing invalidates unsubmitted sessions; closing stops new submissions.'
    if route=='participation-setup':return 'จะสร้างรอบข้อมูลสมมุติใหม่ จำนวนสิทธิ์และบริบทจะถูกตรึง ยังไม่เปิดรับคำตอบและไม่แจกคำเชิญ / Creates a new synthetic ready collection with pinned capacity and context. It does not open collection or issue invitations.'
    if route=='participation-manage':
        if action=='open_collection':return 'จะเปิดรอบทดสอบให้ผู้ถือรหัสเข้าตอบได้ตามช่วงเวลา ระบบตรวจความพร้อมอีกครั้งก่อนเปิด ไม่ออกคำเชิญอัตโนมัติ / Opens this test collection to invitation holders within its schedule. Readiness is checked again; no invitations are issued automatically.'
        if action=='close_collection':return 'จะปิดรอบและหยุดรับคำตอบเพิ่มทันที รวมถึงผู้ที่กำลังตอบ คำตอบและหลักฐานที่ออกแล้วคงเดิม รุ่นนี้ยังไม่รองรับเปิดรอบที่ปิดแล้วอีกครั้ง / Closes collection immediately, including further submissions from active respondents. Existing answers and proofs remain. Reopening a closed collection is not supported.'
        if action=='mint':return 'ชุดคำเชิญจะแสดงรหัสและ QR ครั้งเดียว โปรดพิมพ์หรือเก็บให้ปลอดภัย แจกแบบสุ่มโดยไม่บันทึกรายชื่อคู่กับรหัส / Codes and QR cards are shown once. Save them securely and distribute without a recipient map.'
        if action=='pause':return 'จะระงับช่องทางคำเชิญและยุติช่วงตอบที่เปิดอยู่ หลักฐานที่ออกแล้วคงเดิม / Pausing ends active invitation sessions; issued receipts remain unchanged.'
        if action=='resume':return 'ผู้ถือรหัสที่ยังไม่ใช้จะเข้าประเมินได้อีกครั้งเมื่อรอบเปิดรับ / Unused invitation holders can re-enter while collection is open.'
    if 'publish' in route:return 'การเผยแพร่ทำให้รุ่นนี้นำไปสร้างรอบได้ การแก้เนื้อหาภายหลังต้องสร้างรุ่นใหม่ / Publishing makes this version available for collection.'
    if 'revoke' in route or 'reject' in action:return 'ผู้ใช้หรือผู้ตอบอาจเข้าใช้งานไม่ได้หลังยืนยัน กรุณาตรวจบุคคลและขอบเขตสิทธิ์ / Access may be removed.'
    if 'member' in route or 'request' in route:return 'รายการนี้เกี่ยวข้องกับบัญชี รายชื่อ หรือสิทธิ์เข้าถึงข้อมูล ตรวจชื่อ อีเมล บทบาท และวันหมดอายุ / Check identity, email, roles and expiry.'
    if 'delete' in route or action=='remove':return 'ข้อมูลร่างที่เลือกจะถูกลบ และอาจต้องกรอกใหม่ / The selected draft will be removed.'
    if action in {'freeze','ready','open'} or 'freeze' in route:return 'หลังยืนยัน ข้อมูลบางส่วนจะถูกล็อกเพื่อรักษาประวัติ ตรวจปี ช่วงเวลา แบบฟอร์ม และรายชื่อผู้มีสิทธิ์ / Check year, schedule, form and eligible people before locking.'
    if action in {'close','closed'}:return 'ผู้ตอบจะส่งคำตอบเพิ่มไม่ได้หลังปิดรอบ / Closing stops further submissions.'
    if 'split' in route:return 'จะปิดรอบเดิมที่ยังเปิดและสร้างสองช่วงใหม่ คำตอบเดิมเก็บในประวัติ ไม่ย้ายคะแนนไปช่วงใหม่ / Splitting retains historical answers.'
    if 'result' in route or 'calculate' in route:return 'รายการนี้สร้างหรือเปลี่ยนสถานะชุดผลที่ใช้รายงาน ตรวจปี วิธีเก็บข้อมูลและความครบถ้วน / Check reporting context and completeness.'
    return 'ตรวจข้อมูลที่กรอกก่อนบันทึก การเปลี่ยนแปลงอาจมีผลต่อรอบ แบบฟอร์ม หรือผู้ใช้งานที่เกี่ยวข้อง / Review your entries and their effect before saving.'

class ConfirmationMiddleware(MiddlewareMixin):
    def process_view(self,request,view_func,args,kwargs):
        if not settings.PRODUCTION and not getattr(settings,'NEXORA_CONFIRM_IMPORTANT_ACTIONS',True):return
        if request.method=='POST' and request.path.startswith('/api/'):
            return HttpResponse('ดำเนินการจากหน้าจัดการเพื่อดูผลกระทบและยืนยันก่อนเปลี่ยนข้อมูล / Use the workspace review-and-confirm flow.',status=409)
        if request.method=='POST' and request.path.startswith('/admin/') and request.path not in {'/admin/login/','/admin/logout/'}:
            return HttpResponse('ใช้หน้าจัดการระบบในพื้นที่ทำงานเพื่อยืนยันการเปลี่ยนแปลง / Use the workspace management pages.',status=409)
        if request.method!='POST' or not request.path.startswith('/workspace/') or not request.user.is_authenticated:return
        if request.resolver_match.url_name=='notifications':return
        if request.POST.get('action')=='preview':return
        # Identified self-assessment routes are read-only under the new policy.
        if request.path.startswith('/workspace/self-assessments/'):return
        if request.FILES:return HttpResponse('กรุณาใช้แบบฟอร์มที่แสดงคำยืนยันก่อนส่งไฟล์ / Review the file upload first.',status=422)
        payload={k:request.POST.getlist(k) for k in request.POST if k not in EXCLUDE}
        fingerprint=digest(payload)
        current=context(request)
        ticket=request.POST.get('operation_ticket','')
        edit=request.resolver_match.url_name=='participation-setup' and request.POST.get('operation_edit')=='yes'
        if ticket and (request.POST.get('operation_ack')=='yes' or edit):
            with transaction.atomic():
                try:record=Confirmation.objects.select_for_update().get(pk=ticket,user=request.user,route=request.path)
                except (Confirmation.DoesNotExist,ValueError,ValidationError):return HttpResponse('คำยืนยันใช้ไม่ได้ กรุณาเปิดแบบฟอร์มใหม่ / Invalid confirmation.',status=409)
                current=context(request)
                if record.used_at or record.digest!=fingerprint or (not edit and (record.expires_at<=timezone.now() or record.context_digest!=current)):
                    return HttpResponse('ข้อมูลเปลี่ยน คำยืนยันหมดอายุ หรือใช้แล้ว กรุณาเปิดแบบฟอร์มใหม่ / Confirmation expired, changed or already used.',status=409)
                record.used_at=timezone.now();record.save(update_fields=['used_at'])
                request.POST=request.POST.copy()
                for k in ('operation_ticket','operation_ack','operation_edit'):request.POST.pop(k,None)
                if edit:
                    # Return the bound setup form only. Never execute the setup
                    # service or renew this ticket, even when acknowledgement is set.
                    request._confirmation_edit=True
                    return view_func(request,*args,**kwargs)
                response=view_func(request,*args,**kwargs)
                if response.status_code<400:
                    Notification.objects.create(user=request.user,text='รับรายการที่คุณยืนยันแล้ว โปรดตรวจผลการดำเนินการบนหน้าจอ / Your confirmed request was processed; check the outcome on the page.')
                return response
        sensitive=any(any(word in k.lower() for word in ['password','secret']) for k in payload)
        if sensitive:return HttpResponse('กรุณาเปิดหน้าจัดการบัญชีใหม่เพื่อใช้ขั้นตอนเปิดบัญชีที่ปลอดภัย / Use the secure account setup workflow.',status=422)
        record=Confirmation.objects.create(user=request.user,route=request.path,digest=fingerprint,context_digest=current,expires_at=timezone.now()+timedelta(minutes=10))
        fields=[(key,value) for key,values in payload.items() for value in values]
        from .review_presentation import presentation
        route=request.resolver_match.url_name or ''
        entries=display_entries(payload,route=route)
        return render(request,'governance/confirm.html',{'ticket':record.pk,'fields':fields,'entries':entries,
            'risk':risk(route,request.POST.get('action','')),'target_path':request.path,
            'review_expires_at':record.expires_at.isoformat(),**presentation(payload,route,entries)},status=200)


LABELS={'code':'ชื่อหรือรหัส','period':'ปีที่นำผลไปรายงาน','owner':'ผู้รับผิดชอบ','bundle':'รุ่นแบบฟอร์มและคำแปล','open_at':'เริ่มรับคำตอบ','due_at':'กำหนดส่ง','close_at':'ปิดรับคำตอบ','reason':'เหตุผล','full_name':'ชื่อและนามสกุล','email':'อีเมล','role':'บทบาท','active_until':'สิทธิ์สิ้นสุด','outcome':'ผลพิจารณา','action':'การดำเนินการ','mode':'วิธีเปิดบัญชี','group_code':'กลุ่มผู้ตอบ','group_codes':'กลุ่มผู้ตอบทั้งสองกลุ่ม / Both respondent groups','count_st1':'จำนวนอ้างอิง ST1 / ST1 reference count','count_st2':'จำนวนอ้างอิง ST2 / ST2 reference count','context_th':'บริบทของรอบ','context_en':'บริบทภาษาอังกฤษ','privacy_notice':'คำชี้แจงการใช้ข้อมูล','privacy_version':'รุ่นคำชี้แจง','contact':'ช่องทางติดต่อ','retention_days':'ระยะเก็บคำขอ (วัน)','enabled':'เปิดการสมัคร','affiliation':'หน่วยงานหรือความเกี่ยวข้อง','purpose':'วัตถุประสงค์','counting_unit':'หน่วยนับ','definition':'ผู้มีสิทธิ์ตอบ','source_title':'เอกสารรายชื่ออ้างอิง','source_location':'ที่เก็บเอกสารอ้างอิง','captured_at':'รายชื่อ ณ วันที่','count':'จำนวนผู้มีสิทธิ์','text':'ข้อความ','name':'ชื่อ','reporting_year_be':'ปี พ.ศ.','calendar_type':'ประเภทปี','start_date':'วันเริ่มต้น','last_date':'วันสุดท้าย'}
def display_entries(payload,*,route=''):
    hidden={'confirm','preview','reviewed_token','idempotency_key','expected_revision','return_to','context_checked','privacy_ack','ui_section','stamp','setup_stamp'}
    from apps.accounts.models import Role
    from apps.rounds.models import ReportingPeriod
    from apps.catalog.models import TranslationBundle
    from django.contrib.auth import get_user_model
    refs={'role':Role,'period':ReportingPeriod,'bundle':TranslationBundle,'owner':get_user_model()}
    result=[]
    labels=dict(LABELS)
    if route in {'assessment-batch-new', 'survey-new'} and 'group_codes' in payload:
        labels['group_codes'] = 'กลุ่มผู้ตอบที่เลือก / Selected respondent groups'
        from apps.participation.batches import contexts
        from apps.participation.public_catalog import GROUPS
        try:
            b = TranslationBundle.objects.select_related('instrument_version__instrument').get(pk=payload.get('bundle', [''])[0])
            groups = [g for g in b.instrument_version.group_codes if g in GROUPS]
            for i,g in enumerate(groups):
                labels['unit_'+str(i)] = g+' · หน่วยนับ / Counting unit'
                for j,(_,_,title) in enumerate(contexts(g,b.instrument_version.instrument.code)):
                    labels[f'count_{i}_{j}'] = g+' · '+title+' · จำนวนอ้างอิง / Reference count'
        except (TranslationBundle.DoesNotExist, ValueError, ValidationError):
            pass
    labels['collection_name']='รอบประเมิน / Collection'
    if route=='participation-setup':
        labels.update(source_title='หลักฐานจำนวนรวม / Aggregate evidence',source_reference='เลขอ้างอิงจำนวนรวม / Aggregate reference',
                      label_th='ชื่อกิจกรรมภาษาไทย / Thai activity label',label_en='ชื่อกิจกรรมภาษาอังกฤษ / English activity label',
                      expires_at='วันหมดอายุหลักฐาน / Receipt expiry',workload='ใช้ตรวจภาระงาน / Workload verification',prize='ใช้ตรวจสิทธิ์รางวัล / Reward verification')
    for key,values in payload.items():
        if key in hidden:continue
        for value in values:
            if not value:continue
            if key == 'action':
                value = {'launch':'เปิดรับและเผยแพร่ / Open and publish', 'open':'เปิดรับคำตอบ / Open collection', 'publish':'แสดงในหน้าสาธารณะ / Publish', 'withdraw':'ซ่อนจากหน้าสาธารณะ / Withdraw', 'close':'ปิดรับคำตอบ / Close collection'}.get(value, value)
            if key in refs:
                try:obj=refs[key].objects.get(pk=value);value=str(obj)
                except (refs[key].DoesNotExist,ValueError,TypeError,ValidationError):pass
            if route=='participation-setup' and key in {'workload','prize'}:value='เลือก / Selected' if value else 'ไม่เลือก / Not selected'
            result.append((labels.get(key,'ข้อมูล '+key),value))
    return result
