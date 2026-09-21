"""Field-specific assistance, separate from validators and submitted values."""
GUIDES = {
 'name': ('ชื่อที่แสดงให้เจ้าหน้าที่ใช้แยกพื้นที่ การแก้ชื่อไม่ย้ายข้อมูลระหว่างองค์กร / Display name identifying this workspace; renaming does not move data between organisations.', 'วิทยาลัยการศึกษา / School of Education'),
 'first_name': ('ชื่อเจ้าหน้าที่ตามข้อมูลที่รับรอง ไม่ใช้ชื่อผู้ตอบสาธารณะ / Staff first name from approved records; public respondents need no account.', ''),
 'last_name': ('นามสกุลเจ้าหน้าที่ เพื่อให้ผู้ดูแลแยกบัญชีได้ถูกต้อง / Staff surname to distinguish accounts correctly.', ''),
 'email': ('อีเมลติดต่อของเจ้าหน้าที่ตามนโยบายหน่วยงาน ไม่ใช่ช่องเก็บอีเมลผู้ตอบ / Staff contact email under institutional policy, not respondent email.', 'name@example.org (ตัวอย่างเท่านั้น / example only)'),
 'password2': ('กรอกรหัสเดียวกับช่องรหัสผ่านเริ่มต้น อย่าส่งรหัสผ่านในแชตหรือคู่มือ / Repeat the initial password; never share passwords in chats or manuals.', ''),
 'appointment_kind': ('เลือกดำรงตำแหน่งหรือรักษาการให้ตรงคำสั่งในช่วงเวลานี้ / Choose substantive or acting to match the appointment order for this period.', ''),
 'targets': ('เลือกเฉพาะรายการที่ตรวจครบและตรึงแล้ว สำหรับรอบสาธารณะบุคลากรต้องครอบคลุมทุกผู้บริหารทุกตำแหน่ง / Use reviewed, frozen targets. Public staff collections cover all leaders and positions.', ''),
 'source': ('เลือกรายการต้นทางที่มีอยู่ ตรวจปีและพื้นที่ก่อนคัดลอก / Select the existing source and check its year and workspace before copying.', ''),
 'change_date': ('วันแรกที่ข้อมูลหรือผู้ดำรงตำแหน่งใหม่เริ่มมีผล ต้องไม่ทำให้ช่วงเวลาทับซ้อน / First effective date of the new appointment or details; periods must not overlap.', ''),
 'new_person': ('ผู้ดำรงตำแหน่งตั้งแต่วันเปลี่ยน เลือกจากทะเบียนบุคลากรที่เตรียมไว้ / Person taking the position on the effective date, selected from the people register.', ''),

 'code': ('ใช้ชื่อหรือรหัสที่แยกรายการนี้จากรายการอื่น และค้นหาได้ในภายหลัง / Use a distinct, searchable name or code.', 'รอบ F01 ประสบการณ์นิสิต 2569 ครั้งที่ 1 / F01 Student experience 2026 – collection 1'),
 'period': ('เลือกปีที่ต้องการนำผลไปสรุป ไม่ใช่วันเปิดรับคำตอบ F01 ใช้ปีการศึกษา; F02–F06 ใช้ปีงบประมาณ / Select the reporting year. F01 uses academic years; F02–F06 use fiscal years.', 'ปีการศึกษา 2569 สำหรับ F01 / Academic year 2569 (B.E.) for F01'),
 'owner': ('เจ้าหน้าที่ผู้รับผิดชอบติดตามรอบ ต้องมีบัญชีและสิทธิ์ในพื้นที่นี้ / The staff member responsible for this collection must have an account and scoped access.', 'เลือกบัญชีเจ้าหน้าที่ที่ได้รับมอบหมาย / Choose the assigned operator account'),
 'bundle': ('เลือกชุดแบบประเมินและคำแปลที่ตรวจและเผยแพร่แล้ว หากไม่มีตัวเลือกให้ตรวจคลังแบบฟอร์มก่อน / Choose reviewed, published wording. If empty, complete form-library review first.', 'F01 และชุดคำแปลไทย–อังกฤษที่รับรองแล้ว / F01 with approved Thai–English wording'),
 'open_at': ('วันและเวลาแรกที่ผู้ตอบส่งแบบประเมินได้ ใช้เวลาไทย UTC+7 / First permitted submission time, Thailand time (UTC+7).', '1 ต.ค. 2026 เวลา 08:30 / 1 Oct 2026, 08:30'),
 'due_at': ('กำหนดส่งที่แจ้งผู้ตอบ ต้องไม่ก่อนวันเปิดและไม่หลังวันปิด / Communicated deadline, between opening and closing.', '25 ต.ค. 2026 เวลา 16:30 / 25 Oct 2026, 16:30'),
 'close_at': ('หลังเวลานี้ไม่รับคำตอบใหม่ ควรเว้นเวลาจากกำหนดส่งตามนโยบายหน่วยงาน / Submissions stop at this time; allow a grace period only if intended.', '31 ต.ค. 2026 เวลา 23:59 / 31 Oct 2026, 23:59'),
 'privacy_notice': ('แจ้งวัตถุประสงค์ ผู้เข้าถึงข้อมูล ระยะเก็บ และช่องทางติดต่อ ให้ตรงกับการใช้งานจริง / State the purpose, access, retention and contact details for this collection.', 'ใช้สรุปเพื่อปรับปรุงบริการ ไม่กรอกชื่อในคำตอบ เจ้าหน้าที่ที่ได้รับมอบหมายดูข้อมูลตามสิทธิ์ ระบุระยะเก็บและผู้ติดต่อก่อนเผยแพร่ / Used to improve services. Do not enter names. Specify actual retention and a contact before publication.'),
 'reason': ('บันทึกเหตุผลให้ตรวจย้อนหลังได้ โดยเฉพาะเมื่อแก้ข้อมูลเดิม / Explain the change for the audit history, especially when editing an existing record.', 'แก้ชื่อภาษาอังกฤษให้ตรงกับเอกสารที่รับรอง / Correct the English name to match the approved document'),
 'group': ('เลือกกลุ่มที่รอบนี้เปิดให้ตอบ แยกรอบเมื่อบริบทหรือหน่วยนับต่างกัน / Select the respondent group; separate rounds for different contexts or counting units.', 'C1 นิสิตปริญญาตรี หรือ ST2 บุคลากรสายสนับสนุน / C1 undergraduates or ST2 support staff'),
 'group_code': ('เลือกกลุ่มตามทะเบียนกลาง ผู้ตอบจะเลือกกลุ่มนี้ที่หน้าสาธารณะ / Use the registered group that respondents select on the public page.', 'ST1 สายวิชาการ; ST2 สายสนับสนุน / ST1 academic staff; ST2 support staff'),
 'counting_unit': ('หน่วยที่ใช้ตีความจำนวนคำตอบ ต้องตรงกับบริบทและตัวหารของรอบ / The unit used to interpret response counts must match the context and denominator.', 'บุคคล สำหรับความคิดเห็นรายบุคคล / Person for individual feedback'),
 'context_th': ('ชื่อบริบทที่ผู้ตอบเห็น เช่น หลักสูตร โครงการ หรือบริการ ไม่ใช้ชื่อผู้ตอบ / Respondent-visible programme, project or service context; never a respondent name.', 'ประสบการณ์นิสิต สาขาวิชาการประถมศึกษา / Primary Education student experience'),
 'context_en': ('คำแปลของบริบทเดียวกับภาษาไทย เพื่อให้ทั้งสองภาษาเข้าใจตรงกัน / English translation of the same context.', 'Primary Education student experience'),
 'assessor_role': ('ใช้กับ F04 เพื่อระบุตำแหน่งผู้บริหารที่ถูกประเมิน ตรวจให้ตรงทะเบียนรายปี / F04 position of the leader being evaluated; match the annual register.', 'รอบสาธารณะบุคลากรประเมินผู้บริหารทุกคนทุกตำแหน่ง / Public staff collections cover every leader and position'),
 'study_options': ('ใช้เฉพาะ F01 เลือกชั้นปีหรือช่วงศึกษาที่รอบนี้ครอบคลุม / F01 only: select the years or study stages covered by this collection.', 'เลือกรายการที่รุ่นแบบรองรับ เช่น ปี 1 และปี 2 รอบสาธารณะเลือกหลักสูตรและชั้นปีจากทะเบียนสาธารณะแยกต่างหาก / Select supported options, such as Year 1 and Year 2. Public programmes and years use their own entry taxonomy.'),
 'context_checked': ('ยืนยันเมื่อกลุ่ม หน่วยนับ และบริบทตรงกันแล้ว / Confirm only after checking that group, counting unit and context match.', ''),
 'fiscal_year': ('กรอก พ.ศ. ของปีที่สิ้นสุด ปีงบประมาณเริ่ม 1 ตุลาคมปีก่อน และจบ 30 กันยายนของปีนี้ / Enter the B.E. ending year; fiscal years run October–September.', '2569 = 1 ต.ค. 2025 ถึง 30 ก.ย. 2026 / 2569 = 1 Oct 2025–30 Sep 2026'),
 'reporting_year_be': ('กรอกปี พ.ศ. ที่ใช้รายงานผล เลือกประเภทปีให้ตรงกับแบบประเมิน / Enter the B.E. reporting year and select the matching calendar type.', '2569 (ค.ศ. 2026) / 2569 B.E. (2026 C.E.)'),
 'calendar_type': ('F01 ใช้ปีการศึกษา ส่วน F02–F06 ใช้ปีงบประมาณ / F01 uses academic years; F02–F06 use fiscal years.', ''),
 'start_date': ('วันแรกของช่วงที่ต้องการบันทึก ช่องวันที่ใช้ ค.ศ. / First date of the recorded period; date inputs use C.E.', '1 ต.ค. 2025 สำหรับปีงบประมาณ 2569 / 1 Oct 2025 for fiscal year 2569'),
 'last_date': ('วันสุดท้ายของช่วง โดยนับรวมวันนี้ / Inclusive last date of the period.', '30 ก.ย. 2026 สำหรับปีงบประมาณ 2569 / 30 Sep 2026 for fiscal year 2569'),
 'confirm': ('อ่านข้อมูลและผลที่จะเกิดขึ้นก่อนทำเครื่องหมาย ระบบจะตรวจเงื่อนไขอีกครั้งเมื่อบันทึก / Read the entries and their effect before confirming. Server validation still applies.', ''),
 'name_th': ('ชื่อทางการภาษาไทยที่ต้องการแสดงในทะเบียน / Official Thai display name in this register.', ''),
 'name_en': ('ชื่อภาษาอังกฤษของรายการเดียวกัน ตรวจการสะกดกับต้นฉบับ / English name of the same record; verify the spelling.', ''),
 'user': ('เชื่อมบัญชีของผู้ถูกประเมินถ้ามี เว้นว่างได้ ช่องนี้ไม่ใช่ข้อมูลผู้ตอบแบบประเมิน / Optional account of the evaluatee, not the anonymous respondent.', 'เว้นว่างหากบุคคลนี้ยังไม่มีบัญชี / Leave blank if there is no account'),
 'role': ('เลือกบทบาทหรือประเภทตามหน้าที่จริง อ่านผลของสิทธิ์ก่อนมอบหมาย / Select the role matching the actual responsibility and review its permissions.', ''),
 'title_th': ('ชื่อตำแหน่งภาษาไทยที่จะแสดงให้ผู้ประเมินเห็น / Thai position title shown to respondents.', 'รองคณบดีฝ่ายวิชาการ / Vice Dean for Academic Affairs'),
 'title_en': ('คำแปลของตำแหน่งเดียวกับภาษาไทย / English title matching the Thai position.', 'Vice Dean for Academic Affairs'),
 'programme': ('ระบุหลักสูตรเมื่อเป็นตำแหน่งประธานหลักสูตร ต้องสร้างหลักสูตรก่อน / Select a programme for a programme-chair position; create the programme first.', 'หลักสูตร กศ.ม. สาขาวิชาสะเต็มศึกษา / M.Ed. in STEM Education'),
 'person': ('เลือกผู้บริหารที่ถูกประเมินจากทะเบียนบุคลากร / Select the leader being evaluated from the people register.', ''),
 'position': ('เลือกตำแหน่งของผู้บริหารในช่วงนี้ คนเดียวหลายตำแหน่งต้องแยกรายการ / Select the position for this segment; separate each position held by one person.', ''),
 'responsibility_th': ('ขอบเขตงานของตำแหน่งในช่วงที่ประเมิน / Responsibilities of this position during the assessment period.', 'กำกับงานวิชาการและพัฒนาหลักสูตร / Academic oversight and curriculum development'),
 'responsibility_en': ('แปลภารกิจเดียวกับข้อความภาษาไทย / Translate the same responsibilities into English.', 'Academic oversight and curriculum development'),
 'source_reference': ('เลขคำสั่งหรือเอกสารที่ยืนยันผู้ดำรงตำแหน่งและช่วงเวลา / Appointment order or source confirming the person and dates.', 'คำสั่งแต่งตั้งเลขที่ … ลงวันที่ … / Appointment order no. … dated …'),
 'eligibility_basis': ('อธิบายนโยบายผู้ตอบของรอบ สำหรับสาธารณะให้บุคลากรประเมินผู้บริหารทุกคนทุกตำแหน่ง / State the collection policy. Public staff assessments cover every leader in every position.', 'บุคลากร ST1 และ ST2 ทุกคน / All ST1 and ST2 staff'),
 'username': ('ชื่อบัญชีเจ้าหน้าที่ที่สร้างแล้ว การเพิ่มสมาชิกยังไม่มอบสิทธิ์ ต้องทำขั้นตอนมอบบทบาทต่อ / Existing staff username. Adding membership does not grant access; assign a role next.', 'survey-operator'),
 'membership': ('เลือกสมาชิกที่จะได้รับสิทธิ์ หากไม่มีให้เพิ่มสมาชิกด้านซ้ายก่อน / Select the member receiving access; add membership first if missing.', ''),
 'active_until': ('วันสิ้นสุดสิทธิ์ตามเวลาไทย เว้นว่างเมื่อได้รับมอบหมายแบบไม่กำหนดวันสิ้นสุด / Access expiry in Thailand time; leave blank only for an ongoing assignment.', ''),
 'include_descendants': ('เมื่อเลือก สิทธิ์ครอบคลุมพื้นที่ย่อยทั้งหมดภายใต้พื้นที่นี้ / When selected, access also covers descendant workspaces.', 'ใช้สำหรับผู้ดูแลที่รับผิดชอบทั้งหน่วยงาน / For administrators responsible for the whole unit'),
}

def guidance(field):
    name = type(field.form).__name__
    help_text, example = GUIDES.get(field.name, ('', ''))
    if name in {'PersonForm', 'ProgrammeForm', 'PositionForm'}:
        examples = {
          'PersonForm': {'code':'LEADER-001', 'name_th':'ชื่อ–สกุลผู้บริหารตามคำสั่งแต่งตั้ง / Leader name from the appointment order', 'name_en':'Official English name from the appointment record'},
          'ProgrammeForm': {'code':'MED-STEM', 'name_th':'กศ.ม. สาขาวิชาสะเต็มศึกษา', 'name_en':'Master of Education in STEM Education'},
          'PositionForm': {'code':'VD-ACADEMIC-01', 'role':'รองคณบดี / Vice Dean'},
        }
        example = examples[name].get(field.name, example)
        if field.name == 'code':
            help_text = 'รหัสคงที่เพื่ออ้างอิงข้ามปี ใช้รหัสเดิมเมื่อแก้ชื่อ ไม่สร้างซ้ำ / Stable cross-year reference. Keep the code when updating a name; avoid duplicates.'
    return {'help':help_text, 'example':example}
