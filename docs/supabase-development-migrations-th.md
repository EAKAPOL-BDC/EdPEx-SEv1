# คู่มือเตรียม Django migrations บน Supabase development

เอกสารนี้เตรียมขั้นตอนให้ผู้ดูแลตรวจรับก่อนติดตั้งจริง งานรอบนี้ยังไม่เชื่อมต่อหรือ apply
ไปยัง Supabase ไม่ reset ข้อมูล และไม่ deploy แอป เริ่มจาก `main` ที่รวม PR #3 แล้ว
โดยคง Django `auth.User`, migrations เดิม และ Blueprint 1.2 / Instruments 1.1 ใน `docs/source/`
F06 ยังคงเป็น self-report ไม่บังคับหลักฐาน และ migrations ไม่เผยแพร่คำแปล draft

## 1. ตั้งค่า GitHub Environment และ secrets

1. หลัง PR นี้ผ่านตรวจรับและรวมเข้า `main` ให้ผู้ดูแล repository เปิด **Settings → Environments**
   สร้างหรือแก้ Environment ชื่อ **`development`** ให้เสร็จก่อนเรียก workflow
2. ใน **Deployment branches and tags** เลือก **Selected branches and tags**
   เพิ่มกฎชนิด **Branch** ชื่อ `main` เท่านั้น ไม่เพิ่ม tag หรือ wildcard
3. ตั้ง **Required reviewers** เป็นผู้ตรวจการติดตั้ง เปิด **Prevent self-review**
   และปิดการข้ามกฎโดย administrator หากตัวเลือกเหล่านี้มีในแพ็กเกจของ repository
   หากไม่มี ให้บันทึกข้อจำกัดและจัดให้ผู้ดูแลอีกคนตรวจ plan/ข้อมูลสำรองก่อนกด apply;
   workflow ไม่สามารถสร้างกฎอนุมัติแทนการตั้งค่านี้ได้
4. ใน **Environment secrets** เพิ่มหรือปรับค่าห้าชื่อด้านล่างให้ชี้ Supabase **development**
   ใช้ชื่อเดิมตาม `edpex/settings.py` และ workflow ตรวจการเชื่อมต่อ ไม่ต้องเพิ่มชื่อ secrets ใหม่

| ชื่อ secret | ค่าที่ผู้ดูแลนำมาจากโครงการ development |
|---|---|
| `SUPABASE_DEV_DB_HOST` | host ของ Direct connection หรือ Session pooler |
| `SUPABASE_DEV_DB_PORT` | port ของโหมดที่เลือก |
| `SUPABASE_DEV_DB_NAME` | ชื่อฐานข้อมูล |
| `SUPABASE_DEV_DB_USER` | ชื่อผู้ใช้ของ endpoint นั้น ซึ่งอาจต่างกันระหว่าง direct/pooler |
| `SUPABASE_DEV_DB_PASSWORD` | รหัสผ่านฐานข้อมูลของผู้ใช้ข้างต้น |

ชื่อทั้งห้ายืนยันจาก source code; คู่มือนี้ไม่ยืนยันว่ามีค่าถูกบันทึกอยู่ใน GitHub แล้ว
ไม่ใช่ Supabase project URL, anon key หรือ service-role API key ผู้ใช้ฐานข้อมูลต้องมีสิทธิ์อ่าน
ตารางเดิมและสร้าง/แก้ตาราง functions และ triggers ของ Django ตามแผนที่ตรวจรับ
ให้ทดสอบสิทธิ์ DDL บนฐานจำลองก่อน เพราะ `SELECT 1` ไม่พิสูจน์สิทธิ์ติดตั้ง

หากมีชื่อเดียวกันใน Repository/Organization secrets ให้ผู้ดูแลทบทวนผู้ใช้งานเดิมก่อนย้ายหรือจำกัด
สิทธิ์ค่าเหล่านั้น การมี Environment secrets อย่างเดียวไม่ได้ถอนการเข้าถึงค่าระดับ repository
จาก workflow อื่น ไม่ใส่ค่า secrets ลง PR, issue, ไฟล์ `.env` ที่ commit หรือภาพหน้าจอ

ทั้ง `plan`, `apply` และ connection checker ใช้ Environment `development`
จึงอาจต้องอนุมัติทุกครั้งตามกฎที่ตั้งไว้ และ GitHub อาจแสดงเป็น deployment record แม้ job นั้น
ตรวจแบบอ่านอย่างเดียว ไม่มีการเผยแพร่แอปจาก workflow นี้
รายละเอียดและข้อจำกัดแพ็กเกจดู [GitHub: Managing environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)

## 2. เลือกการเชื่อมต่อและทดสอบ

