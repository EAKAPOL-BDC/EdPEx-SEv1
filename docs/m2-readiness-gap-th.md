# ตรวจช่องว่างก่อนพัฒนาระบบคำนวณ M2

> อัปเดตหลังรายงานฐานนี้: เพิ่มแกนคำนวณและ CAL-01–18 แล้ว ดู
> [ผลทดสอบและขอบเขตแกนคำนวณ](m2-calculation-core-th.md)
> ข้อความ “ยังไม่มี engine” ด้านล่างบรรยาย commit ที่ตรวจเดิม ไม่ใช่สถานะล่าสุด
> ส่วน calculation run/source manifest ที่บันทึกถาวร สิทธิ์ และงาน M2 ส่วนอื่นยังไม่เสร็จ

วันที่ตรวจ: 2026-09-15 UTC  
โค้ดที่ตรวจ: `11e21f65831eba7a445e7c78b4bfdba68e9c0f2e` บน `feat/web-organization-access`  
ฐานข้อกำหนด: `docs/source/EdPEx_System_Blueprint_v1.md` System Blueprint 1.2 และ `docs/source/EdPEx_6_Instruments.md` 1.1  
ข้อ 24–33 ใช้ขยาย milestone เดิม ไม่เลื่อนเป็นงานนอกขอบเขต

## ข้อสรุป

การนำเข้าคลังผ่านการตรวจจำนวนบนเครื่องผู้ใช้แล้ว แต่ M0–M1 ยังไม่ครบเกณฑ์เพิ่มเติมของ Blueprint และยังไม่มี calculation engine ในโค้ดที่ตรวจ ไม่ประกาศว่า M2 ผ่านจากจำนวน FormulaVersion ที่นำเข้า

เริ่มพัฒนาแกนคำนวณที่ไม่พึ่งฐานข้อมูลได้ระหว่างปิดช่องว่าง M0–M1 ส่วนการเปิดรอบ การรับคำตอบ และการเผยแพร่ต้องผ่านเกณฑ์ของระยะนั้นก่อน

## หลักฐานและขอบเขต

| หลักฐาน | ผล | ขอบเขตที่ยืนยัน |
|---|---|---|
| ภาพคลังจากผู้ใช้ | F01–F06 รุ่น 1.1 ฉบับร่าง; 42/19/29/34/22/44 ข้อ รวม 190 | จำนวนที่หน้าเว็บแสดง ไม่ใช่การตรวจเนื้อหาทุกรายการ |
| ภาพ SQL จากผู้ใช้ | สูตร 20; ตัวชี้วัด 63; bindings รุ่น 1.1 จำนวน 63 | จำนวนใน scope ที่ตรวจ ไม่ใช่ผลทดสอบสูตร |
| Offline tests ที่รันในการตรวจครั้งนี้ | 26 tests ผ่าน | ชุด catalog, bindings, source semantics บนโค้ดข้างต้น |
| GitHub Actions Test #23 | success, run 34999150538 | CI ของ commit ข้างต้น; workflow ใช้ PostgreSQL 17 |
| Migration/check ที่ผู้ใช้ส่งก่อนหน้า | check ผ่าน; migrations แสดง [X] | สภาพแวดล้อมผู้ใช้ ณ เวลาภาพ ไม่ใช่การตรวจฐานข้อมูลโดยผู้จัดทำรายงาน |

คำสั่งที่รันจริง:
```bash
python -m unittest tests.test_m0_catalog tests.test_m0_bindings tests.test_m0_source_semantics
```

ผล: Ran 26 tests; OK. ไม่ได้รัน PostgreSQL tests ซ้ำใน scratch และไม่ได้เชื่อมฐานข้อมูล Supabase ของผู้ใช้

CI: https://github.com/EAKAPOL-BDC/EdPEx-SEv1/actions/runs/34999150538

## ช่องว่าง M0–M1

