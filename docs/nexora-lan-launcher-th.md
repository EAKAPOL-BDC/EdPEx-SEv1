# ตัวเปิด NEXORA สำหรับทดสอบ LAN

ใช้แก้กรณี Required environment variable is missing: SUPABASE_DEV_DB_HOST เมื่อเปิดจาก PowerShell ใหม่ ค่าที่กรอกในตัวติดตั้งเดิมอยู่เฉพาะกระบวนการนั้นและไม่ได้บันทึกถาวร

ดาวน์โหลด start_nexora_lan.py ลง Downloads แล้วรันจาก PowerShell:

```powershell
& "$env:USERPROFILE\EdPEx-Web\EdPEx-SEv1\.venv\Scripts\python.exe" "$env:USERPROFILE\Downloads\start_nexora_lan.py" --ip 10.51.72.130
```

ตัวเปิดตั้งต้นใช้โฟลเดอร์ EdPEx-Previews\NEXORA-WEB-c975590a70 ตามรุ่นที่ตรวจพบในภาพ หากย้ายที่ติดตั้งหรือเปลี่ยนรุ่น ให้เพิ่ม --project ตามด้วยพาธจริงในเครื่องหมายคำพูด

กรอก Host, Port, Database name, Database user และ Database password จากชุดเชื่อมต่อ development เดิมทีละช่อง รหัสผ่านจะไม่แสดงขณะพิมพ์หรือบันทึกลงไฟล์ Host เป็นชื่อโฮสต์ฐานข้อมูล ไม่ใช่ IP เครื่อง Windows และ Database user ไม่ใช่บัญชี edpexadmin เมื่อเปิด PowerShell ใหม่อาจต้องกรอกใหม่

เมื่อเห็น Starting development server เปิด http://10.51.72.130:8000/workspace/ จากเครื่องในวง LAN โดยคงหน้าต่างตัวเปิดไว้และอนุญาต Firewall TCP 8000 สำหรับเครือข่ายทดสอบตามขั้นตอนเดิม กด Ctrl+C เพื่อหยุด เปลี่ยน IP ในคำสั่งหากเครื่องได้รับ IP ใหม่

ตัวเปิดไม่ติดตั้งรุ่นใหม่ ไม่ทำ migration ไม่เปลี่ยนบัญชีหรือ Firewall และไม่ปิดข้อกำหนด HTTPS ของ /survey/ การทดสอบแบบสำรวจผ่านเครื่องอื่นยังต้องใช้ HTTPS ใช้ตัวเปิดนี้กับ development และข้อมูลสาธิตในเครือข่ายที่เชื่อถือได้เท่านั้น

ผ่าน unit tests 6 กรณีโดยจำลองการเปิด subprocess ไม่ได้เชื่อมฐานข้อมูลจริงหรือทดสอบบน Windows ของผู้ใช้