1. ใน Supabase development เปิด **Connect** คัดลอกองค์ประกอบของ endpoint ที่เลือกไปเก็บ
   ใน secrets ข้างต้นผ่านหน้าตั้งค่าที่ปลอดภัย อย่าคาดเดา host/username จากชื่อ region
2. ใช้ **Direct connection** เป็นตัวเลือกหลักสำหรับ migrations หาก runner เข้า IPv6 ไม่ได้
   ให้ใช้ **Session pooler** ที่รักษา session เดิม ไม่ใช้ **Transaction pooler**:
   runner นี้ใช้ session read-only และ session advisory lock ซึ่งต้องคงอยู่ข้าม transaction
   ตรวจโหมดจาก endpoint ที่เลือกใน Connect; หมายเลข port อย่างเดียวไม่พิสูจน์โหมดหรือพฤติกรรม session
3. การเชื่อมต่อ Supabase ใน settings และ checker ใช้ `sslmode=require` ซึ่งบังคับเข้ารหัส TLS;
   ยังไม่ได้ตั้ง `verify-full`/root certificate เพื่อตรวจชื่อเซิร์ฟเวอร์ในงานนี้
4. เปิด GitHub **Actions → Test Supabase connection → Run workflow** เลือก `main`
   อนุมัติ Environment หากมี แล้วตรวจข้อความ `Supabase connection check passed (read-only SELECT 1).`

