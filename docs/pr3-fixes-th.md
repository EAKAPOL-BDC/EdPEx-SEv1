# แก้ข้อค้นพบ PR #3 ก่อน merge

เริ่มจาก PR head `99fc2ea637fbd45e4959594bb0d5b32972df5765` บนสาขา
`feature/m1-data-permissions` ซึ่งยังไม่มี commit ใหม่จากผล review
ใช้ Blueprint 1.2 และ Instruments 1.1 ใน `docs/source/` และรักษาต้นฉบับ/ทะเบียน M0
รวมถึง migrations `0001`/`0002` เดิมทุกไฟล์

## ข้อค้นพบ → วิธีแก้ → ไฟล์ → การยืนยัน

| ข้อค้นพบ | วิธีแก้ | ไฟล์ที่แก้ | Tests ที่ยืนยัน |
|---|---|---|---|
| รับรองคำแปลที่เปลี่ยนหลังผู้ตรวจเปิดอ่าน | ส่ง snapshot พร้อม token ที่ลงลายมือชื่อ ผูกผู้ตรวจ รายการ revision และ hash ของไทย/คำแปล ตรวจ token ภายใต้ transaction และ row locks; database เพิ่ม revision ทุกครั้งที่แก้ รวม A→B→A | `apps/catalog/services.py`, `models.py`, `migrations/0003_review_revisions.py` | `CatalogReviewFixTests`, `CatalogReviewConcurrencyTests` ใน `tests/test_m1_catalog_fixes.py`: A→B, แก้ต้นฉบับ, token คนอื่น/รายการอื่น, ABA, counters, คำแปลป้ายระบบ, audit และ concurrent edit/review ทั้งสองลำดับ |
| ย้ายสมาชิกพร้อม freeze แล้วประชากรที่ตรึงไม่ตรง | ล็อกแถวสมาชิกเดิม แล้วล็อก snapshot ต้นทาง/ปลายทางตาม UUID; ตรวจ frozen หลังได้ lock; เพิ่ม/ลบ/ย้ายใช้กติกาเดียวกัน และ freeze ถือ snapshot lock จน commit | `apps/rounds/models.py`, `services.py`, `migrations/0003_population_locking_and_retired_bindings.py` | `PopulationConcurrencyTests` ใน `tests/test_m1_population_concurrency.py`: freeze A/B ทั้งสองลำดับ, service และ SQL โดยตรง, เพิ่ม/ลบ, stale instance และการเปลี่ยนหลัง freeze |
| เจ้าของพ้นสมาชิกแล้วปิดรอบ/ยุติความรับผิดชอบไม่ได้ | ตรวจ active membership เมื่อสร้างหรือเปลี่ยนผู้รับผิดชอบ; การปิดงานคงเจ้าของเดิมและตรวจสิทธิ์ปัจจุบันของผู้กระทำ | `apps/rounds/models.py` | `DepartedPersonnelTests` ใน `tests/test_m1_lifecycle_fixes.py`: ผู้จัดการที่มีสิทธิ์สำเร็จ คนพ้นสมาชิก/ไม่มีสิทธิ์/ข้าม scope/org ถูกปฏิเสธ; ข้อมูลคนเดิมไม่เปลี่ยน |
| clone ชื่อ bundle ยาวแล้วเกิน max_length | ตัดฐานรหัสให้เหลือที่สำหรับ suffix และแก้ collision อย่างแน่นอน ไม่ใช้รหัสของต้นทางหรือรหัสซ้ำในรุ่นปลายทาง | `apps/catalog/services.py` | `CatalogCloneFixTests`: ชื่อ 36/40 ตัวอักษร clone หลายรอบ รหัสชนหลังตัดความยาว ต้นทางไม่เปลี่ยน และคำแปลใหม่ต้องตรวจรับ |
| อ่านรุ่น retired ของรอบเก่าไม่ได้ | เพิ่ม `round_respondent_text` ที่ตรวจ round/binding/version/bundle จากฐานจริง; อ่านเฉพาะรอบที่เปิดใช้แล้วและข้อความที่รับรอง; ห้ามเลือกรุ่น retired เข้า binding ใหม่ทั้ง model และ database | `apps/catalog/round_reading.py`, `apps/rounds/models.py`, rounds migration `0003` | `PinnedRoundWordingTests`: open/closed round, ขอบเขต/สิทธิ์, ความสัมพันธ์ปลอมใน cache, draft ภาษาอังกฤษ, locale/key ที่ไม่อนุญาต และการเพิ่ม retired binding ผ่าน SQL |

## สัญญาการเรียก API รับรองที่เปลี่ยน

`approve_translation` และ `review_localized_label` ต้องรับ `reviewed_token`
หน้าจอในระยะถัดไปต้องแสดงข้อความจาก snapshot เดียวกับ token แล้วส่ง token นั้นกลับมาเมื่อกดรับรอง
ห้ามโหลด token ใหม่อัตโนมัติขณะรับรอง เพราะผู้ตรวจยังไม่ได้อ่านข้อความของ token ใหม่

```python
preview = translation_review_snapshot(reviewer, entry)
# แสดง preview['source_text'] และ preview['translation_text'] ให้ผู้ตรวจอ่าน
approve_translation(reviewer, entry, reviewed_token=preview['reviewed_token'])
```

เมื่อข้อความหรือ revision เปลี่ยน ระบบปฏิเสธคำขอเดิมและต้องเปิดอ่าน snapshot ใหม่
token ของผู้ตรวจคนหนึ่งใช้แทนอีกคนไม่ได้ แม้ทั้งสองมีสิทธิ์ตรวจรับ
audit บันทึก revision และ hash ของคู่ข้อความที่ตรวจ โดยไม่บันทึก token
ต้นทางและคำแปลมี revision เพิ่มโดย database จึงย้อน counter ผ่าน bulk update เพื่อใช้ token เก่าไม่ได้

