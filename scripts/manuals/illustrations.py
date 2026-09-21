"""Source-grounded instructional illustrations, never live user screenshots.

Coordinates simplify the interface for print; numbered keys explain actions.
Every example is synthetic. The same PNG and captions are used on web/PDF.
"""
from hashlib import sha256

STATIC_DIR = 'manuals/illustrations'


def pin(number):
    return f'<b class="pin">{number}</b>'


def card(x, y, w, h, body, tone=''):
    return f'<div class="card {tone}" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px">{body}</div>'


def field(label, value='', number=None):
    return f'<div class="field">{pin(number) if number else ""}<label>{label}</label><div class="input">{value or "&nbsp;"}</div></div>'


def button(label, secondary=False, number=None):
    return (pin(number) if number else '') + f'<span class="btn {"secondary" if secondary else ""}">{label}</span>'


def heading(title, detail=''):
    return f'<h2>{title}</h2><p class="muted">{detail}</p>'


def fig(title, body, keys, sources, alt):
    return dict(title=title, body=body, keys=keys, sources=sources, alt=alt)


FIGURES = {
 'login': fig('เข้าสู่ระบบด้วยบัญชีของตนเอง',
    card(36,112,390,418,heading('ยินดีต้อนรับสู่ NEXORA','บัญชีสำหรับผู้ได้รับสิทธิ์')+'<div class="emblem">N</div><p>ผู้ตอบ F06 และเจ้าหน้าที่<br>ใช้ชื่อบัญชีของตนเอง</p>', 'soft') +
    card(450,112,594,418,field('ชื่อผู้ใช้','บัญชีตัวอย่าง',1)+field('รหัสผ่าน','••••••••••••••••',2)+'<p class="muted">แสดงรหัสผ่าน / ซ่อนรหัสผ่าน</p>'+button('เข้าสู่ระบบ NEXORA',number=3)),
    ['กรอกชื่อบัญชีที่ผู้ดูแลจัดเตรียมให้', 'กรอกรหัสผ่าน ตรวจภาษาแป้นพิมพ์และปุ่มแสดงรหัสผ่าน', 'กดเข้าสู่ระบบ แล้วเลือกพื้นที่ทำงานที่ได้รับสิทธิ์'],
    ['apps/accounts/templates/portal/login.html'], 'ภาพจำลองหน้าเข้าสู่ระบบ: 1 ชื่อผู้ใช้ 2 รหัสผ่าน 3 ปุ่มเข้าสู่ระบบ'),
 'workspace': fig('หางานและเครื่องมือจากเมนูด้านข้าง',
    card(36,112,310,430,heading('หน้าหลัก')+'<p>'+pin(1)+'หน้าหลัก</p><p>แบบประเมินของฉัน</p><hr><p>'+pin(2)+'เก็บข้อมูล</p><p class="small">งานเก็บข้อมูล F06<br>แบบสำรวจ F01–F04<br>กิจกรรมบุคลากร F05</p><hr><p>'+pin(3)+'คู่มือการใช้งาน</p>', 'soft')+
    card(370,112,674,190,heading('ตรวจชื่อพื้นที่ก่อนเริ่ม','เลือกพื้นที่ที่คุณได้รับสิทธิ์')+'<p>หน่วยงานตัวอย่าง · รอบตัวอย่าง</p>')+
    card(370,326,674,216,heading('อ่านชื่อรอบและสถานะ')+'<p>เมนูและรายการที่แสดงขึ้นกับบทบาทของคุณ</p><p class="notice">ไม่พบงาน? ให้ผู้ดูแลตรวจสิทธิ์และการมอบหมาย</p>'),
    ['ตรวจบัญชีและพื้นที่ก่อนเปิดรายการ', 'ขยายกลุ่มเมนู แล้วเลือกงานตามแบบฟอร์ม', 'เปิดคู่มือประจำหน้าที่ และดาวน์โหลด PDF จากหน้าอ่าน'],
    ['apps/accounts/templates/portal/base.html'], 'ภาพจำลองเมนูด้านข้าง: ภาพรวมงาน กลุ่มเก็บข้อมูล และคู่มือการใช้งาน'),
 'survey-entry': fig('เข้าทำ F01–F04 ด้วยรหัสคำเชิญ',
    card(160,112,760,430,heading('เข้าแบบสำรวจ / Enter survey','ใส่รหัสที่ผู้ดูแลส่งให้เพื่อเข้ารอบของคุณ')+
    field('รหัสคำเชิญ','[รหัสตัวอย่าง ไม่สามารถใช้งานได้]',1)+button('เข้าแบบสำรวจ / Continue',number=2)+
    '<p class="notice">'+pin(3)+'หน้าแบบสำรวจ: ตรวจชื่อแบบ กลุ่ม และบริบทก่อนตอบ</p>'),
    ['เปิดลิงก์ /survey/ ที่ได้รับ แล้วใส่รหัสคำเชิญของตน', 'กดเข้าแบบสำรวจ; เส้นทางนี้ไม่ใช้บัญชีผู้ดูแล', 'เมื่อเปิดแบบได้ ให้ตรวจกลุ่ม หลักสูตร/กิจกรรม และช่วงเวลาตามคำชี้แจง'],
    ['apps/surveys/templates/surveys/access.html','apps/surveys/templates/surveys/answer.html'], 'ภาพจำลองช่องรหัสคำเชิญ ปุ่มเข้าแบบสำรวจ และจุดตรวจบริบทหลังเปิดแบบ'),
 'survey-answer': fig('ตอบเป็นหมวด แล้วบันทึกฉบับร่าง',
    card(36,112,290,430,heading('หมวดแบบประเมิน')+'<p>'+pin(1)+'เลือกหมวดคำถาม</p><div class="navitem">01 หมวดตัวอย่าง</div><div class="navitem">02 หมวดถัดไป</div><hr><p>เลือกคำตอบแล้ว</p><div class="track"><i style="width:45%"></i></div><p class="small">ความคืบหน้าในหน้า<br>ยังไม่ใช่การบันทึก</p>', 'soft')+
    card(350,112,694,430,heading('คำถามตัวอย่าง','ตัวเลือกจริงขึ้นกับมาตรวัดของแต่ละข้อ')+'<p>'+pin(2)+'อ่านคำถามแล้วเลือกคำตอบ</p><div class="choice">○ ตัวเลือกตามแบบฟอร์ม</div><div class="choice selected">● ตัวเลือกที่เลือกไว้</div><p class="small">หมวดก่อนหน้า　 /　 หมวดถัดไป</p>'+button('บันทึกฉบับร่างและทำต่อ',True,3)),
    ['เลือกหมวดหรือใช้ปุ่มก่อนหน้า–ถัดไป', 'กดการ์ดคำตอบตามประสบการณ์ อ่านมาตรวัดของข้อนั้น', 'กดบันทึกฉบับร่างและทำต่อ ตรวจข้อความสำเร็จ; ระบบปรับคำถามตามเงื่อนไขหลังบันทึก'],
    ['apps/surveys/templates/surveys/answer.html','apps/accounts/templates/portal/components/assessment_sections.html'], 'ภาพจำลองหมวดคำถาม ตัวเลือกแบบการ์ด และปุ่มบันทึกฉบับร่าง'),
 'survey-submit': fig('ตรวจคำตอบก่อนยืนยันส่ง F01–F04',
    card(36,112,1008,200,heading('ตรวจสอบก่อนส่งคำตอบ')+'<p>'+pin(1)+'☑ ฉันตรวจสอบคำตอบแล้ว และเข้าใจว่าหลังส่งจะไม่สามารถแก้ไขได้</p>'+button('ยืนยันส่งคำตอบ →',number=2))+
    card(36,336,1008,206,heading('ตรวจข้อความตอบรับหลังส่ง')+'<p>'+pin(3)+'เมื่อระบบยืนยันรับคำตอบแล้ว จึงถือว่าส่งสำเร็จ</p><p class="notice">F01–F04 ส่งแล้วแก้คำตอบไม่ได้ · บันทึกฉบับร่างยังไม่ใช่การส่ง</p>', 'soft'),
    ['ทบทวนทุกหมวด แล้วเลือกช่องยืนยันเมื่อเข้าใจเงื่อนไข', 'กดยืนยันส่งคำตอบเพียงครั้งเดียวและรอผล', 'ตรวจหน้าตอบรับ หากเกิดข้อผิดพลาดให้ตรวจสถานะก่อนลองใหม่'],
    ['apps/surveys/templates/surveys/answer.html','apps/surveys/templates/surveys/receipt.html'], 'ภาพจำลองการยืนยันและส่งแบบสำรวจ พร้อมคำอธิบายการตรวจหน้าตอบรับ'),
 'f06': fig('F06: แยกฉบับร่างออกจากการส่งคำตอบ',
    card(36,112,1008,112,'<h2>'+pin(1)+'แบบประเมินตนเอง · F06</h2><p class="muted">รอบตัวอย่าง · ตรวจหน้าที่ที่ได้รับมอบหมายและสถานะคำตอบ</p>', 'soft')+
    card(36,244,1008,184,'<h2>'+pin(2)+'ตอบคำถามตามหน้าที่และมาตรวัด</h2><div class="choice selected">● เลือกคำตอบตามระดับที่แบบฟอร์มกำหนด</div><p class="small">ตัวอย่างและแผนพัฒนาเลือกกรอกได้ · ด้าน M/T ที่ไม่เกี่ยวข้องต้องให้เหตุผล</p>')+
    card(36,448,1008,94,pin(3)+button('บันทึกฉบับร่าง',True)+button('ส่งคำตอบประเมินตนเอง →')),
    ['เปิดแบบประเมินของฉัน ตรวจรอบ กลุ่ม และหน้าที่', 'ตอบจากตนเอง; อ่านระดับคาดหวังและเหตุผลที่ต้องกรอก', 'เลือกบันทึกฉบับร่างหรือส่งคำตอบ และตรวจสถานะ/รุ่นคำตอบ; ส่ง revision ใหม่ได้ขณะรอบยังรับคำตอบ'],
    ['apps/selfassessments/templates/selfassessments/detail.html'], 'ภาพจำลอง F06 แสดงบริบท การตอบ และปุ่มบันทึกฉบับร่างกับส่งคำตอบที่แยกกัน'),
 'admin': fig('จัดการระบบ: เลือกเครื่องมือตามงาน',
    card(36,112,492,230,heading('สมาชิกและบทบาท')+'<p>'+pin(1)+'ตรวจคน บทบาท ขอบเขต และช่วงเวลา</p>'+button('เปิดเครื่องมือ →',True))+
    card(552,112,492,230,heading('ตั้งค่าพื้นที่ทำงาน')+'<p>'+pin(2)+'เปลี่ยนชื่อพร้อมเหตุผลการแก้ไข</p>'+button('เปิดเครื่องมือ →',True))+
    card(36,366,1008,176,heading('ติดตามงานและประวัติ')+'<p>'+pin(3)+'รอบที่ต้องติดตาม · สิทธิ์ใกล้หมดอายุ · ประวัติการดำเนินงาน</p><p class="small">แต่ละเครื่องมือยังตรวจสิทธิ์ในพื้นที่แยกกัน</p>', 'soft'),
    ['ตรวจบัญชีเดิมก่อนสร้างใหม่ และมอบบทบาทเท่าที่จำเป็น', 'ตั้งชื่อพื้นที่พร้อมเหตุผล; เปิดหน้าใหม่เมื่อข้อมูลเปลี่ยนระหว่างแก้', 'ติดตามรายการค้างและตรวจประวัติ โดยไม่เปลี่ยนผลรับรองแทนเจ้าของหน้าที่'],
    ['apps/accounts/templates/portal/backoffice.html'], 'ภาพจำลองเครื่องมือหลังบ้าน: สมาชิกและบทบาท ตั้งค่าพื้นที่ และติดตามงาน'),
 'preview': fig('ดูแบบประเมินให้ตรงแบบ รุ่น และกลุ่ม',
    card(36,112,1008,190,'<div class="half">'+field('แบบฟอร์ม','F01',1)+'</div><div class="half">'+field('กลุ่มผู้ประเมิน','C1 · กลุ่มตัวอย่าง')+'</div>'+button('แสดงแบบประเมิน',True))+
    card(36,326,492,216,heading('F01 · รุ่นตัวอย่าง')+'<p>'+pin(2)+'เลือกกลุ่มเพื่อเปิดดู</p><div class="navitem">C1 · กลุ่มตัวอย่าง →</div>')+
    card(552,326,492,216,heading('ตรวจตัวอย่างคำถาม')+'<p>'+pin(3)+'คำชี้แจง · มาตรวัด · เงื่อนไข</p><p class="notice">การเปิดดูไม่สร้างคำตอบจริง</p>', 'soft'),
    ['กรองแบบฟอร์มและกลุ่ม แล้วกดแสดงแบบประเมิน', 'เลือกกลุ่มจากการ์ดรุ่นที่ต้องการตรวจ', 'อ่านคำชี้แจงและคำถามตามเงื่อนไข; F04 ตรวจตำแหน่งผู้ถูกประเมินให้ตรง'],
    ['apps/accounts/templates/portal/assessment_previews.html','apps/accounts/templates/portal/assessment_preview.html'], 'ภาพจำลองตัวกรองแบบฟอร์ม กลุ่ม และการเปิดดูแบบประเมินโดยไม่บันทึกคำตอบ'),
 'round': fig('เตรียมรอบและตรวจประชากรก่อนเปิดรับ',
    card(36,112,1008,100,pin(1)+button('สร้างรอบ F01–F04',True)+button('สร้างรอบ F06',True)+button('เพิ่มช่วงรายงาน',True))+
    card(36,236,492,306,heading('รอบตัวอย่าง','ร่าง · รุ่นแบบฟอร์ม · ช่วงรายงาน')+'<p>'+pin(2)+'วันเปิดรับ / วันปิดรับ</p><p>ตรวจกลุ่มและบริบทของรอบ</p>'+button('จัดการรอบ →',True))+
    card(552,236,492,306,heading('ก่อนเปิดรับคำตอบ')+'<p>'+pin(3)+'ตรวจและตรึงประชากร</p><p>F01–F04 → ออกรหัสคำเชิญ<br>F06 → มอบหมายเจ้าของงาน</p><p class="notice">เปิดรับเมื่อพร้อมและถึงเวลาที่กำหนด</p>', 'soft'),
    ['สร้างช่วงรายงานหรือรอบให้ตรงแบบ; F05 เริ่มจากเมนูกิจกรรมบุคลากร', 'เปิดจัดการรอบและตรวจเวลา รุ่นแบบ กลุ่ม และบริบท', 'ตรวจ/ตรึงประชากร แล้วออกรหัสหรือมอบหมายตามแบบก่อนเปิดรับ'],
    ['apps/accounts/templates/rounds/list.html','apps/accounts/templates/rounds/detail.html'], 'ภาพจำลองปุ่มสร้างรอบ การ์ดรอบ และรายการตรวจประชากรก่อนเปิดรับ'),
 'activity': fig('F05: บันทึกกิจกรรมและชั่วโมงจริง',
    card(36,112,620,430,field('บุคลากรจากทะเบียน','เลือกบุคลากรตัวอย่าง',1)+field('ชื่อกิจกรรม','กิจกรรมตัวอย่าง')+'<div class="half">'+field('ชั่วโมงอบรมจริง','6.00',2)+'</div><div class="half">'+field('ชั่วโมงดูงานจริง','0.00')+'</div><p class="small">ตัวเลขตัวอย่าง ไม่ใช่ข้อมูลจริง</p>')+
    card(680,112,364,430,heading('ก่อนบันทึก')+'<p>ตรวจเวลาเริ่ม–จบ<br>หลักฐานอ้างอิง<br>และเหตุผลการบันทึก</p>'+field('บันทึกเป็น','ส่งตรวจ',3)+button('บันทึก')+'<p class="small">ผู้ตรวจบันทึกผลตรวจอีกขั้นหนึ่ง</p>', 'soft'),
    ['เลือกบุคลากรจากทะเบียนให้ตรงกับเจ้าของกิจกรรม', 'กรอกเวลาและชั่วโมงจริง แยกอบรม/ดูงาน พร้อมเลขที่หรือที่เก็บหลักฐาน', 'เลือกฉบับร่างหรือส่งตรวจ ระบุเหตุผลแล้วบันทึก; การส่งตรวจยังไม่ใช่ตรวจรับ'],
    ['apps/accounts/templates/calculations/activity_entry.html','apps/calculations/activity_web.py'], 'ภาพจำลองฟอร์ม F05: บุคลากร ชั่วโมงกิจกรรม และสถานะร่างหรือส่งตรวจ'),
 'calculate': fig('ตรวจความพร้อมก่อนบันทึกชุดผล',
    card(36,112,492,430,heading('เตรียมชุดผลแบบสำรวจ','รอบตัวอย่าง')+field('เวลาตัดข้อมูล / Cutoff','วันที่และเวลาที่ตกลงใช้',1)+'<p>ตรวจรุ่นแบบ กลุ่ม และบริบท</p>'+button('ตรวจความพร้อมคำนวณ',number=2))+
    card(552,112,492,430,heading('หลังตรวจความพร้อมผ่าน')+'<p>อ่านจำนวนชุดตัวชี้วัด<br>และตรวจปัญหาจากต้นทาง</p><div class="notice">ใช้เฉพาะคำตอบที่ส่งแล้ว<br>ตามเงื่อนไขของรอบ</div><p>'+pin(3)+'บันทึกชุดผล</p><p class="small">จากนั้นส่งต่อผู้ตรวจรับรอง<br>ยังไม่ใช่ผลรับรองทันที</p>', 'soft'),
    ['ตรวจรอบและกำหนด cutoff ให้ตรงชุดข้อมูลที่ต้องการ', 'กดตรวจความพร้อมคำนวณ และแก้ปัญหาต้นทางที่ระบบแจ้ง', 'เมื่อผ่านแล้วกดบันทึกชุดผลและส่งตรวจตามขั้นตอนของแบบนั้น'],
    ['apps/surveys/templates/surveys/calculate.html','apps/selfassessments/templates/selfassessments/operator_calculate.html'], 'ภาพอธิบายสองขั้นของการคำนวณ: ตรวจความพร้อม แล้วบันทึกชุดผลเพื่อส่งตรวจ'),
 'review': fig('ตรวจชุดผลก่อนตัดสินใจรับรอง',
    card(36,112,310,430,heading('01 / ที่มา')+'<p>'+pin(1)+'รอบ · รุ่น · cutoff</p><p>ทะเบียนประชากร<br>และแหล่งข้อมูล<br>ตรงกับงานที่ตรวจ</p>', 'soft')+
    card(370,112,340,430,heading('02 / ตรวจซ้ำ')+'<p>'+pin(2)+'สูตร · ความครบ</p><p>ผลคำนวณซ้ำผ่าน<br>ตัวชี้วัดและมิติครบ<br>ข้อจำกัดการเปิดเผย</p>')+
    card(734,112,310,430,heading('03 / ตัดสินใจ')+'<p>'+pin(3)+'บันทึกเหตุผล</p><div class="choice">รับรอง</div><div class="choice">ส่งกลับให้แก้ไข</div><p class="small">ยึดสิทธิ์และเงื่อนไข<br>ที่ระบบตรวจ</p>', 'soft'),
    ['ตรวจชุดผลและหลักฐานต้นทางให้ตรงบริบท', 'ตรวจ replay ความครบ หน่วย และกติกาซ่อนค่ากลุ่มเล็ก', 'ระบุเหตุผลและตัดสินใจตามสิทธิ์; ผลที่ส่งกลับต้องแก้ต้นทางและสร้างชุดใหม่'],
    ['scripts/manuals/operations.py','apps/calculations/review.py'], 'แผนภาพลำดับตรวจรับรอง: ตรวจที่มา ตรวจคำนวณซ้ำ และบันทึกการตัดสินใจ'),
 'results': fig('อ่านกราฟเปรียบเทียบโดยตรวจหน่วยและที่มา',
    card(36,112,1008,108,'<p>'+pin(1)+'ผลจริงรับรอง / ข้อมูลสาธิต　 ·　 ช่วงรายงาน　 ·　 แบบฟอร์ม</p><p class="small">เลือกตัวกรองให้ตรงกับคำถามที่ต้องการวิเคราะห์</p>', 'soft')+
    card(36,244,620,298,heading('กราฟตัวอย่าง · คะแนนเต็ม 10')+'<p>'+pin(2)+'เปรียบเทียบเฉพาะเงื่อนไขที่ตรงกัน</p><div class="bar-row">ST1 <span class="bar" style="width:65%"></span> 8.10</div><div class="bar-row">ST2 <span class="bar teal" style="width:61%"></span> 7.60</div><p class="small">ค่าตัวอย่างสำหรับอธิบาย ไม่ใช่ผลจริง</p>')+
    card(680,244,364,298,heading('อ่านตารางประกอบ')+'<p>'+pin(3)+'หน่วยและสถานะ</p><p>“ซ่อนค่า” ≠ ศูนย์<br>ไม่มีข้อมูล ≠ ศูนย์</p><p class="notice">อ่านที่มาก่อนนำไปใช้รายงาน</p>', 'soft'),
    ['เลือกผลจริงรับรองหรือข้อมูลสาธิต และช่วงรายงานให้ชัดเจน', 'เทียบเฉพาะสูตร หน่วย รุ่น บริบท และช่วงที่ระบบอนุญาต; ตัวเลขในภาพเป็นตัวอย่าง', 'อ่านตาราง สถานะ และข้อจำกัดการเปิดเผย ไม่แทนค่าที่ซ่อนด้วยศูนย์'],
    ['apps/accounts/templates/calculations/comparisons.html','apps/accounts/templates/calculations/visualization.html'], 'ภาพกราฟตัวอย่าง ST1 8.10 และ ST2 7.60 คะแนนเต็ม 10 พร้อมตัวกรองและคำเตือนเรื่องค่าที่ซ่อน'),
 'audit': fig('ค้นประวัติและติดตามจากรหัสอ้างอิง',
    card(36,112,1008,180,'<div class="half">'+field('ช่วงวันที่','วันเริ่มต้น → วันสิ้นสุด',1)+'</div><div class="half">'+field('คำค้นการดำเนินการ','เหตุการณ์ที่ต้องการตรวจ')+'</div>'+button('ค้นหา',True))+
    card(36,316,1008,226,'<h2>'+pin(2)+'วันเวลา · การดำเนินการ · ผู้ดำเนินการ · เหตุผล</h2><hr><p class="small">เหตุการณ์ตัวอย่าง　 /　 รหัสวัตถุอ้างอิง　 /　 ผู้ใช้ตัวอย่าง</p><p>'+pin(3)+'ก่อนหน้า　　1 / 2　　ถัดไป</p><p class="small">ตรวจทุกหน้าภายใต้ตัวกรองเดียวกัน ก่อนสรุปข้อค้นพบ</p>', 'soft'),
    ['กำหนดวันที่และประเด็นในพื้นที่ที่ได้รับสิทธิ์', 'อ่านเวลา ผู้ดำเนินการ เหตุผล และรหัสวัตถุอ้างอิง', 'ใช้ก่อนหน้า/ถัดไปเพื่ออ่านครบ แล้วบันทึกรหัสเหตุการณ์ในรายงานติดตาม'],
    ['apps/accounts/templates/portal/backoffice_audit.html'], 'ภาพจำลองตัวกรองประวัติ คอลัมน์หลักของเหตุการณ์ และการเปลี่ยนหน้า'),
 'architecture': fig('โครงสร้างเว็บ: เส้นทางคำขอและจุดตรวจสิทธิ์',
    card(36,112,310,180,heading('Browser')+'<p>HTML / CSS / JS<br>session + CSRF</p>', 'soft')+
    card(386,112,310,180,heading('Routing → View')+'<p>'+pin(1)+'middleware / forms<br>method · owner · scope</p>')+
    card(734,112,310,180,heading('Domain services')+'<p>'+pin(2)+'permission<br>transaction / version</p>', 'soft')+
    '<div class="arrow" style="left:350px;top:175px">→</div><div class="arrow" style="left:699px;top:175px">→</div>'+
    card(386,346,310,196,heading('Response')+'<p>Template / aggregate<br>เฉพาะข้อมูลที่อนุญาต</p>')+
    card(734,346,310,196,heading('PostgreSQL')+'<p>'+pin(3)+'constraints / guards<br>snapshot / audit</p>', 'soft')+
    '<div class="arrow" style="left:870px;top:296px">↓</div><div class="arrow" style="left:699px;top:410px">←</div>',
    ['View ตรวจคำขอและขอบเขต ก่อนเรียกบริการของงาน', 'Service รักษา permission, transaction, revision และ workflow', 'PostgreSQL บังคับข้อจำกัด/ประวัติ; response ส่งเฉพาะข้อมูลที่เปิดเผยได้'],
    ['edpex/urls.py','scripts/manuals/developer.py'], 'แผนภาพ Browser ส่งคำขอไป Routing และ View ผ่าน Domain services ไป PostgreSQL แล้วคืน Template หรือ aggregate'),
 'privacy': fig('F01–F04: แยกการใช้สิทธิ์ออกจากคำตอบ',
    card(36,112,310,190,heading('รหัสคำเชิญ')+'<p>'+pin(1)+'ตรวจสิทธิ์ส่ง<br>และช่วงเปิดรับ</p>', 'soft')+
    card(386,112,310,190,heading('Session ชั่วคราว')+'<p>บันทึกฉบับร่าง<br>ตรวจเงื่อนไขคำถาม</p>')+
    card(734,112,310,190,heading('ยืนยันส่ง')+'<p>'+pin(2)+'ใช้สิทธิ์ครั้งเดียว<br>ภายใน transaction</p>', 'soft')+
    '<div class="arrow" style="left:350px;top:180px">→</div><div class="arrow" style="left:699px;top:180px">→</div>'+
    card(36,342,660,200,heading('ข้อจำกัดที่ต้องรักษา')+'<p>ไม่เพิ่มความสัมพันธ์หรือบันทึกเหตุการณ์<br>ที่เชื่อมคำตอบกลับไปหาตัวผู้ตอบ</p>', 'soft')+
    card(734,342,310,200,heading('AnonymousResponse')+'<p>'+pin(3)+'คำตอบแยกจาก<br>ทะเบียนคำเชิญ</p>')+
    '<div class="arrow" style="left:870px;top:301px">↓</div>',
    ['รหัสใช้ตรวจสิทธิ์ ไม่ใส่รหัสใน URL หรือภาพคู่มือจริง', 'Submit ใช้สิทธิ์ครั้งเดียว เก็บร่าง/ส่งผ่านเงื่อนไขบริการ', 'รักษาการแยกตัวตน ไม่เพิ่ม join หรือ audit metadata ที่เชื่อมผู้ตอบกับคำตอบ'],
    ['apps/surveys/web.py','scripts/manuals/developer.py'], 'แผนภาพรหัสคำเชิญไป session ชั่วคราวและยืนยันส่ง ก่อนเก็บ AnonymousResponse แยกจากทะเบียน'),
}


