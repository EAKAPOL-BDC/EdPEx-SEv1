"""Bilingual field guidance. Examples are suggestions, never persisted defaults."""
GUIDANCE = {
    'code': (
        'ตั้งชื่อให้เจ้าหน้าที่ค้นหาและแยกรอบนี้จากรอบอื่นได้ ชื่อต้องไม่ซ้ำในพื้นที่เดียวกัน / Give staff a distinct name to find this collection. It must be unique in this workspace.',
        'ชื่อรอบใช้จัดการงาน การเปลี่ยนชื่อไม่ได้เปลี่ยนปีรายงานที่รับมาจากต้นแบบ / This is an administrative name. Renaming does not change the reporting period inherited from the template.',
        'ทดลอง F01 นิสิตปริญญาตรี ครั้งที่ 2 / F01 undergraduate trial 2'),
    'context_th': (
        'ระบุเรื่องและกลุ่มที่ต้องการให้ผู้ตอบนึกถึงขณะประเมิน / Describe the subject and group respondents should consider.',
        'บริบทที่ชัดช่วยให้ทุกคนประเมินเรื่องเดียวกัน ใช้ขอบเขตเดียวตลอดรอบ / A clear, shared context keeps responses about the same subject throughout the collection.',
        'ประสบการณ์การเรียนและการรับบริการของนิสิตปริญญาตรี วิทยาลัยการศึกษา / ประสบการณ์การเรียนและการรับบริการของนิสิตปริญญาตรี วิทยาลัยการศึกษา'),
    'context_en': (
        'เขียนความหมายเดียวกับบริบทภาษาไทย สำหรับผู้เลือกภาษาอังกฤษ / Match the Thai context in English for English-language respondents.',
        'ทั้งสองภาษาต้องใช้กลุ่มและขอบเขตเดียวกัน เพื่อให้คำตอบเปรียบเทียบกันได้ / Both languages must describe the same group and scope so responses remain comparable.',
        'Learning and service experiences of undergraduate students at the School of Education / Learning and service experiences of undergraduate students at the School of Education'),
    'open_at': (
        'เริ่มรับคำตอบได้ตั้งแต่เวลานี้ เมื่อเจ้าหน้าที่เปิดสถานะรอบแล้ว / Responses can start at this time once staff open the collection.',
        'การบันทึกวันเปิดไม่ได้เปิดรอบอัตโนมัติ หลังสร้างสำเร็จต้องตรวจและเปิดรอบแยกต่างหาก / Setting this date does not automatically open collection. Staff review and open it separately.',
        'วันเริ่มเก็บข้อมูล เวลา 09:00 / First collection day at 09:00'),
    'due_at': (
        'วันเป้าหมายที่ต้องการให้ตอบเสร็จ ระบบยังรับได้จนถึงเวลาปิด / The target deadline. Responses remain possible until closing.',
        'หากต้องการเผื่อเวลาหลังวันเป้าหมาย ให้กำหนดเวลาปิดช้ากว่ากำหนดส่ง / Set closing later than the due date to allow an additional response window.',
        '7 วันหลังเปิดรอบ เวลา 17:00 / Seven days after opening, at 17:00'),
    'close_at': (
        'เมื่อถึงเวลานี้จะส่งคำตอบเพิ่มไม่ได้ / No further submissions are accepted at or after this time.',
        'เวลา 00:00 คือเริ่มต้นวันนั้น หากต้องการรับตลอดวันที่ 8 ให้ปิดวันที่ 9 เวลา 00:00 / 00:00 is the start of the day. To accept all of day 8, close on day 9 at 00:00.',
        'หลังวันกำหนดส่ง 1 วัน หรือเวลาสิ้นสุดที่หน่วยงานกำหนด / One day after the due date, or your agreed closing time'),
    'count': (
        'จำนวนรหัสคำเชิญสูงสุดของรอบ แต่ละรหัสส่งได้หนึ่งครั้ง / Maximum invitation codes for this collection. Each code permits one submission.',
        'จำนวนจะถูกตรึงเมื่อสร้างรอบสำเร็จ รหัสที่สูญหายยังนับในโควตา และจำนวนรหัสไม่ยืนยันจำนวนคนที่ไม่ซ้ำ / Capacity is fixed after setup. Lost codes still consume quota; code counts do not establish unique people.',
        '5 สิทธิ์ สำหรับทดลองระบบ / 5 codes for a system trial'),
    'source_title': (
        'บอกว่าจำนวนสิทธิ์มาจากข้อมูลอะไร โดยใช้ข้อมูลยอดรวม / Name the aggregate information supporting the capacity.',
        'ช่วยย้อนตรวจเหตุผลของจำนวนสิทธิ์ รอบทดลองใช้ที่มาสมมุติได้ โดยระบุให้ชัด / This explains the chosen capacity. Test collections may use a clearly labelled synthetic source.',
        'จำนวนสิทธิ์สมมุติสำหรับทดลองระบบ / Synthetic invitation capacity for testing'),
    'source_reference': (
        'ระบุเลขอ้างอิงหรือคำอธิบายเพื่อย้อนตรวจยอดรวม ไม่ต้องแนบรายชื่อ / Give a reference or description for the aggregate count. No roster is needed.',
        'ช่องนี้เป็นข้อความอ้างอิง ไม่ใช่ช่องอัปโหลดเอกสาร หลีกเลี่ยงชื่อ รหัสนิสิต และลิงก์ที่มีรหัสลับ / This is a text reference, not a document upload. Avoid names, student IDs and links containing secrets.',
        'ข้อมูลสมมุติ 5 สิทธิ์ สำหรับทดลอง F01 ครั้งที่ 2 ไม่มีรายชื่อ / Five synthetic slots for F01 trial 2; no named roster'),
    'privacy_notice': (
        'อธิบายวัตถุประสงค์ ผู้เข้าถึงข้อมูล และการนำข้อมูลไปใช้ให้ตรงกับรอบนี้ / Explain this collection’s purpose, who can access data and how it will be used.',
        'ตัวอย่างนี้ใช้เฉพาะการทดลอง ต้องทบทวนข้อความให้ตรงกับการใช้งาน รวมถึงระยะเก็บและช่องทางติดต่อที่กำหนดจริง / This sample is for testing. Review it for the actual use, including agreed retention and contact information.',
        'รอบนี้จัดทำเพื่อทดสอบ NEXORA โปรดใช้ข้อมูลสมมุติและไม่กรอกชื่อ รหัสนิสิต หรือข้อมูลระบุตัวตน เจ้าหน้าที่ผู้มีสิทธิ์ใช้ข้อมูลเพื่อตรวจการทำงานของระบบ หลักฐานที่ออกเป็นหลักฐานทดสอบ ไม่ใช้รับรางวัลหรือรับรองภาระงานจริง / This collection tests NEXORA. Use synthetic information without names, student IDs or identifying details. Authorized staff use the data to verify system operation. Test receipts do not award prizes or certify actual workload.'),
    'label_th': (
        'ชื่อกิจกรรมที่ผู้ตอบเห็นบนหลักฐานการเข้าร่วมภาษาไทย / The Thai activity name shown on the participation proof.',
        'ใช้ชื่อสั้นที่ผู้ตอบเข้าใจได้ ชื่อนี้เป็นข้อความบนหลักฐาน ส่วนรหัสอ้างอิงระบบสร้างให้เอง / Use a short, recognizable label. The system generates the reference code separately.',
        'เข้าร่วมแบบประเมินประสบการณ์นิสิต F01 — รอบทดลอง / เข้าร่วมแบบประเมินประสบการณ์นิสิต F01 — รอบทดลอง'),
    'label_en': (
        'ชื่อกิจกรรมเดียวกันสำหรับหลักฐานภาษาอังกฤษ / The same receipt activity name in English.',
        'ทั้งสองภาษาควรหมายถึงกิจกรรมเดียวกัน เพื่อให้ผู้ตรวจหลักฐานเข้าใจตรงกัน / Keep the meaning consistent in both languages for receipt verification.',
        'F01 Student Experience Assessment — Test Participation / F01 Student Experience Assessment — Test Participation'),
    'expires_at': (
        'หลักฐานใช้ตรวจสิทธิ์ได้ก่อนเวลานี้ ต้องอยู่หลังวันปิดรอบ / Proofs remain eligible for verification before this time, which must follow collection close.',
        'วันหมดอายุหลักฐานไม่ได้สั่งลบคำตอบอัตโนมัติ ควรเผื่อเวลาตรวจสิทธิ์หลังปิดรอบ / Receipt expiry does not automatically erase answers. Allow time for verification after collection closes.',
        '30 วันหลังปิดรอบ / Thirty days after collection closes'),
    'workload': (
        'เลือกเมื่อวางแผนใช้หลักฐานตรวจภาระงานในระบบที่จะเชื่อมต่อ / Select for planned workload verification in a future connected system.',
        'การเลือกนี้ไม่เพิ่มชั่วโมงอัตโนมัติ สำหรับตัวอย่างนิสิต C1 ปกติไม่ต้องเลือก / This does not automatically add hours. It is normally unnecessary for this undergraduate C1 example.',
        'รอบทดลองนิสิต: ไม่เลือกภาระงาน / Undergraduate trial: leave workload unchecked'),
    'prize': (
        'เลือกเมื่อวางแผนตรวจหลักฐานเพื่อกิจกรรมรางวัลหลังปิดรอบ / Select for planned reward eligibility checks after collection closes.',
        'ระบบไม่สุ่มผู้ชนะหรือแจกรางวัลอัตโนมัติ และรหัสหลักฐานยังเป็นรหัสทดสอบ / The system does not draw winners or award prizes automatically. These remain test receipts.',
        'รอบทดลองนิสิต: เลือกเพื่อลองตรวจสิทธิ์รางวัล / Undergraduate trial: select to test reward verification'),
}


def attach_guidance(form):
    from django.utils.translation import get_language
    from apps.accounts.templatetags.portal_ui import ui_wording
    for name,(hint,reason,example) in GUIDANCE.items():
        field=form.fields[name]
        field.help_text=ui_wording(hint,get_language())
        field.setup_reason=ui_wording(reason,get_language())
        field.setup_example=ui_wording(example,get_language())
        field.setup_fillable=name in {'code','context_th','context_en','source_title','source_reference','privacy_notice','label_th','label_en'}
        field.widget.attrs['aria-describedby']=f'id_{name}_helptext id_{name}_example'
