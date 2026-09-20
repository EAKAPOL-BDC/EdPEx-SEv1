# รอบแบบประเมินหลายกลุ่ม — 21 กันยายน 2026

## วิธีใช้สำหรับเจ้าหน้าที่

1. เข้าพื้นที่ทำงาน → **รอบแบบประเมิน F01–F06** → **สร้างรอบ**
2. เลือกรุ่นแบบประเมินที่เผยแพร่แล้ว เช่น F01 รุ่นปีการศึกษาที่ต้องการ
3. กรอกชื่อรอบ ปีรายงาน และบริบทของการประเมินร่วมกันครั้งเดียว
4. เลือกกลุ่มได้หลายกลุ่ม เช่น **C1 และ C2.1**
5. สำหรับ F01 กรอกจำนวนอ้างอิงแยกตามกลุ่มและหลักสูตรที่จะเปิดรับ ช่องว่างหมายถึงไม่รวมหลักสูตรนั้น ต้องมีอย่างน้อยหนึ่งรายการต่อกลุ่มที่เลือก ไม่ต้องเพิ่มชื่อหรือรหัสผู้ตอบ
6. ตรวจวันเปิด กำหนดส่ง วันปิด แหล่งอ้างอิงยอดรวม คำชี้แจง และรายละเอียดหลักฐาน
7. กดตรวจข้อมูล อ่านหน้าทบทวน แล้วจึงยืนยัน ระบบสร้างรอบหลักพร้อมรายการแต่ละกลุ่ม/หลักสูตรครบชุด หากรายการใดสร้างไม่ได้จะไม่บันทึกบางส่วน
8. ในหน้ารอบหลัก ตรวจทุกรายการ แล้วใช้ **เปิดรับทุกกลุ่ม** และ **เผยแพร่ทุกกลุ่ม** ผู้ตอบจะเข้าถึงได้เมื่อทั้งสองสถานะพร้อมและอยู่ในช่วงเวลาที่กำหนด
9. เมื่อเก็บข้อมูลเสร็จ ระบุเหตุผลแล้ว **ปิดรับทุกกลุ่ม** จากนั้นคำนวณผลแยกกลุ่ม/หลักสูตรผ่านปุ่มของแต่ละรายการ

### รอบเดิม

รอบที่สร้างด้วยขั้นตอนรายชื่อ/คำเชิญเดิมยังเก็บข้อมูลไว้ครบ หน้ารายละเอียดมีปุ่ม **ใช้ข้อมูลนี้สร้างรอบสาธารณะ** ซึ่งคัดลอกค่าตั้งต้นไปยังแบบฟอร์มใหม่ ต้องตรวจวันเวลาและกรอกจำนวนแยกหลักสูตรเอง ระบบไม่เดาว่าจำนวนเดิมควรแบ่งอย่างไร และไม่แก้ไข ลบ หรือเผยแพร่รอบเดิมโดยอัตโนมัติ

### ขอบเขต

- รองรับการสร้างหลายกลุ่มร่วมกันสำหรับ F01, F02, F03, F05 และ F06 ตามกลุ่มของรุ่นแบบประเมินที่เผยแพร่ F05 ใช้รุ่นเชิงปริมาณ 2.1
- F04 ใช้ทะเบียนผู้บริหารรายปีและกระบวนการ ST1 + ST2 เดิม
- คำตอบ จำนวนอ้างอิง และผลคำนวณยังแยกตามกลุ่ม/หลักสูตร ไม่มีการรวมค่าเฉลี่ยโดยอัตโนมัติ
- หลักฐานยังแยกต่อการส่งสำเร็จ จำนวนคำตอบไม่ใช่การยืนยันจำนวนบุคคลที่ไม่ซ้ำ
- พอร์ต 8768 ยังเป็นระบบทดสอบ หลักฐานเป็น TEST การแก้ไขนี้ไม่ได้เปิดใช้งานจริงหรือเปิดรับแบบประเมินใดให้ผู้ใช้

## Implementation and verification

Added AssessmentBatch and AssessmentBatchItem as administrative parents around existing public collection bindings. Migration participation.0009 creates two tables; it does not convert existing collections. Creation is atomic and protected by an actor/scope nonce. All-group controls are atomic and permission checked. Existing public admission and response services remain the enforcement boundary.

Public-mode creation/menu links now lead to multi-group setup. Group-specific details link back to batch controls. Legacy draft settings remain available and can prefill a new batch without altering source records. The in-app staff guide was updated; prior offline screenshot exports were not regenerated for this change.

Verification:

- 25 regression tests passed: eight batch tests, ten public assessment tests and seven public leadership tests. Coverage includes multiple-group counts, invalid context rejection, permissions, replay protection, rollback after a later failure, confirmation, public visibility, and preservation of the source round.
- The HTTP template/language test passed again when exporting Thai/English pages for browser inspection.
- Browser inspection used isolated-test HTML rendered by the real templates: two-group selection, per-programme fields and live counts work; Thai desktop width 1280 and Thai/English mobile width 390 have no horizontal document overflow. No business data was submitted through browser QA.
- Active preview F01 versions were checked read-only and both include C1 and C2.1.
- Before migration: full PostgreSQL archive and hashes of existing records were saved locally under outputs/batch-ui-20260921. The archive was not restore-tested in this task and must not be uploaded, served or committed.
- After migration: all 75 pre-existing model fingerprints matched. No existing business records were changed or deleted.
- Django system check passed. After restart, home/login/public entry/static JavaScript returned HTTP 200; the staff creation URL redirects unauthenticated users to login.

Current loopback preview is runserver session 2721 on 127.0.0.1:8768. Previous sessions 63547 and 54925 were stopped. The former LAN address 10.51.72.64 is no longer assigned (current Wi-Fi is 192.168.1.155); LAN access was not reconfigured or verified in this change. The original 8767 service and production flags were not changed.
