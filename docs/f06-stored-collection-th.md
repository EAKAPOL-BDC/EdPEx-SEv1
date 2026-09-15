# F06: รับคำตอบที่บันทึกจริงและตรวจรับรองผลรวม

ต่อจากรอบคำนวณ snapshot เพิ่มขั้นตั้งแต่มอบหมายงาน F06 ก่อนเปิดรอบ จนถึง
เจ้าของกรอกบนเว็บ ส่งคำตอบ คำนวณจากฐานข้อมูล และผู้ตรวจอีกคนรับรอง/ส่งกลับผลรวม
เป็นส่วนเชื่อมของ M2/M4 ยังไม่ใช่การตรวจรับ M2 หรือ M4 ทั้งระยะ

## พฤติกรรมที่ใช้งานได้

- พื้นที่ทำงาน → **แบบประเมินตนเองของฉัน** แสดงเฉพาะงานของบัญชีที่มี `self.read`
- ผู้รับผิดชอบที่มี `selfassessment.assign` มอบหมายเจ้าของจากประชากรที่ตรึงของรอบ
  หลังรอบเป็น `ready` และก่อนเปิดรอบ กำหนดหน้าที่ ระดับที่คาดหวังทุกข้อคะแนน และด้านที่เกี่ยวข้อง
  แต่ละเจ้าของและแต่ละสมาชิกประชากรมีได้หนึ่ง assignment ต่อแบบ/บริบท
- กำหนดระดับที่คาดหวัง 1–5 ตามจริง ไม่ใส่ค่าเริ่มต้นสมมติ ยกเว้นด้าน M/T ตามหน้าที่ได้
  ข้ออื่นที่อยู่ในกลุ่มต้องคงไว้ ข้อมูลทั้งหมดแก้ย้อนหลังไม่ได้
- ผู้ตอบมี `self.write` และเป็นเจ้าของเท่านั้นจึงบันทึกได้ คะแนนเป็นจำนวนเต็มตามตัวเลือกจริง
  วันที่ กลุ่ม รอบ หน้าที่ และเจ้าของมาจากระบบ ไม่รับการแก้บริบทผ่านคำตอบ
- บันทึกร่าง/ส่งคำตอบ/ส่งรุ่นแก้ไขก่อนปิดรอบ ทุกครั้งสร้าง revision ใหม่
  `expected_revision` ป้องกันการเขียนทับจากหลายแท็บ และ request key ป้องกันกดซ้ำ
  key เดิมแต่ข้อมูลต่างคืน conflict การ retry ที่สำเร็จเดิมอ่าน receipt ได้หลังปิดรอบ
  แต่ยังตรวจสิทธิ์ปัจจุบัน และไม่มีการเขียนใหม่
- ข้อที่ไม่เกี่ยวข้องใน M/T ต้องระบุเหตุผล ผู้ตอบประกาศเอง ไม่มีผู้ตรวจยืนยัน
  ตัวอย่างพฤติกรรมและแผนพัฒนาของข้อคะแนนเลือกกรอก ข้อความเหล่านี้ไม่เข้าสูตร
- ข้อที่ไม่ตอบคงเป็น missing ไม่แทนด้วย 0 และไม่ทำให้ผลของข้ออื่นที่ตอบครบสูญหาย
  F06 ไม่มีช่องหลักฐาน คะแนนผู้ประเมิน หรือขั้นรอผู้ประเมินอนุมัติคำตอบ
- หน้าเว็บอ่านคำถามและคำชี้แจงจากรุ่นคำแปลที่รอบตรึงไว้ มีเมนูไทย/อังกฤษ
  ยังไม่กล่าวอ้างว่าคำแปลในคลังของผู้ใช้ผ่านการตรวจรับครบแล้ว

## คำนวณจากฐานข้อมูล

`calculate_self_assessments()` รับ `round_instrument_id`, cutoff, request key และ dry_run
ผู้วิเคราะห์มี `calculation.run` ก็เรียกได้ ไม่ต้องได้รับสิทธิ์ส่ง raw source
บริการเลือกคำตอบ submitted ทั้งหมดของแบบ/บริบทจากฐานข้อมูลเอง แล้วสร้างทุก series
ที่กำหนดใน bindings สำหรับกลุ่มในประชากรของรอบ รวมกลุ่มที่ไม่มีผู้ส่งคำตอบ
การเลือก latest submitted ใช้ cutoff และเวลาปิดแบบ exclusive เช่นเดิม

