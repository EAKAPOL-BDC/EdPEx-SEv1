# การตั้งค่า Django และ Supabase (ยังไม่เปิดใช้งานจริง)

โครงการอ้างอิง System Blueprint 1.2 และเครื่องมือ 1.1 โดยคงขอบเขตไทย–อังกฤษ F01–F06;
F06 เป็นการประเมินตนเองและ **ไม่บังคับแนบหลักฐาน** เอกสารนี้ไม่ใช่ขั้นตอน deploy

## หลักการฐานข้อมูล

- ใช้ Django migrations เป็นแหล่งหลักเพียงระบบเดียวสำหรับโครงสร้างตารางของแอป
- ชุดทดสอบปกติใช้ PostgreSQL ชั่วคราวผ่านตัวแปร `POSTGRES_*` และห้ามตั้ง
  `DJANGO_DATABASE_PROFILE=supabase` ในงานทดสอบ
- การตั้ง `DJANGO_DATABASE_PROFILE=supabase` ทำให้ Django อ่านค่าจาก
  `SUPABASE_DEV_DB_HOST`, `SUPABASE_DEV_DB_PORT`, `SUPABASE_DEV_DB_NAME`,
  `SUPABASE_DEV_DB_USER` และ `SUPABASE_DEV_DB_PASSWORD` พร้อมบังคับ TLS
- ห้ามใช้ Supabase CLI migration หรือระบบ migration อื่นสร้างตารางเดียวกับ Django

## ตรวจด้วย PostgreSQL ชั่วคราว

เตรียม PostgreSQL แยกต่างหาก แล้วกำหนด `POSTGRES_HOST`, `POSTGRES_PORT`,
`POSTGRES_DB`, `POSTGRES_USER` และ `POSTGRES_PASSWORD` จากนั้นรัน:

```bash
python manage.py check
python manage.py migrate --noinput
python manage.py test
```

Workflow `Test` ทำขั้นตอนนี้อัตโนมัติกับ PostgreSQL service container โดยไม่อ่าน secrets ของ Supabase

## กดตรวจ Supabase แบบอ่านอย่างเดียว

1. เปิดแท็บ **Actions** ของ repository
2. เลือก **Test Supabase connection**
3. กด **Run workflow** เลือก branch ที่ต้องการ แล้วกด **Run workflow** อีกครั้ง
4. ตรวจว่า step `Run read-only connection check` แสดงข้อความว่าสำเร็จ

Workflow นี้ทำงานเมื่อกด `workflow_dispatch` เท่านั้น ใช้ TLS เปิด transaction แบบ read-only
และส่งคำสั่ง `SELECT 1` เพียงคำสั่งเดียว ไม่รัน Django migrations ไม่สร้างฐานทดสอบ
และไม่สร้าง แก้ไข หรือลบตาราง/ข้อมูล สคริปต์ไม่พิมพ์รหัสผ่าน connection string
ค่าตัวแปรทั้งหมด หรือรายละเอียด exception ที่อาจมีข้อมูลเชื่อมต่อ
