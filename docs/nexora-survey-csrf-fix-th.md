# แก้ CSRF Origin null ในหน้าตอบแบบสำรวจ

สาเหตุ: Referrer-Policy: no-referrer บนหน้าตอบแบบสำรวจทำให้ browser ส่ง Origin: null ใน HTML form POST แล้ว Django ปฏิเสธคำขอ
เปลี่ยนเป็น same-origin เพื่อให้ส่ง Origin ของระบบในการส่งแบบฟอร์ม และไม่ส่ง referrer ข้าม origin
คง CSRF token, origin validation, CSP และการไม่ใส่รหัสคำเชิญ/คำตอบใน URL ไว้
ไม่มี migration ใหม่ ไม่ต้องสร้างรอบหรือตรึงประชากรซ้ำ

## ติดตั้ง
1. แตก ZIP ทั้งหมดไปยัง Downloads/nexora-survey-csrf-fix
2. หยุดเว็บเดิมด้วย Ctrl+C ใน PowerShell เดิม
3. รันคำสั่ง:

```powershell
& "$env:USERPROFILE\EdPEx-Web\EdPEx-SEv1\.venv\Scripts\python.exe" "$env:USERPROFILE\Downloads\nexora-survey-csrf-fix\nexora_web_update.py"
```

4. รอ Starting development server แล้วเปิด http://127.0.0.1:8000/survey/ ใหม่ผ่านแถบที่อยู่ เพื่อโหลดฟอร์มใหม่ ห้ามเพียงส่ง POST เดิมซ้ำ
5. ใส่รหัสคำเชิญเดิมที่ยังไม่หมดอายุหรือถูกยกเลิก หากเป็นการปฏิเสธโดย CSRF ตามภาพ ยังไม่ได้ใช้สิทธิ์ส่งคำตอบ

## การทดสอบ
ผ่าน 3 targeted Django tests: loopback/HTTPS restrictions, sanitized exceptions, และ CSRF token/origin checks ทั้ง HTTP และ HTTPS
ทดสอบ same-origin + token ผ่าน; null origin, foreign origin และไม่มี token ถูกปฏิเสธ 403
ตรวจ response policy เป็น same-origin
ยังไม่ได้ทดสอบ browser จริงบน Windows หรือเชื่อมฐานข้อมูลของผู้ใช้

อ้างอิง: https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Referrer-Policy#effect_on_the_origin_header
