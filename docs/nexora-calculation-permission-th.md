# ตั้งค่าสิทธิ์คำนวณผล

ชุดนี้เตรียมตามการยืนยันของเจ้าของระบบ ให้ edpexadmin ได้ calculation.run เฉพาะ scope fc064809-6564-4f74-b303-c32026f82511 ไม่มีขอบเขตย่อยและไม่กำหนดวันสิ้นสุด ไม่เพิ่มสิทธิ์ source, submit, review หรือ approve

คำสั่งต้องทำจากเครื่องผู้ดูแลที่เชื่อมฐาน development อยู่แล้ว โดยบัญชีเป้าหมายต้องเป็น active Django superuser และสมาชิกที่มี role.manage ในขอบเขตนี้ บันทึก audit event ทุกครั้งที่เพิ่มสิทธิ์จริง รันซ้ำไม่เพิ่มรายการซ้ำ ไม่เปลี่ยนบทบาทเดิม ไม่มี migration ใหม่

1. แตก ZIP ไปยัง Downloads/nexora-calculation-permission
2. หยุดเว็บด้วย Ctrl+C แล้วใช้ PowerShell เดิมรัน:

```powershell
& "$env:USERPROFILE\EdPEx-Web\EdPEx-SEv1\.venv\Scripts\python.exe" "$env:USERPROFILE\Downloads\nexora-calculation-permission\setup_calculation.py" --apply
```

หากต้องการตรวจรายการก่อน ให้ละ --apply ซึ่งจะไม่บันทึกสิทธิ์และไม่เปิดเว็บ
เมื่อสำเร็จ ตัวเปิดเว็บจะเริ่มทำงาน รีเฟรชรอบ F03-ST1-2569 ที่ปิดรับแล้ว เลือก เตรียมคำนวณจากคำตอบที่ส่งแล้ว
ไม่ต้องสร้างรอบหรือส่งคำตอบซ้ำ หากคำสั่งปฏิเสธเพราะบัญชีไม่ใช่ superuser หรือไม่มี role.manage ให้ส่งข้อความผิดพลาดให้ผู้ดูแลตรวจสอบ ไม่แก้ฐานข้อมูลข้ามเงื่อนไข

การเพิกถอน: ผู้มี role.manage ใช้หน้า สมาชิกและบทบาท เพิกถอนรายการ calculation-operator-v1 ของบัญชีและขอบเขตนี้ ประวัติยังคงอยู่

การตรวจสอบ: ทดสอบ preview ไม่เขียนข้อมูล, grant เฉพาะสิทธิ์และ scope, audit, รันซ้ำ, ปฏิเสธผู้ไม่ใช่ superuser/ไม่มี role.manage และ role ที่นิยามผิด ไม่มีการเชื่อมต่อฐานผู้ใช้ระหว่างทดสอบ