checker ส่ง `SELECT 1` ซึ่งเป็นคำสั่งอ่าน และขอ `default_transaction_read_only=on`
ผ่าน startup options แต่ไม่ได้อ่านกลับเพื่อยืนยันโหมดที่มีผลจริง ไม่เรียก Django migrations
และไม่พิมพ์รหัสผ่าน connection string หรือรายละเอียด exception หากล้มเหลว ให้ผู้ดูแลตรวจ secrets,
โหมด endpoint, DNS/IPv4/IPv6 และกฎเครือข่ายในช่องทางส่วนตัว ไม่เปิด debug เพื่อพิมพ์ค่าออก log
การเลือกโหมดและข้อจำกัด session อ้างอิง [Supabase: Connect to your database](https://supabase.com/docs/guides/database/connecting-to-postgres)

Direct connection เชื่อมกับ PostgreSQL โดยตรง ส่วน Session pooler เป็นทางเลือกสำหรับ IPv4
ที่รองรับ session state รวม `SET` และ session advisory locks; Transaction pooler คืน connection
หลังแต่ละ transaction จึงไม่รองรับข้อกำหนดของ runner นี้
ดู [Supabase: Transaction mode limitations](https://supabase.com/docs/guides/database/connecting-to-postgres#transaction-mode-limitations)
ข้อจำกัดนี้ไม่ใช่ข้อสรุปว่าการใช้ Session pooler เป็นสาเหตุของความล้มเหลวแต่ละครั้ง

### กรณี `session_mode_mismatch` และการลอง plan ใหม่

Actions plan run `34936261291` รายงาน `session_mode_mismatch` ในจุดตรวจโหมดหลังเปิด connection
ด้วย startup options ผู้ดูแลยืนยันว่าใช้ Session pooler และ connection checker ผ่านแล้ว
log เดิมไม่ได้แสดงค่า session ที่อ่านได้จริง จึงยืนยันได้เพียงว่าค่าที่ตรวจไม่ตรงกับโหมดที่ต้องการ
ยังระบุสาเหตุว่าเกิดจาก Supavisor, endpoint หรือการตั้งค่าใดโดยเฉพาะไม่ได้
ผล `SELECT 1` ที่ผ่านไม่ได้พิสูจน์ว่า read-only, search path, timeouts และ autocommit ของ runner
ถูกตั้งและคงอยู่ครบข้าม transaction งานแก้ไขนี้ให้คง endpoint และ secrets ทั้งห้าค่าเดิมไว้

runner ยังคงส่ง startup options เป็นคำขอเริ่มต้น ตรวจว่า autocommit ของทั้ง Django และ driver
เป็น `true` แล้วจึงอ่านค่าก่อนตั้ง session อย่างปลอดภัย จากนั้นตั้งค่าระดับ session
ด้วย `SET SESSION`: `default_transaction_read_only` เป็น `on` สำหรับ plan หรือ `off` สำหรับ apply,
`search_path=public`, `lock_timeout=5000ms` และ `statement_timeout=900000ms`
อ่านยืนยันค่าหลังตั้ง รวม `transaction_read_only` ก่อนขอ advisory lock หรืออ่าน migration plan
หากอ่านหรือตั้งค่าไม่ได้ หรือค่าใดไม่ตรง จะหยุดด้วยผลไม่สำเร็จ ไม่มีการข้ามเงื่อนไขเพื่อทำงานต่อ
`SET SESSION` เปลี่ยนค่าของ connection นี้ ไม่เปลี่ยน schema หรือแถวข้อมูลของแอป
ดู [PostgreSQL: SET](https://www.postgresql.org/docs/17/sql-set.html)
และ [Django: Autocommit](https://docs.djangoproject.com/en/5.2/topics/db/transactions/#autocommit)

ผลสำเร็จมี `session_diagnostics` ใน JSON และ GitHub job summary แบ่งเป็น `expected`, `before`
และ `after` เพื่อเทียบค่าที่ต้องการ ค่าก่อนตั้ง และค่าหลังตั้งตามลำดับ พร้อม `stage` ที่ระบุขั้นตอน
เป็น `preflight`, `startup`, `configure`, `verify` หรือ `verified`
ค่าที่ตรวจแสดงเฉพาะ read-only แบบ `on`/`off` (หรือ `unknown` เมื่อยืนยันไม่ได้), autocommit แบบ boolean,
search path ที่แปลงเป็น `public`/`other` และ timeout เป็นตัวเลขมิลลิวินาที
ไม่แสดง host, port, database, username, password, connection string หรือค่า search path อื่นจริง
เมื่อการตรวจหรือตั้ง session ล้มเหลว log จะแสดงรหัสคงที่พร้อม JSON ของค่าที่อ่านได้
ส่วน `before` หรือ `after` อาจยังว่างหากหยุดก่อนอ่านครบ; ไม่ถือว่าช่องว่างผ่านการตรวจ
ค่า `before` อาจต่างจาก `expected` ได้; การยอมให้ทำงานต่อขึ้นกับการยืนยันค่า `after` ให้ครบตามนี้:

| ค่าที่ตรวจหลังตั้ง session | plan | apply ที่ได้รับอนุมัติแยกต่างหาก |
|---|---|---|
| `default_transaction_read_only` และ `transaction_read_only` | `on` ทั้งคู่ | `off` ทั้งคู่ |
| `django_autocommit` และ `driver_autocommit` | `true` ทั้งคู่ | `true` ทั้งคู่ |
| `search_path` | `public` | `public` |
| `lock_timeout_ms` | `5000` | `5000` |
| `statement_timeout_ms` | `900000` | `900000` |

รหัส `session_autocommit_required` หมายถึง autocommit ไม่พร้อม;
`session_configuration_failed` หมายถึงอ่านหรือตั้งค่า session ไม่สำเร็จ;
`session_mode_mismatch` หมายถึง read-only หลังตั้งไม่ตรง;
`session_settings_mismatch` หมายถึง search path หรือ timeout หลังตั้งไม่ตรง
ให้ใช้ `stage` และค่าที่กรองแล้วประกอบการวิเคราะห์ โดยไม่เดาค่า endpoint จากรหัสเหล่านี้

หลัง PR แก้ session ผ่านการตรวจรับและรวมเข้า `main` โดยได้รับอนุญาตจากผู้ใช้แล้ว
ให้ผู้ดูแลลองเฉพาะ plan ดังนี้:

1. คง Environment `development`, endpoint แบบ Session pooler ที่ยืนยันไว้ และ secrets เดิมทั้งห้า
   ตรวจ SHA เต็ม 40 ตัวของ `main` ล่าสุดที่รวมการแก้ไขแล้ว
2. เปิด **Actions → Supabase development migrations → Run workflow** เพื่อสร้าง run ใหม่
   เลือก branch `main` และ `mode=plan`; อย่าใช้ Re-run jobs ของ run เก่า เพราะจะยังใช้ commit เก่า
3. กรอก `commit_sha` เป็น SHA เต็มล่าสุดข้างต้น เว้น `expected_plan_hash` และ `backup_reference` ว่าง
   หาก `main` เปลี่ยนก่อนสร้าง run ให้ตรวจ SHA ล่าสุดใหม่ ไม่เลือก `apply`
4. อนุมัติ Environment ตามกฎ ตรวจว่า SHA ในผลตรงกับที่เลือก, `session_diagnostics.stage=verified`
   และค่า `after` ตรงกับ `expected` ทุกค่าของ plan ในตาราง จากนั้นตรวจ applied/pending migrations,
   `schema_exceptions`, จำนวน auth และ plan hash ตามข้อ 3 เก็บลิงก์ run กับผลไว้ตรวจรับ
5. หากยัง mismatch หรือยืนยันค่าใดไม่ได้ ให้หยุดและส่งกลับเฉพาะรหัสข้อผิดพลาด
   กับ `session_diagnostics` ที่ runner กรองแล้ว ไม่ส่งค่า secrets หรือรายละเอียด endpoint
   ไม่กด apply หรือเปลี่ยน endpoint เพื่อข้ามปัญหา แม้ plan ผ่านก็ต้องรอการอนุมัติ apply แยกต่างหาก

ขั้นตอนนี้ยังไม่ได้ทดลองกับ Supavisor/Session pooler ของโครงการจริง
เอกสารทางการและผลทดสอบ PostgreSQL ชั่วคราวไม่ยืนยันว่า plan บน endpoint จริงผ่านแล้ว
ต้องดูผล run ใหม่หลังตรวจรับ โดยไม่ตีความผลสำเร็จของ checker เดิมแทนการตรวจ session นี้

## 3. รันและอ่านผล plan

1. เปิด **Actions → Supabase development migrations → Run workflow** เลือก branch `main`
2. คง `mode` เป็น **`plan`** ซึ่งเป็นค่าเริ่มต้น `commit_sha` เว้นว่างได้เพื่อใช้ SHA เต็มของ
   `main` ณ ตอนเริ่ม run หรือกรอก SHA เต็ม 40 ตัวของ commit นั้น ค่าไม่ตรงกับ SHA ของ run จะถูกปฏิเสธ
   ไม่กรอก `expected_plan_hash` หรือ `backup_reference` ในขั้นนี้
3. อนุมัติ Environment ตามกฎ แล้วอ่านผล job `plan` เก็บลิงก์ run และ SHA เต็มไว้ในบันทึกติดตั้ง
4. ตรวจรายการ migrations ที่ใช้แล้วและรายการที่ยังรอติดตั้งพร้อมลำดับ เทียบกับไฟล์ migrations
   ของ commit ที่แสดงในผล อ่านความหมายของตารางใน [คู่มือ M1](m1-schema-th.md)
   ตรวจรายการ `schema_exceptions` ในผล JSON ของ plan และรายการข้อยกเว้นใน GitHub job summary
   ซึ่งระบุ migration, table, column และ operation ที่ยอมให้เปลี่ยนตามแผนอย่างชัดเจน
5. เก็บ **plan hash** จากผล run เพื่อกรอก `expected_plan_hash` ตอน apply
   ตรวจจำนวนบัญชี/กลุ่ม/ความสัมพันธ์สิทธิ์ Django เดิมที่รายงานแบบผลรวมด้วย
   ฐานใหม่อาจยังไม่มีตาราง auth หรือ `django_migrations`: จะยังไม่มีรายการ applied
   และแสดงแผนที่รอติดตั้งทั้งหมด โดยไม่สร้างตาราง ค่า auth count เป็นศูนย์อย่างเดียว
   แยกไม่ได้ว่าตารางยังไม่มีหรือมีแต่ไม่มีข้อมูล ให้ผู้ดูแลเทียบกับ inventory ก่อนติดตั้ง

plan โหลด migration graph และอ่านประวัติฐานข้อมูลใน session แบบ read-only ไม่เรียก migrate,
ไม่บันทึก migration recorder และไม่สร้างฐานทดสอบ ลำดับแผนไม่ใช่การลองรัน DDL
จึงยังไม่ยืนยันว่า DDL จะสำเร็จบนสิทธิ์และข้อมูลจริงของ development
runner กำหนด `search_path=public` สำหรับตาราง Django; หากฐานเดิมวางตาราง Django ใน schema อื่น
ให้หยุดและทบทวนการตั้งค่าก่อน ไม่สร้างชุดตารางซ้ำเพื่อหลบประวัติเดิม

ก่อน apply ให้ผู้ดูแลตรวจการเปิด **Data API / exposed schemas** และ default grants ของโครงการจริง:
สิทธิ์ M1 บังคับผ่านบริการ Django ไม่ใช่ RLS สำหรับเรียกตารางจาก Supabase API โดยตรง
ตารางใน schema ที่เปิด API และมี grants อาจเข้าถึงได้โดยข้ามการตรวจสิทธิ์ Django
ถ้า development ใช้ Django backend อย่างเดียว ให้เตรียมปิด Data API หรือเอา `public` ออกจาก
exposed schemas หลังตรวจผลกระทบต่อผู้ใช้งานเดิม หากต้องใช้ API กับตารางอื่นใน `public`
ต้องจัดแผนแยกและป้องกันตาราง Django ก่อนติดตั้ง ไม่อาศัยชื่อ `development` หรือ API key เป็นสิทธิ์รายองค์กร
งานเตรียมนี้ยังไม่เปลี่ยนการตั้งค่าดังกล่าว และ plan ไม่ยืนยันการปิด Data API ให้
ดู [Supabase: Securing your API](https://supabase.com/docs/guides/api/securing-your-api)
และ [Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security)

ข้อยกเว้น schema ที่รองรับมีเพียงการลบ `django_content_type.name` ตาม
`contenttypes.0002_remove_content_type_name` เมื่อ migration นี้อยู่ในรายการ pending ของแผนจริง
และมี operation `RemoveField(model_name="contenttype", name="name")` ตรงตามที่ตรวจรับ
ผล `schema_exceptions` จะระบุ migration นี้, table `django_content_type`, column `name`
และ operation `remove_column` ซึ่งมาจาก Django operation `RemoveField` ข้างต้น
หากเงื่อนไขไม่ครบ จะไม่มีสิทธิ์ข้ามการตรวจคอลัมน์นี้
การตรวจหลัง apply ยอมรับการลบได้ต่อเมื่อประวัติ `django_migrations` บันทึก migration นี้สำเร็จแล้วด้วย
runner ไม่ข้ามคอลัมน์ที่หายไปแบบทั่วไป และยังตรวจคอลัมน์กับข้อมูลเดิมส่วนที่เหลือครบตามข้อ 6

plan hash ใช้ผูกแผนที่ตรวจรับกับ commit เนื้อหาไฟล์ migrations รุ่น Django สถานะ migrations
และรายการ `schema_exceptions` รวมปลายทาง/ผู้ใช้เชื่อมต่อในรูป hash โดยไม่พิมพ์ค่าต่อฐานข้อมูล;
ไม่ใช่ backup หรือ checksum ของข้อมูลทั้งหมด หากมีการเปลี่ยนสิ่งเหล่านี้ระหว่าง plan กับ apply
ต้องรัน plan ใหม่ อ่านผลใหม่ และใช้ hash ใหม่ ไม่มีตัวเลือกข้ามการตรวจนี้

## 4. เตรียมสำรองและซ้อมกู้คืนข้อมูลเดิม

ให้ผู้รับผิดชอบฐานข้อมูลทำขั้นนี้หลังได้รับอนุญาตสำหรับ development และก่อน apply จริง
บันทึกเจ้าของงาน ช่วงเวลาบำรุงรักษา จุดเวลาสำรอง SHA/plan run และรหัสหลักฐานการซ้อมกู้คืน
รหัสสั้นที่ไม่เป็นความลับ เช่น `DEV-BACKUP-20260915-01` จะใช้เป็น `backup_reference`;
อย่าใส่ URL ที่มี token, connection string หรือข้อมูลบัญชีในช่องนี้

1. ตรวจโครงการและฐานปลายทางโดยผู้ดูแลในช่องทางส่วนตัว หยุดงานที่เขียนฐานข้อมูลระหว่างสำรอง
   จนตรวจหลังติดตั้งเสร็จ รวมการเข้าใช้บัญชีที่ทำให้ `last_login` เปลี่ยน ไม่หยุดบริการหรือข้อมูลโดย
   เดาสถานะจากคู่มือนี้ การหยุดเขียนช่วยให้เปรียบเทียบบัญชีก่อน/หลังได้และกำหนดจุดกู้คืนชัดเจน
2. ตรวจวิธี backup/restore ที่โครงการ Supabase นี้มีจริงและ retention ของมัน เลือกจุดก่อน apply
   ที่กู้คืนได้ บันทึกตำแหน่งปลอดภัย ผู้มีสิทธิ์ และเวลาที่คาดว่าจะสูญเสียข้อมูลหากย้อนกลับ
   database backup ของ Supabase ไม่ครอบคลุมไฟล์วัตถุใน Storage API ต้องสำรองไฟล์และ metadata
   ให้สัมพันธ์กันแยกต่างหาก รวมข้อกำหนด custom roles ตามแผนกู้คืน
   ดู [Supabase: Database Backups](https://supabase.com/docs/guides/platform/backups)
3. เตรียมสำเนาข้อมูล Django รวม `auth_user`, กลุ่ม/สิทธิ์/ตารางเชื่อม,
   `django_migrations`, ตารางธุรกิจ และ audit ไม่ใช่เฉพาะจำนวนแถว
   Django `auth_user` คนละระบบกับ Supabase `auth.users`; workflow นี้ไม่ย้ายหรือแก้บัญชี Supabase Auth
4. สำหรับสำเนาเฉพาะแอป ให้ใช้ PostgreSQL client รุ่นที่รองรับ server และบัญชีที่อ่านข้อมูลครบ
   กำหนด libpq service ชื่อ `edpex_development` ในไฟล์นอก repository พร้อม `sslmode=require`
   เก็บรหัสผ่านใน password file ที่เฉพาะเจ้าของอ่านได้ ไม่อยู่ใน command line/history
   บน Unix ใช้ permission `0600`; บน Windows จำกัด ACL ของไฟล์
   ดู [connection service file](https://www.postgresql.org/docs/17/libpq-pgservice.html)
   และ [password file](https://www.postgresql.org/docs/17/libpq-pgpass.html)

ตัวอย่างนี้ใช้เมื่อผู้ดูแลยืนยันแล้วว่าตารางแอปทั้งหมดอยู่ใน `public` หากมี schema อื่นหรือ
dependencies/large objects ต้องปรับขอบเขตให้ครบก่อนใช้ รันจากพื้นที่สำรองข้อมูลที่ควบคุมสิทธิ์
ไม่ใช่ checkout หรือ GitHub runner:

```text
pg_dump --dbname=service=edpex_development --format=custom --schema=public --file=edpex-app-before.dump
pg_restore --list edpex-app-before.dump > edpex-app-restore.list
```

นี่เป็นสำเนาแอปที่เลือก schema ไม่ใช่สำเนาครบทั้ง Supabase project/roles/Storage
สำรองแบบกำหนด schema อาจไม่รวม dependencies นอก schema ให้ตรวจรายการและซ้อมกู้คืนจริง
ไม่อาศัยเพียงการสร้างไฟล์สำเร็จ ไฟล์ dump มีข้อมูลส่วนบุคคลและ password hashes ให้เข้ารหัส
และเก็บในที่จำกัดสิทธิ์ ไม่แนบกับ PR หรือ GitHub artifact สาธารณะ
พฤติกรรมของเครื่องมือดู [PostgreSQL: pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html)

5. เตรียมฐานเปล่าที่แยกจาก Supabase development สำหรับซ้อมกู้คืน ปิดช่องทางส่งข้อความ/งานอัตโนมัติ
   ตรวจว่า service ชื่อ `edpex_restore_isolated` ชี้เฉพาะฐานซ้อมและใช้ credentials แยก
   จัดเตรียม extensions/roles ที่จำเป็นตาม inventory เปิดไฟล์ `edpex-app-restore.list` เพื่อตรวจรายการ
   ฐาน PostgreSQL ใหม่มักมี `public` ที่ยังว่างอยู่แล้ว: เมื่อยืนยันว่าไม่มีตารางแอปในฐานซ้อม
   ให้เติม `;` หน้ารายการชนิด `SCHEMA - public` เพียงบรรทัดเดียว เพื่อข้ามการสร้าง schema ซ้ำ
   คงรายการตาราง ข้อมูล sequences functions และ triggers ทั้งหมด ไม่ข้ามรายการอื่นเพื่อซ่อน error
   ถ้าฐานซ้อมไม่มี schema นี้ ให้คงบรรทัดเดิมไว้ จากนั้นรัน:

```text
pg_restore --dbname=service=edpex_restore_isolated --use-list=edpex-app-restore.list --no-owner --no-privileges --exit-on-error edpex-app-before.dump
```

ไม่ใช้ `--clean` กับฐานเดิม ตัวอย่างนี้ให้ผู้กู้คืนเป็นเจ้าของ objects และไม่คืน GRANT/REVOKE
จึงต้องตรวจสิทธิ์ฐานข้อมูลแยกจากกลุ่มและสิทธิ์ Django ที่เก็บในตาราง
ดู [PostgreSQL: pg_restore](https://www.postgresql.org/docs/17/app-pgrestore.html)

6. ตรวจบนฐานซ้อมว่าบัญชีเดิมยังมี primary key/ค่ารหัสผ่านเดิม กลุ่ม สิทธิ์สมาชิกและประวัติ
   `django_migrations` ครบ ตรวจรุ่น/คำแปลที่เผยแพร่ ประชากรตรึง และ audit รวมถึงไฟล์ที่สำรองแยก
   เก็บผลเทียบรายละเอียดในที่จำกัดสิทธิ์ ให้บันทึกส่วนกลางเฉพาะผลผ่าน/ไม่ผ่านและรหัสอ้างอิง
   ซ้อมแผนติดตั้งและการกลับไปใช้สำเนากู้คืนจนทราบขั้นตอนและเวลาที่ใช้จริงก่อนอนุมัติ apply

## 5. รัน apply หลังตรวจรับและพร้อมสำรอง

1. เมื่ออนุญาตให้ติดตั้งจริงแล้ว ตรวจว่าไม่มี migration run อื่นและช่วงบำรุงรักษาเริ่มแล้ว
   หาก `main` เปลี่ยนจากตอน plan ให้รัน plan ใหม่กับ commit ล่าสุดก่อน
2. เปิด workflow **Supabase development migrations** อีกครั้ง เลือก `main` และ `mode=apply`
3. กรอก `commit_sha` เป็น SHA เต็ม 40 ตัวที่แสดงใน plan, `expected_plan_hash` เป็น hash ของ
   plan นั้น และ `backup_reference` เป็นรหัสหลักฐานสำรอง/ซ้อมกู้คืนที่ไม่เป็นความลับ
   inputs เหล่านี้แสดงใน metadata ของ workflow จึงห้ามใส่ค่าลับ
4. ผู้ตรวจ Environment ตรวจ SHA, ลิงก์ plan, รายการ migrations, `schema_exceptions`
   และหลักฐานสำรอง ก่อนอนุมัติ
   workflow checkout SHA ตายตัว และปฏิเสธ SHA ที่ไม่ตรงกับ `main` ณ ตอนสร้าง run
5. ติดตาม job `apply` จนจบ อย่ากดยกเลิกหรือเริ่มรันขนานเพื่อแก้อาการรอ
   workflow ใช้ concurrency กลุ่มเดียวของ development และ `cancel-in-progress: false`
   runner ใช้ PostgreSQL advisory lock เพิ่มอีกชั้น แล้วตรวจ plan hash ใหม่หลังได้ lock

apply เป็นงานที่เรียกเองเท่านั้น ไม่ตามหลัง plan อัตโนมัติ และไม่เริ่มจาก push/PR
ไม่มี `--fake`, reset, seed หรือ deploy รวมอยู่ด้วย การกรอก `backup_reference` ไม่ได้สร้าง
หรือตรวจความสมบูรณ์ของ backup ให้แทนผู้ดูแล

หาก apply ล้มเหลว ให้แยกผลสองกรณีจากข้อความที่ไม่มีรายละเอียดข้อมูลหรือการเชื่อมต่อ:

- `Migration execution failed: migration_execution_failed. Earlier migrations may already be committed.`
  หมายถึงคำสั่ง migrate ล้มเหลว โดย migrations ก่อนหน้าที่สำเร็จอาจ commit ไปแล้ว
- `Migrate command completed, but post-apply verification failed: CODE. Committed changes were not rolled back.`
  หมายถึงคำสั่ง migrate จบแล้ว แต่การตรวจหลังติดตั้งไม่ผ่าน รหัส `CODE` เป็นรหัสคงที่ที่ปลอดภัย เช่น
  `legacy_schema_changed` เมื่อตารางหรือคอลัมน์เดิมหายนอกข้อยกเว้น,
  `legacy_auth_changed` เมื่อข้อมูลแถวเดิมเปลี่ยนหรือหาย,
  `migrations_still_pending` เมื่อยังมี migrations ค้าง หรือ
  `post_apply_verification_error` เมื่อการตรวจหลังติดตั้งเกิดข้อผิดพลาดอื่น
  หากเกิด `connection_cleanup_failed` หมายถึงการปลด lock หรือปิด connection ไม่สำเร็จ
  ระบบยังรายงานขั้นตอนที่เกิดปัญหา และไม่อ้างว่าการเปลี่ยนแปลงที่ commit แล้วถูกย้อนกลับ

ทั้งสองกรณีจบด้วย exit code ที่ไม่เป็นศูนย์ และไม่รายงาน apply สำเร็จ
ผลสำเร็จจะออกได้เมื่อ migrate จบ การตรวจหลังติดตั้งผ่าน และรายการ pending ว่างทั้งหมดเท่านั้น
การรันทั้งชุดไม่ใช่ transaction เดียว และการตรวจพบปัญหาไม่ได้ย้อนการเปลี่ยนแปลงที่ commit แล้ว

ให้คงช่วงหยุดเขียนและรัน plan แบบอ่านอย่างเดียวเพื่อดูสถานะจริงหลังล้มเหลว
ตรวจรายการที่ใช้แล้ว/ที่ยัง pending เทียบกับผล run และหลักฐานสำรอง จากนั้นวิเคราะห์และแก้สาเหตุ
ก่อนรัน plan ใหม่อีกครั้ง ตรวจรับ SHA, hash, รายการ migrations และ `schema_exceptions` ใหม่
แล้วจึง apply ตามขั้นตอนอนุมัติเดิม ห้ามนำ hash หรือข้อยกเว้นจากแผนที่ล้มเหลวมาใช้ต่อโดยอัตโนมัติ:
ข้อยกเว้นต้องมาจาก migrations ที่ยัง pending จริงในแผนใหม่ หาก contenttypes migration ข้างต้น
commit ไปแล้ว แผนใหม่จะไม่อนุญาตข้อยกเว้นการลบ `name` ซ้ำ
plan ที่ผ่านหรือ pending ที่ว่างไม่ได้ยืนยันย้อนหลังว่าข้อมูลก่อน run ที่ล้มเหลวยังคงครบ
จึงต้องเทียบข้อมูลเดิมกับหลักฐานสำรองในช่องทางส่วนตัวก่อนรับผลและเปิดการเขียนอีกครั้ง

ห้ามใช้ `--fake`, reset หรือย้อน migration เพื่อทำให้การตรวจผ่านโดยไม่วิเคราะห์
หากต้องใช้แผนกู้คืนที่ซ้อมไว้ ให้ผู้ดูแลประเมินจุดข้อมูลที่จะสูญเสียและขออนุมัติการกู้คืนจริง
ก่อนเปลี่ยนปลายทาง งานนี้ไม่มีคำสั่ง restore ฐานจริงอัตโนมัติ

## 6. ตรวจ migrations และบัญชีเดิมหลังติดตั้ง

1. ตรวจว่า apply จบสำเร็จและ SHA ในผลตรงที่อนุมัติ runner เปรียบเทียบข้อมูล auth เดิมก่อน/หลัง
   ในหน่วยความจำและรายงานผลรวม ไม่พิมพ์ usernames, อีเมล หรือ password hashes
   ตรวจ primary key/ค่ารหัสผ่านเดิม กลุ่ม สิทธิ์ ตารางเชื่อมความสัมพันธ์ และแถวประวัติ migrations เดิม
   อย่างเคร่งครัด รวมข้อมูลเดิมของ `django_content_type` ในคอลัมน์ที่ยังคงอยู่
   ยอมให้ลบเฉพาะ `django_content_type.name` ตามข้อยกเว้นที่ตรวจรับใน plan และยืนยันประวัติติดตั้งแล้ว
   หากตารางหรือคอลัมน์เดิมหายนอกข้อยกเว้น หรือแถวเดิมส่วนที่ต้องรักษาถูกแก้ไข/ลบ จะถือว่าไม่ผ่าน
   การเพิ่มข้อมูลระบบตาม migrations ไม่ได้อนุญาตให้แก้แถวเดิม; การตรวจพบไม่ได้ย้อน migrations ที่ commit ไปแล้ว
2. รัน `plan` อีกครั้งที่ commit เดียวกัน รายการ pending ต้องว่าง ประวัติที่เคยใช้แล้วต้องยังอยู่
   เก็บลิงก์ผลตรวจคู่กับ apply run และ backup reference
3. ผู้ดูแลตรวจบัญชีเดิมในช่องทางส่วนตัว: primary key/รหัสผ่าน/กลุ่ม/สิทธิ์เดิมและ membership/grant
   ใช้บัญชีทดสอบที่ได้รับอนุญาตยืนยันการเข้าใช้และขอบเขตข้อมูลเมื่อมีบริการพร้อมทดสอบ
   อย่าสร้าง superuser ใหม่หรือ reset password เพียงเพื่อทำให้การตรวจผ่าน
4. ตรวจตารางธุรกิจ ประวัติ audit รุ่นคำแปล และประชากรที่ตรึงตามแผน M1
   migrations ไม่สร้างองค์กร/บทบาทผู้ใช้จำลอง ไม่ seed ทะเบียน และไม่รับรองคำแปลอังกฤษให้เอง
5. ให้ผู้รับผิดชอบรับผลก่อนเปิดการเขียนข้อมูลอีกครั้ง เก็บหลักฐานติดตั้งโดยไม่แนบข้อมูลบัญชีจริง

## ขอบเขตที่ทดสอบและข้อจำกัด

ซ้อมคำสั่ง backup/restore ในคู่มือนี้บน PostgreSQL 17.11 ชั่วคราวด้วยข้อมูลจำลองแล้ว:
หลังปรับ TOC เฉพาะ `SCHEMA - public` ที่ฐานเปล่ามีอยู่เดิม การ dump/list/restore ผ่านทั้งหมด
เทียบข้อมูลครบ 38 ตาราง 201 แถว นิยามคอลัมน์ และค่า 9 sequences ตรงกัน รวมบัญชีเดิมหนึ่งบัญชี
รหัสผ่านที่ hash ไว้ กลุ่ม/สิทธิ์ และ migration history 28 รายการ ต้นทางไม่เปลี่ยน
ผลนี้ไม่ยืนยันการกู้คืน managed roles, ACL, Storage หรือข้อมูลจริงบน Supabase

ผลทดสอบ PostgreSQL ชั่วคราวของการเปลี่ยนครั้งนี้ให้ดูใน PR พร้อม commit ที่ทดสอบ
CI ที่ไม่ใช้ secrets ตรวจ runner/workflow ได้ แต่ไม่พิสูจน์ DNS/TLS สิทธิ์ฐานข้อมูลจริง
การตั้งค่า Environment หรือความสมบูรณ์ของ backup ของ Supabase development

ผล checker ที่ผู้ดูแลแจ้งในข้อ 2 ไม่ยืนยันการตั้งค่า session ของ migration runner หรือความพร้อมของ backup
งานแก้ session นี้ยังไม่ได้เชื่อมต่อ ทดสอบ Supavisor จริง หรือ apply ไปยัง Supabase
การลอง plan ใหม่และขั้นตอนติดตั้งจริงต้องทำหลังตรวจรับตามสิทธิ์ของผู้ดูแล
ไม่ใช้ `manage.py test` หรือสคริปต์สร้างฐานทดสอบกับ profile Supabase
และไม่ใช้ Supabase CLI migrations จัดการตารางเดียวกับ Django
