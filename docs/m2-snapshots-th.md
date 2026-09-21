# รอบคำนวณและการตรวจผลย้อนหลัง

เพิ่มการบันทึกรอบคำนวณจากแหล่งข้อมูลที่ระบุรุ่นแล้ว ผลและแหล่งข้อมูลของรอบที่บันทึกสำเร็จ
แก้ทับไม่ได้ หากข้อมูลเปลี่ยนต้องสร้างผลชุดใหม่ และยังตรวจผลชุดเดิมจาก snapshot เดิมได้
อ้างอิง Blueprint 1.2 ข้อ 4, 7, 9, 11, 12 และ 17

## สิ่งที่เพิ่ม

| ส่วน | การทำงาน |
|---|---|
| CalculationRun | เก็บรอบเก็บข้อมูล ประชากรที่ตรึง cutoff รุ่น engine และ hash ของ manifest/ผลทั้งชุด |
| CalculationInputSnapshot | เก็บคำตอบหรือ attendance ที่เลือกแล้ว รหัส revision นิยามคำถาม สูตร เครื่องมือ กลุ่ม บริบท และมิติ |
| IndicatorResult | เก็บค่าผล ตัวตั้ง ตัวหาร หน่วย สถานะ และ counts พร้อม hash; ไม่คำนวณสดเวลาเปิดผลเก่า |
| CalculationRequest | ผูก actor+round+idempotency key กับแหล่งข้อมูลและรอบคำนวณที่สำเร็จ |
| validate_results | คำนวณซ้ำจาก snapshot แล้วเทียบผล โดยไม่พิมพ์คำตอบรายคนหรือค่าผลลงหน้าจอ |

`record_calculation()` เป็นบริการภายใน รับ `SeriesInput` ที่มี stable IDs และ
`ResponseRevision` หรือ `AttendanceSource` ไม่รับค่าร้อยละที่คำนวณจาก browser
คืนเฉพาะ `RunReceipt` ซึ่งมี run ID, hash, สถานะ, จำนวน series และข้อมูลว่าคืนรอบเดิมหรือไม่

แหล่งข้อมูลสำหรับการทดสอบเป็นข้อมูลจำลองทั้งหมด ไม่มีการนำข้อมูลจริงขึ้น Git
ตัวเชื่อมตารางรับคำตอบจริงและทะเบียนกิจกรรมยังเป็นงานขั้นถัดไป จึงยังไม่มี endpoint
รับ snapshot JSON จากผู้ตอบหรือปุ่มคำนวณในหน้าคลัง และยังไม่เพิ่ม `calculate_round`
ที่อ้างว่าอ่านข้อมูลจริงได้ทั้งที่ยังไม่มีตัวเชื่อมดังกล่าว

## กติกาความถูกต้องและการทำซ้ำ

- ใช้รอบที่ปิดรับแล้ว และใช้ population snapshot, instrument version, translation bundle
  ที่รอบตรึงไว้ รุ่นเครื่องมือ/สูตร/คำแปลต้องผ่านการเผยแพร่แล้ว รุ่นเดิมที่ retired ยังใช้ตรวจผลของรอบเดิมได้
- ตรวจสูตรและการผูกคำถามกับ template 1.1 ที่ engine รองรับ หากสูตร ตัวเลือก มาตรา
  กลุ่ม หรือการผูกคำถามไม่ตรง จะปฏิเสธ ไม่ตีความ JSON เป็นโค้ดหรือข้ามกติกาล็อกรุ่น
- F06 เลือก revision ที่ส่งล่าสุดภายใน cutoff และก่อนเวลาปิดรับแบบ exclusive
  ไม่เลือกคะแนนสูงสุด และไม่มีผู้ประเมินหรือหลักฐานมาเพิ่มคะแนน ตัวอย่างนอกชุดข้อคำนวณไม่ถูกคัดลอกมาใน snapshot
- F01–F04 ไม่ยอมรับหลาย submitted revisions ของหน่วยตอบเดียวในบริบทเดียว
  เก็บ anonymous response IDs โดยไม่จับคู่กับรายชื่อประชากร; manifest ระบุเพียงนิยาม/จำนวนประชากรและแหล่งอ้างอิง
