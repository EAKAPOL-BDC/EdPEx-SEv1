# ข้อยกเว้นการรับรองชุดผลของ edpexadmin

เพิ่มตามคำสั่งเจ้าของระบบให้ edpexadmin รับรองชุดผลที่ตนเองคำนวณหรือส่งตรวจได้ เฉพาะ scope fc064809-6564-4f74-b303-c32026f82511
ต้องเป็น active superuser และมีบทบาท system-administrator-v1 ที่ยังไม่หมดอายุ/ถูกเพิกถอน พร้อมสิทธิ์ role.manage, result.review, result.approve, calculation.validate และสมาชิก/ขอบเขตยัง active

หน้าเว็บแจ้งเมื่อใช้ข้อยกเว้น ผู้ดูแลต้องระบุเหตุผลการตัดสินใจ ระบบเติม [ADMIN SELF-REVIEW] ในประวัติและบันทึก administrator_self_review ใน audit log ไม่มีการรับรองให้อัตโนมัติ ไม่เปลี่ยนคำตอบ/สูตร/ชุดผลเดิม และไม่เผยแพร่ผลโดยอัตโนมัติ
เงื่อนไข token ของชุดผล, ประวัติแก้ไขผล และประวัติที่ห้ามแก้ย้อนหลังยังคงเดิม ทั้ง model, service และ PostgreSQL ตรวจข้อยกเว้นเดียวกัน

## ติดตั้ง
1. แตก ZIP ไปยัง Downloads/nexora-admin-self-review
2. หยุดเว็บเดิม Ctrl+C แล้วใช้ PowerShell เดิม:

```powershell
& "$env:USERPROFILE\EdPEx-Web\EdPEx-SEv1\.venv\Scripts\python.exe" "$env:USERPROFILE\Downloads\nexora-admin-self-review\nexora_web_update.py" --apply-schema
```

มี migration ใหม่ calculations.0006_admin_self_review เปลี่ยนเงื่อนไข trigger และเพิ่ม function ตรวจข้อยกเว้น ไม่แก้ข้อมูลเดิม
ต้องตั้งค่า system-administrator-v1 จากชุดก่อนหน้าแล้ว ชุดนี้ไม่มอบสิทธิ์ใหม่
เปิดหน้าชุดผลเดิมและรีเฟรช ตรวจข้อมูล จากนั้นระบุเหตุผลที่ใช้ข้อยกเว้น เลือกรับรองหรือส่งกลับ และบันทึกผลการตรวจ
เมื่อเพิกถอนบทบาทผู้ดูแลหรือระงับบัญชี ข้อยกเว้นหยุดใช้ได้ทันที ประวัติเดิมยังอยู่