| ข้อกำหนด | สิ่งที่มีใน repository | สิ่งที่ยังต้องส่งมอบ/ตรวจรับ |
|---|---|---|
| M0 catalog ฐาน 63 รหัส | catalog/*.json; tests/test_m0_*; source hashes | ตรวจรายการที่นำเข้าเทียบ catalog รายรหัสและความสัมพันธ์ก่อนเปิดจริง; จำนวนเท่ากันอย่างเดียวไม่เพียงพอ |
| Traceability ข้อ 1–33 | docs/requirements-traceability.md | ตารางเดิมระบุตำแหน่งและระยะ ไม่ใช่หลักฐานผ่านทุกข้อ; ใช้รายงานนี้ประกอบ |
| ต้นแบบ 6 หน้าตามข้อ 29 | หน้า home/login/workspace/members/catalog/detail | หน้าเหล่านี้ไม่เท่ากับต้นแบบทุกบทบาทตามข้อ 29; ยังต้องตรวจหน้าตอบ หลังบ้าน และ dashboard ตามรายการจริง |
| บัญชีและขอบเขต | apps/accounts/models.py, permissions.py, services.py; scoped roles/revocation/expiry | ยังไม่มีชุดสิทธิ์คำนวณ รับรอง เผยแพร่ และ dashboard ครบตามข้อ 4/28/30; ห้ามอนุมานจาก staff/superuser |
| รุ่นคำถามและคำแปล | apps/catalog/models.py, services.py; clone/publish/review/bundle guards | UI จัดการและ semantic review คำแปลยังไม่ครบ; คลังกำลังแสดงต้นฉบับเพื่อทบทวน |
| ปฏิทินและประชากร | Calendar, ReportingPeriod, CollectionRound, PopulationSnapshot/Member, ResponsibilityAssignment, DataSource | ยังขาด collection plans/version/bundle/schedule occurrences และหน้าจัดการครบวงจร |
| ข้อมูลย้อนหลังตั้งแต่ 2565 | DataSource เป็นฐานอ้างอิง | ยังไม่มี historical import batches/rows/result sources และการเลือก raw หรือ aggregate |
| การแจ้งเตือน | ยังไม่พบโมเดลและบริการ notification/outbox ใน apps | ต้องเพิ่ม schema และสิทธิ์ แล้วทำ scheduler/delivery ใน M3; ห้ามส่งข้อความจริงระหว่างพัฒนา |
| ผลลัพธ์และ dashboard | ยังไม่มี calculation run/result/release/disclosure models | ต้องเพิ่ม migration แบบต่อยอดและสิทธิ์ตามระยะ; ไม่ reset DB |
| ภาษาไทย/อังกฤษ | preference, middleware, catalog/glossary, translation bundle, ปุ่มสลับภาษา | คำแปลเครื่องมือยังไม่ผ่านตรวจรับครบ; LANG01–10 ยังไม่ผ่านครบจากการมีปุ่มภาษา |
| CI และ migrations | .github/workflows/test.yml; scripts/test_m1_migrations.py | CI ผ่านเฉพาะความสามารถที่มี tests; ไม่แทน UAT ของฟังก์ชันที่ยังไม่สร้าง |

## ลำดับงาน M2 ที่นำไปพัฒนาได้

1. **แกนคำนวณและข้อมูลจำลอง**: เพิ่มโมดูล Python ใช้ Decimal, stable IDs, ค่าคะแนน/NA/missing แยกชัด; ไม่รับผลคำนวณจาก browser เป็นค่าจริง สร้าง golden tests CAL-01–18 จากข้อ 12 ก่อนเชื่อมข้อมูลจริง
2. **สัญญาข้อมูลและการทำซ้ำ**: migration สำหรับ run/result/source manifest ที่อ้างรุ่นสูตร เครื่องมือ ประชากร cutoff และ engine commit; ผลเดิมไม่เปลี่ยนตามการแก้ต้นทาง สร้างบริการที่ตรวจสิทธิ์ฝั่ง server
3. **รุ่นและ template validation**: ตรวจสูตรกับคำถาม/มาตรา/กลุ่มของรุ่นที่จะใช้; ไม่ยอมรับ arbitrary code หรือสูตรที่ไม่รองรับ
4. **ข้อมูลย้อนหลัง**: แยก raw/aggregate, เก็บวิธีวัดและรุ่นเดิม พร้อม revision/source hash; ห้ามเติมตัวหารที่ไม่มีและห้ามนับสองแหล่งซ้ำ
5. **การรวมผลและเปรียบเทียบ**: รวม n/N หรือ sum/count ที่ระดับถูกต้อง; ไม่เฉลี่ยเปอร์เซ็นต์เปล่า; ตรวจ period/method/unit/version ก่อนรวมไตรมาสและปี
6. **ตรวจรับ M2**: CAL ทั้ง 18 กรณี, สูตรไม่ขึ้นกับภาษา, manifest replay, สิทธิ์ข้าม scope, immutability และ historical/series cases ต้องผ่านจริงก่อนระบุ M2 เสร็จ

ขั้น 1–6 เป็นงานที่ยังต้องทำ ไม่ใช่รายการความสามารถที่ติดตั้งแล้ว

## Golden test checklist

| ID | ประเด็นที่ต้องพิสูจน์ |
|---|---|
| CAL-01 | SAT: 2/3 = 66.67%; แยก NA และ missing |
| CAL-02 | DIS: 1/3 = 33.33%; ไม่ใช้ 100−SAT |
| CAL-03 | ENG: ตัดคนตอบไม่ครบ; 1/2 = 50% |
| CAL-04 | 7.3-36: เกณฑ์รายคนและความครบ; 50% |
| CAL-05 | F04: เฉลี่ยรายคนก่อนเฉลี่ยกลุ่ม; 4.00 |
| CAL-06 | F06 digital: ใช้ประชากรทั้งหมดเป็นตัวหาร; 2/4 = 50% |
| CAL-07 | F06 vision: ทุกข้อถึงเกณฑ์; 1/2 = 50% |
| CAL-08 | F06 values: ตัวอย่างพฤติกรรมไม่กระทบคะแนน; 50% |
| CAL-09 | K_EXTERNAL: เงื่อนไขเคยรับรู้/ความครบ/เฉลย; 50% |
| CAL-10 | H01: ศูนย์เป็นค่าจริง; mean 5.00 |
| CAL-11 | อบรมหลายหมวดไม่คูณชั่วโมงซ้ำ; 1.25 ชม., 25%, 50% |
| CAL-12 | SAFETY_ANY: นับคนไม่ซ้ำ; 50%; แต่ละด้าน 25% |
| CAL-13 | รวมกลุ่มจากตัวตั้ง/ตัวหาร; 20% |
| CAL-14 | NA ทั้งหมด: no_valid_data, value=null |
| CAL-15 | เลือก latest submitted revision ภายใน cutoff |
| CAL-16 | คำตอบเดียวผูกสองตัวชี้วัด ไม่เพิ่มจำนวนคน |
| CAL-17 | M01: valid/NA/missing แยกกัน; mean 4.00 |
| CAL-18 | ดูงานล้วน: ชั่วโมงอบรม 0.00; คนดูงาน 25% |

รายละเอียด input และ expected outputs ใช้ข้อ 12 ใน Blueprint โดยตรง ตารางนี้ไม่แทนต้นฉบับ

## กติกาที่ต้องคงไว้

- F06 เป็น self_report; ไม่เพิ่ม assessor score, reviewer workflow หรือการบังคับหลักฐาน
- F05 ตรวจหลักฐานตามข้อกำหนดเดิม แยกจาก F06
- สูตร 20 นิยามและตัวชี้วัด 63 รหัสไม่เท่ากับ engine ที่ทดสอบแล้ว
- ไม่เผยแพร่ฉบับร่างเพื่อข้ามการตรวจภาษาและคำชี้แจง
- ไม่ seed ซ้ำ ไม่ลบหรือ reset ฐานข้อมูลเพื่อเริ่ม M2
- ไม่ merge/deploy production หรือส่งอีเมลจริงในงานตรวจนี้