ตัวหารประชากร F06 ใช้ roster ที่ตรึงครบจริง ผู้ไม่ตอบยังอยู่ในตัวหารของสูตรที่กำหนดเช่นนั้น
คำตอบ draft รุ่นใหม่ไม่แทน submitted รุ่นก่อน และไม่เลือกคะแนนสูงสุด

สร้าง `StoredSourceSelection` เพื่อระบุว่าทั้งชุดมาจากตัวเชื่อมฐานข้อมูล
การคำนวณแบบ typed source เดิมยังต้องมีทั้ง `calculation.run` และ `calculation.source`
และไม่ส่งเข้ารับรองผ่านทางใหม่นี้ได้โดยตรง การตรวจผลเก่าด้วย `validate_results` ยังคงใช้ snapshot เท่านั้น

ขอบเขตคำนวณนี้คือ **F06 หนึ่งแบบ/บริบท** ไม่อ้างว่าคำนวณแบบอื่นทั้งหมดในรอบแล้ว
จึงไม่เปลี่ยนสถานะ CollectionRound ทั้งรอบเป็น approved

## การตรวจรับรองผลรวม

1. ผู้มี `result.submit` และ `calculation.validate` ส่ง sealed run เข้าตรวจพร้อมเหตุผล
2. ระบบ replay ผลและเทียบ source coverage ของทุก series กับข้อมูลบันทึก ณ cutoff เดิม
3. ผู้ตรวจมี `result.review` + `calculation.validate` อ่าน packet สูตร/ผลรวมที่เปิดได้
4. ผู้มี `result.approve` เพิ่มเติมรับรองหรือส่งกลับพร้อมเหตุผลและ review token ของผลที่ตรวจ
5. ผู้รับรองต้องไม่ใช่ผู้สร้าง calculation run หรือผู้ส่งชุดผลเข้าตรวจ

ReviewRequest และ Decision เป็น append-only ผลที่ส่งกลับไม่ถูกแก้เป็นอนุมัติภายหลัง
ให้สร้าง calculation run ใหม่และส่งตรวจใหม่ การรับรอง correction จะอ้าง approval เดิม
โดยไม่เปลี่ยนค่าหรือประวัติเดิม รุ่นเก่าห้ามแทน approval ที่ใหม่กว่า
การส่งคำขอ/ตัดสินซ้ำแบบเดิมคืนผลเดิม ข้อมูลต่างหลังตัดสินแล้วเป็น conflict

**การรับรองนี้ตรวจสูตรและความครบถ้วนของข้อมูลรวม ไม่ใช่รับรองสมรรถนะรายบุคคล**
คำตอบ F06 ยังคง submitted โดยไม่มี reviewer step
ผล approved ยังคง `publication_status=unpublished` ไม่มี public result API/export

## การเปิดเผยและประวัติ

หน้า review ใช้กลุ่ม/มิติที่ตรึง ไม่รับ arbitrary filters:

- valid_n < 5: ไม่ส่ง value, numerator, denominator หรือ quality counts
- เมื่อมีหลาย generation ในบริบทเดียวกัน: ซ่อนค่าของทุก generation เพิ่มเติม
  เพื่อไม่เปิดช่องหักลบค่ารุ่นเก่ากับ correction จนกว่าจะมีกระบวนการอนุญาตเผยแพร่ตาม policy
- ไม่มีการส่ง raw answers, optional examples/plans, eligible unit keys หรือเวลารายคนใน review packet
- หน้าเจ้าของแสดงเฉพาะคำตอบตนเอง ใช้ no-store; API/session และ CSRF ยังคงตรวจตาม Django
- ไม่ลงทะเบียนโมเดลใหม่ใน admin และไม่เพิ่ม default model permissions
- audit ไม่เก็บคำตอบหรือข้อความประกอบส่วนบุคคล; เหตุผลรับรองเก็บในประวัติการตัดสินจำกัดสิทธิ์

การเก็บ revision แบบ append-only ต้องจัดทำนโยบาย retention/ลบข้อมูลส่วนบุคคลก่อนเปิด production
ฟังก์ชันลบตามนโยบายยังไม่อยู่ใน increment นี้

## API ที่สร้างจริง

ดู [OpenAPI](f06-api.openapi.json) สำหรับ request/response และตัวอย่าง
ใช้ session ของเว็บเดียวกันและ `X-CSRFToken` ในคำขอที่เขียนข้อมูล
JSON ทุกคำขอต้องมีเฉพาะ fields ที่ระบุ; ไม่รับ client timestamp หรือผลคะแนนรวม