def attach(manuals, root):
    """Attach allowlisted, checksummed static illustrations to related sections."""
    by_role = {
        'system-administrator': {'overview':['admin'], 'settings':['audit']},
        'form-manager': {'preview':['preview']},
        'collection-officer': {'create-round':['round'], 'assign-f06':['f06']},
        'activity-officer': {'entry':['activity']},
        'calculation-operator': {'calculate-survey':['calculate']},
        'result-reviewer': {'review-steps':['review']},
        'executive-reader': {'visualization':['results']},
        'audit-reader': {'audit-search':['audit']},
        'developer': {'architecture':['architecture'], 'workflow-survey':['privacy'], 'workflow-result':['review']},
    }
    for m in manuals:
        placements = dict(by_role.get(m['slug'], {}))
        if m['category'] == 'respondents':
            placements.update({'prepare':['survey-entry'], 'survey':['survey-answer'], 'draft-and-status':['survey-submit']})
            if m['group'] in ('ST1','ST2'):
                placements['self-assessment'] = ['f06']
                placements['activity-input'] = ['activity']
        elif m['category'] == 'operations':
            placements['start'] = ['login', 'workspace']
        number = 0
        for section in m['sections']:
            section['figures'] = []
            for key in placements.get(section['id'], []):
                number += 1
                source = FIGURES[key]
                payload = (root/'apps/manuals/static'/STATIC_DIR/(key+'.png')).read_bytes()
                section['figures'].append(dict(key=key, number=number, title=source['title'],
                    alt=source['alt'], keys=source['keys'], filename=key+'.png',
                    sha256=sha256(payload).hexdigest(), width=2160, height=1200))
        m['figure_count'] = number