## Lock และความหมายของประชากร

เส้นทางแก้/ลบสมาชิกล็อกแถวสมาชิกก่อน แล้วล็อก snapshot ที่เกี่ยวข้องตามลำดับ UUID
ตรงกับ PostgreSQL UPDATE/DELETE ที่ได้ tuple lock ก่อนเรียก row trigger
freeze ล็อก snapshot และอ่านจำนวนสมาชิกโดยไม่ขอล็อกแถวสมาชิกย้อนลำดับ
ชุดทดสอบใช้ connection คนละตัวและตรวจ `pg_blocking_pids` ก่อนปล่อย transaction
จึงยืนยันการรอ lock จริง ไม่อาศัยหน่วงเวลาคาดเดา

ข้อมูลที่มาชนิด `raw` ต้องมีรายชื่อครบตามจำนวนที่ประกาศ แม้สมาชิกคนสุดท้ายย้ายออก
ข้อมูลที่มาชนิด `aggregate` ยังรองรับจำนวนจากผลรวมเดิมที่ไม่มีรายชื่อได้
หากมีรายชื่อประกอบ ต้องตรงกับจำนวนในทุกกลุ่มเช่นกัน
ที่มาประชากรเป็นข้อมูลของผู้จัดการประชากร ไม่ใช่หลักฐานที่บังคับผู้ตอบ F06

รหัส bundle ไม่ซ้ำตามขอบเขต `(instrument_version, bundle_version)` ของ schema เดิม
แต่ละ clone ได้ bundle UUID ใหม่; ไม่สร้างความหมายใหม่ให้รหัสคำถาม/ตัวเลือก
คำแปลที่ clone เป็น `needs_review` และไม่คัดลอกผู้ตรวจหรือเวลารับรอง

## migrations และการอัปเกรด

- `catalog/0003_review_revisions.py` เพิ่ม `review_revision` เริ่มที่ 1 และ trigger สำหรับคำแปล/ป้ายข้อความ
  ไม่แก้ข้อความ สถานะ ผู้ตรวจ หรือเวลารับรองที่มีอยู่
- `rounds/0003_population_locking_and_retired_bindings.py` เพิ่ม guards โดยไม่เขียนทับ migrations เดิม
  ลำดับ trigger ของ round binding คงการล็อก round ก่อน version
- `scripts/test_m1_migrations.py` ทดสอบสามเส้นทางบนฐานชื่อสุ่มที่สร้างใหม่:
  ฐานว่าง, Django auth เดิม, และฐาน M1 ที่ใช้ `0002` แล้ว
- เส้นทาง M1 เดิมสร้าง fixture ด้วย historical models ของ `0002` มีผู้ใช้/สิทธิ์
  เครื่องมือและ bundle เผยแพร่ คำแปล/ป้ายรับรอง ประชากร frozen รอบ open และ audit
  หลังอัปเกรด เปรียบเทียบทุกคอลัมน์เดิมของทุกตารางธุรกิจ รวม PK และ timestamps ว่าตรงทั้งหมด
  และตรวจ revision ใหม่เริ่มที่ 1

ฐานทดสอบเป็น PostgreSQL ชั่วคราวที่ loopback เท่านั้น
CI ใช้ workflow ทดสอบเดิมซึ่งเรียกสคริปต์และชุดทดสอบทั้งหมดอยู่แล้ว
ไม่มีการแก้ workflow ตรวจ Supabase หรือค่าการเชื่อมต่อเดิม

## ข้อจำกัดในการนำไปใช้

ผลในเครื่องของไฟล์ฉบับส่ง: PostgreSQL 17.11 / Django 5.2.17 ที่ loopback พอร์ต 55441
ผ่าน **142 tests ใน 113.372 วินาที** (ชุดเดิม 98 และเพิ่ม 44)
รวม separate-connection concurrency tests; system check, model/migration drift check,
compilation และ diff whitespace check ผ่าน
การ migrate ฐานว่าง, Django auth เดิม และ M1 `0002` เดิมผ่านทั้งหมด
รหัสผ่าน/สิทธิ์เดิมและข้อมูลธุรกิจทุกคอลัมน์เดิมของ fixture คงครบ

ผล GitHub CI เป็นการรันแยกบน Linux/PostgreSQL 17 ดูผลของ commit ล่าสุดที่
[Checks ของ PR #3](https://github.com/EAKAPOL-BDC/EdPEx-SEv1/pull/3/checks)
และลิงก์ run/commit ที่ระบุในรายละเอียด PR ไม่ใช้ผลในเครื่องแทนผล CI

- ยังไม่มีหน้าจอรับรองใน M1 ผู้พัฒนาหน้าจอต้องใช้สัญญา snapshot/token ข้างต้น
- การอ่านประวัติเป็น service สำหรับผู้มีทั้ง `round.manage` และ `catalog.read`
  ในขอบเขตของรอบ ไม่เปิดสิทธิ์ให้ผู้ตอบทั่วไปหรือข้ามขอบเขต
- Windows sandbox นี้ไม่อนุญาตการส่งสัญญาณ checkpoint เพื่อลบฐานชั่วคราวตามปกติ
  การทดสอบในเครื่องจึงใช้ `--keepdb`/`--keep-databases` และปิด cluster เมื่อจบ
  ผล cleanup บน Linux CI รายงานแยกจากผลในเครื่อง
- F06 ยังคง self-report ไม่มีผู้ให้คะแนนแทนหรือหลักฐานบังคับ
  ไม่ merge ไม่ apply migrations ไป Supabase ไม่ reset ข้อมูล และไม่ deploy