- F05 เลือกรุ่นล่าสุดของคน+กิจกรรม+session ณ source cutoff ก่อนกรองวันกิจกรรมตาม reporting period
  ถ้ารุ่นล่าสุดถูกปฏิเสธ จะไม่ย้อนเลือกครั้งที่เคยตรวจรับ ชั่วโมงอบรมและดูงานยังแยกกัน
  การตรวจรับเกิดหลังปิดรับได้เมื่ออยู่ก่อน source cutoff แต่ไม่ยอมรับการตรวจรับก่อนวันกิจกรรมจริง
- ตัวเชื่อมข้อมูลต้องส่งชุดแหล่งข้อมูลให้ครบ และตรวจวันเข้าทำงาน/พ้นสภาพ ช่วงเวลา session
  ซ้อนกัน และหลักฐาน F05 ตามระบบทะเบียนต้นทาง การเก็บ snapshot ไม่ใช่การสร้างหลักฐานใหม่
- สำหรับ F05/F06 ต้องมี roster ที่ตรึงและนับตรงจำนวนประชากรของกลุ่ม หากมีเพียง aggregate count
  จะไม่สร้างรายชื่อสมมติขึ้นมาเพื่อคำนวณ
- request key เดิม+actor+round กับข้อมูลเดิม คืนรอบเดิม; key เดิมกับข้อมูลหรือ cutoff ที่เปลี่ยนไป
  เป็น `IdempotencyConflict` และไม่เขียนทับ หากใช้ key ใหม่กับ manifest เดิมจะชี้รอบเดิมเพื่อลดงานซ้ำ
- ใช้ transaction และล็อกแถวรอบเก็บข้อมูลก่อนคำนวณ/บันทึก คำขอพร้อมกันต้องรอและตรวจของเดิมใหม่
  ผล แหล่งข้อมูล receipt และ audit บันทึกสำเร็จทั้งชุดหรือย้อนกลับทั้งชุด
- ก่อน commit ต้อง seal รอบให้ครบทั้ง inputs และ results; PostgreSQL มี deferred constraint
  ป้องกันรอบ building ค้างจากการ insert ตรง หลัง seal จะปฏิเสธ update/delete รวมถึงการเพิ่มลูกใหม่ผ่าน SQL
- hash ตรวจ payload และนิยามที่ตรึงไว้ การ replay ใช้ snapshot เท่านั้น ไม่โหลด catalog ปัจจุบัน
  ถ้า engine hash เปลี่ยน ต้องใช้รุ่น engine ที่บันทึกไว้ ไม่คำนวณด้วยรุ่นใหม่แล้วอ้างว่าเป็นการตรวจผลเก่า
- `complete` หมายถึงคำนวณและ seal ข้อมูลภายในสำเร็จ **ไม่ใช่ผลรับรองหรือผลที่เผยแพร่ได้**
  รอบเก็บข้อมูลยังไม่ถูกเลื่อนไป review/approved โดยบริการนี้

## สิทธิ์และการเปิดเผยข้อมูล

เพิ่มสิทธิ์ `calculation.run`, `calculation.source`, `calculation.validate`
โดยไม่เพิ่มให้ role เดิมโดยอัตโนมัติ ผู้ส่ง typed source เข้า service ต้องมีทั้ง run และ source
ใน scope นั้น แม้เป็น staff/superuser ก็ไม่ได้สิทธิ์เหล่านี้โดยปริยาย

ผู้ตรวจ replay ต้องมี validate ซึ่งคืนเฉพาะผลตรวจและจำนวน series ที่ตรงกัน ไม่คืนตัวตั้ง/ตัวหาร
หรือคำตอบรายคน โมเดลใหม่ไม่ลงทะเบียนใน Django admin และไม่มี default model permissions
audit เก็บเพียงรหัสรอบ/ขอบเขต hash สถานะ และจำนวน series ไม่เก็บ raw answers