| เส้นทาง | งาน / สิทธิ์ |
|---|---|
| GET `/api/v1/me/self-assessments/` | รายการของตน / self.read |
| GET `/api/v1/me/self-assessments/{id}/` | schema + คำตอบของตน / self.read |
| PUT `.../{id}/draft/` | บันทึกฉบับร่าง / self.write |
| POST `.../{id}/submit/` | ส่งคำตอบหรือ revision / self.write |
| POST `/api/v1/self-assessment-assignments/` | มอบหมายก่อนเปิดรอบ / selfassessment.assign |
| POST `/api/v1/round-instruments/{id}/calculate/` | คำนวณ F06 ทุก series ของบริบท / calculation.run |
| POST `/api/v1/calculation-runs/{id}/review-request/` | ส่งเข้าตรวจ / result.submit + calculation.validate |
| GET `.../{id}/review/` | packet ที่ซ่อนผลตามข้อกำหนด / result.review + calculation.validate |
| POST `.../{id}/decision/` | รับรอง/ส่งกลับ / result.review + result.approve + calculation.validate |

ไม่มีการส่งข้อความ เชิญผู้ใช้ หรือมอบสิทธิ์เพิ่มโดยอัตโนมัติ
คำสั่ง bootstrap ใช้รายการสิทธิ์ผู้ดูแลองค์กรเดิมแบบคงที่ ไม่เพิ่มสิทธิ์คำนวณหรือรับรองผลตาม allowlist ใหม่
ผู้ดูแลเดิมไม่สามารถ delegate สิทธิ์ใหม่ที่ตนไม่มี ต้องตั้ง grant ใหม่ผ่านผู้ปฏิบัติการที่ได้รับอนุญาตในการเตรียมติดตั้ง
ไม่มีการแก้ role/grant เดิมใน migration นี้
การมอบหมาย assignment ไม่ได้มอบสิทธิ์ `self.read`/`self.write` ให้ผู้ตอบแทนผู้ดูแล

## Migrations และการตรวจ

เพิ่ม 6 migrations ต่อจากรุ่นเดิม: accounts 0004, calculations 0003–0004,
selfassessments 0001–0003 โดยเพิ่ม permission allowlist แต่ไม่ให้ role เดิมอัตโนมัติ

CI รอบแรกพบชื่อย่อตารางชนกับตัวแปรใน PL/pgSQL จึงเพิ่ม selfassessments 0003
เพื่อแก้ฟังก์ชันทั้งฐานใหม่และฐาน development ที่เคยใช้ 0002 แล้ว โดยคงเงื่อนไขตรวจเดิม

SQL guards ป้องกัน update/delete ทั้ง assignment, revision, source selection, review และ decision
ตรวจกำหนดส่ง ลำดับ revision ขอบเขตและการแยกผู้รับรอง พร้อมล็อกแถวรอบเดียวกับบริการ
การส่งพร้อมกันจึงตรวจ revision/idempotency อีกครั้งหลังผู้ส่งคนแรก commit

ชุดทดสอบใหม่ครอบคลุม owner/scope, คะแนนและ payload ผิด, NA, optional text, revisions,
การส่งซ้ำ, closed window, dry-run, source adapter, replay, independent review, correction,
suppression, CSRF และหน้าเว็บ รวมการตรวจ triggers/การส่งพร้อมกันบน PostgreSQL จริง
ผล local/CI ที่รันจริงบันทึกใน PR ไม่ใช้ SQLite ยืนยัน SQL guards

ยังไม่ได้ apply migrations กับ Supabase ของผู้ใช้ ไม่ต้อง seed F01–F06 ซ้ำ

## งานที่ยังเหลือ

- F01–F04: invitation registry กับ anonymous response store ที่แยกจากกัน; F04 appointment/context
- F05: ทะเบียนกิจกรรม/ช่วงเวลาจ้างงาน การตรวจหลักฐาน storage และชั่วโมงไม่ซ้ำ
- หน้าเจ้าหน้าที่มอบหมาย/ตั้ง expected levels และหน้าผู้ตรวจผล (increment นี้มี service/API)
- personal gap reports, historical raw/aggregate, annual aggregation และการรับรองทั้งรอบ
- disclosure-reviewed publication, dashboard/export, retention และ production hardening/UAT

หน้า F06 บนเครื่องผู้ใช้จะใช้งานรับคำตอบได้เมื่อเข้าสู่ขั้นติดตั้ง migrations
ตรวจรับและ publish คลังที่ตรึงไว้ เตรียม population/assignment/permissions แล้วเปิดรอบจริง
สถานะฉบับร่างในคลังเดิมของผู้ใช้ยังไม่ถูกเปลี่ยนโดยงานนี้
