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
3. การเชื่อมต่อ Supabase ใน settings และ checker ใช้ `sslmode=require` ซึ่งบังคับเข้ารหัส TLS;
   ยังไม่ได้ตั้ง `verify-full`/root certificate เพื่อตรวจชื่อเซิร์ฟเวอร์ในงานนี้
4. เปิด GitHub **Actions → Test Supabase connection → Run workflow** เลือก `main`
   อนุมัติ Environment หากมี แล้วตรวจข้อความ `Supabase connection check passed (read-only SELECT 1).`

checker ส่ง `SELECT 1` ใน transaction อ่านอย่างเดียว ไม่เรียก Django migrations และไม่พิมพ์
รหัสผ่าน connection string หรือรายละเอียด exception หากล้มเหลว ให้ผู้ดูแลตรวจ secrets,
โหมด endpoint, DNS/IPv4/IPv6 และกฎเครือข่ายในช่องทางส่วนตัว ไม่เปิด debug เพื่อพิมพ์ค่าออก log
การเลือกโหมดและข้อจำกัด session อ้างอิง [Supabase: Connect to your database](https://supabase.com/docs/guides/database/connecting-to-postgres)

## 3. รันและอ่านผล plan

1. เปิด **Actions → Supabase development migrations → Run workflow** เลือก branch `main`
2. คง `mode` เป็น **`plan`** ซึ่งเป็นค่าเริ่มต้น `commit_sha` เว้นว่างได้เพื่อใช้ SHA เต็มของ
   `main` ณ ตอนเริ่ม run หรือกรอก SHA เต็ม 40 ตัวของ commit นั้น ค่าไม่ตรงกับ SHA ของ run จะถูกปฏิเสธ
   ไม่กรอก `expected_plan_hash` หรือ `backup_reference` ในขั้นนี้
3. อนุมัติ Environment ตามกฎ แล้วอ่านผล job `plan` เก็บลิงก์ run และ SHA เต็มไว้ในบันทึกติดตั้ง
4. ตรวจรายการ migrations ที่ใช้แล้วและรายการที่ยังรอติดตั้งพร้อมลำดับ เทียบกับไฟล์ migrations
   ของ commit ที่แสดงในผล อ่านความหมายของตารางใน [คู่มือ M1](m1-schema-th.md)
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

plan hash ใช้ผูกแผนที่ตรวจรับกับ commit เนื้อหาไฟล์ migrations รุ่น Django และสถานะ migrations
รวมปลายทาง/ผู้ใช้เชื่อมต่อในรูป hash โดยไม่พิมพ์ค่าต่อฐานข้อมูล; ไม่ใช่ backup หรือ checksum
ของข้อมูลทั้งหมด หากมีการเปลี่ยนสิ่งเหล่านี้ระหว่าง plan กับ apply
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
4. ผู้ตรวจ Environment ตรวจ SHA, ลิงก์ plan, รายการ migrations และหลักฐานสำรอง ก่อนอนุมัติ
   workflow checkout SHA ตายตัว และปฏิเสธ SHA ที่ไม่ตรงกับ `main` ณ ตอนสร้าง run
5. ติดตาม job `apply` จนจบ อย่ากดยกเลิกหรือเริ่มรันขนานเพื่อแก้อาการรอ
   workflow ใช้ concurrency กลุ่มเดียวของ development และ `cancel-in-progress: false`
   runner ใช้ PostgreSQL advisory lock เพิ่มอีกชั้น แล้วตรวจ plan hash ใหม่หลังได้ lock

apply เป็นงานที่เรียกเองเท่านั้น ไม่ตามหลัง plan อัตโนมัติ และไม่เริ่มจาก push/PR
ไม่มี `--fake`, reset, seed หรือ deploy รวมอยู่ด้วย การกรอก `backup_reference` ไม่ได้สร้าง
หรือตรวจความสมบูรณ์ของ backup ให้แทนผู้ดูแล

หาก apply ล้มเหลว ให้คงช่วงหยุดเขียน ตรวจผลและรัน plan แบบอ่านอย่างเดียวเพื่อทราบรายการที่ใช้แล้ว
Django อาจ commit migrations ก่อนหน้าที่สำเร็จแล้ว การรันทั้งชุดไม่ใช่ transaction เดียว
จึงอย่าอ้างว่าล้มเหลวแล้วฐานกลับสภาพเดิมทั้งหมด ห้ามใช้ `--fake` แก้ชื่อให้ตรงหรือย้อน migration
โดยไม่วิเคราะห์ ให้ผู้ดูแลตัดสินใจแก้ไปข้างหน้าหรือใช้แผนกู้คืนที่ซ้อมไว้ บันทึกจุดข้อมูลที่จะสูญเสีย
และขออนุมัติการกู้คืนจริงก่อนเปลี่ยนปลายทาง งานนี้ไม่มีคำสั่ง restore ฐานจริงอัตโนมัติ

## 6. ตรวจ migrations และบัญชีเดิมหลังติดตั้ง

1. ตรวจว่า apply จบสำเร็จและ SHA ในผลตรงที่อนุมัติ runner เปรียบเทียบข้อมูล auth เดิมก่อน/หลัง
   ในหน่วยความจำและรายงานผลรวม ไม่พิมพ์ usernames, อีเมล หรือ password hashes
   หากพบข้อมูลเดิมเปลี่ยนจะถือว่าไม่ผ่าน; การตรวจพบไม่ได้ย้อน migrations ที่ commit ไปแล้ว
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

คู่มือนี้ไม่ยืนยันว่าได้ตั้ง Environment, กรอก secrets, ทดสอบเชื่อมต่อจริง หรือซ้อมกู้คืนข้อมูลจริงแล้ว
ขั้นตอนเหล่านั้นต้องทำหลังตรวจรับตามสิทธิ์ของผู้ดูแล ไม่ใช้ `manage.py test` หรือสคริปต์สร้างฐานทดสอบ
กับ profile Supabase และไม่ใช้ Supabase CLI migrations จัดการตารางเดียวกับ Django