ตาราง snapshot เป็นข้อมูลภายในที่มีข้อมูลจำกัดสิทธิ์ ไม่ใช่ payload สำหรับ public API
ต้องผ่าน suppression และสิทธิ์การอ่านผลก่อนทำหน้าจอ/API/export และไม่ได้อ้างว่าป้องกัน
ผู้ดูแลฐานข้อมูลที่มีสิทธิ์เปลี่ยน schema หรือปิด triggers ได้

## การตรวจผลที่บันทึกแล้ว

เมื่อมี run ID และบัญชีที่ได้รับสิทธิ์ สามารถตรวจโดยคำสั่งอ่านอย่างเดียว:

```text
python manage.py validate_results --run-id <RUN_UUID> --actor-user-id <USER_ID>
```

ผลสำเร็จคืน JSON สถานะ `verified`, จำนวน matched_results, input/engine hashes และ engine commit
หากรันใน deployment ที่ไม่มี Git ให้ตั้ง `EDPEX_ENGINE_COMMIT` เป็น SHA เต็มของรุ่นที่ติดตั้งจริง
ระบบเก็บ hash จากไฟล์ engine ที่ทำงานจริงควบคู่กับ SHA นี้

## การทดสอบและ migrations

ชุดเดิม catalog และ CAL รวม 69 tests; ชุด snapshot services เพิ่ม 21 tests และ
ชุด PostgreSQL guards/concurrency เพิ่ม 7 tests โดย latter ตรวจ row locks จริงและบังคับ
commit constraint จริง ไม่ใช้ SQLite แทนผลตรวจ trigger

```text
python manage.py check
python manage.py makemigrations --check --dry-run
python scripts/test_m1_migrations.py
python manage.py test --settings=edpex.testing
```

local ใช้ SQLite ชั่วคราวตรวจ services และ rollback เท่านั้น เพราะไม่มี PostgreSQL server
ชุด integration และ migration ใช้ workflow Test บน PostgreSQL 17 รายงานผลจริงใน PR

เพิ่ม migrations แบบต่อยอด 3 รายการ:

- `accounts/0003_calculation_permissions`: ขยาย action allowlist โดยไม่แก้ role/grant เดิม
- `calculations/0001_initial`: เพิ่มตาราง snapshot และข้อจำกัดความเป็นเอกลักษณ์
- `calculations/0002_snapshot_guards`: เพิ่ม invariant และการ seal แบบ atomic ฝั่ง PostgreSQL

ยังไม่ได้ apply migrations บน Supabase ของผู้ใช้ ไม่ต้อง seed catalog ซ้ำหรือแก้ข้อมูลเดิม
การติดตั้ง development ใช้ workflow plan/apply ที่มีอยู่เมื่อเข้าสู่ขั้นติดตั้งจริง

ระหว่างทดสอบยังแก้ปัญหาเดิมใน `publish_instrument_version()` ซึ่งเคยเผยแพร่สูตรเดียวซ้ำ
เมื่อตัวชี้วัดหลายรหัสใช้ร่วมกัน ตอนนี้เลือกและล็อก FormulaVersion แต่ละตัวครั้งเดียว
โดยยังคงการตรวจคำแปลและข้อห้ามแก้สูตรที่เผยแพร่แล้ว

## งานที่ยังเหลือ

อัปเดต: เพิ่มการรับ F06 ที่บันทึกจริงและการรับรองผลรวมแล้ว ดู
[F06 intake และ result review](f06-stored-collection-th.md) สำหรับขอบเขตใหม่
รายการด้านล่างเป็นขอบเขตที่ยังไม่มีตอนสร้าง snapshot increment แรก

ตัวเชื่อมรับคำตอบ/ทะเบียนจริง การจัดการ F04 appointment/context แบบครบวงจร
หน้ารอบคำนวณและสิทธิ์รับรอง/ส่งกลับผล การอ่านผลตาม disclosure policy
ข้อมูลย้อนหลัง raw/aggregate และนิยามรวมรายปี ยังต้องพัฒนาต่อ จึงยังไม่ถือว่า M2 ทั้งระยะเสร็จ
