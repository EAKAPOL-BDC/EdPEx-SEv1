# เพิ่มสิทธิ์ส่งชุดผลเข้าตรวจ

ตามการยืนยันของเจ้าของระบบ: เพิ่ม result.submit และ calculation.validate ให้ edpexadmin เฉพาะขอบเขต fc064809-6564-4f74-b303-c32026f82511 ไม่รวมขอบเขตย่อย ไม่กำหนดวันสิ้นสุด เพิ่มบทบาทใหม่ result-submitter-v1 โดยไม่เปลี่ยนบทบาทเดิม ไม่เพิ่มสิทธิ์ result.review หรือ result.approve และไม่ส่งชุดผลเข้าตรวจให้อัตโนมัติ

ต้องเป็นบัญชี Django superuser ที่ active และสมาชิกองค์กรที่มี role.manage ใน scope นี้อยู่แล้ว การตั้งค่าเป็นคำสั่งผู้ดูแลเครื่อง ไม่เปิดผ่านเว็บ ไม่เปลี่ยนกฎมอบสิทธิ์ของเว็บ

1. แตก ZIP ไปยัง Downloads/nexora-result-submitter
2. หยุดเว็บด้วย Ctrl+C แล้วรันใน PowerShell เดิม:

```powershell
& "$env:USERPROFILE\EdPEx-Web\EdPEx-SEv1\.venv\Scripts\python.exe" "$env:USERPROFILE\Downloads\nexora-result-submitter\setup_result_submitter.py" --apply
```

ละ --apply หากต้องการ preview เท่านั้น
ไม่มี migration ใหม่ รันซ้ำไม่เพิ่มรายการสิทธิ์ซ้ำ บันทึก audit event เมื่อเพิ่มจริง จากนั้นเปิดเว็บ
รีเฟรชหน้าชุดผลที่คำนวณแล้ว ตรวจข้อมูลและใช้ปุ่มส่งตรวจ ไม่ต้องคำนวณซ้ำ
ผู้รับรองใช้บัญชีอื่นตามกฎเดิม สิทธิ์รับรองไม่รวมในชุดนี้
เพิกถอนได้ที่ สมาชิกและบทบาท โดยเพิกถอนรายการ result-submitter-v1 ในขอบเขตนี้ ประวัติยังอยู่

ทดสอบบนฐานจำลอง: preview ไม่เขียน, grant จำกัดสิทธิ์และ scope, audit, idempotency, ปฏิเสธ non-superuser/ไม่มี role.manage/role definition ไม่ตรง และทดสอบคำสั่ง calculation เดิม ไม่มีการเข้าถึงฐานข้อมูลผู้ใช้ระหว่างตรวจสอบ
