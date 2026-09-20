"""Source-backed display metadata; never rewrite versioned calculation inputs."""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def reference():
    return json.loads(Path(__file__).with_name('data').joinpath('indicator_alignment.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def by_code():
    return {row['code']: row for row in reference()['indicators']}


def indicator_title(code, fallback=''):
    return by_code().get(code, {}).get('title_th') or fallback or code


def measurement_note(code, *, method='', formula_version=''):
    row = by_code().get(code, {})
    key = row.get('formula')
    if row.get('form') == 'F05':
        if method == 'anonymous_self_report':
            if formula_version == '2.1-quantitative':
                return 'ข้อมูลที่ผู้ตอบรายงานเอง ตัวหารคือผู้ส่งแบบสอบถามครบทุกคน รวมผู้ที่อบรม 0 ชั่วโมง ผู้ที่ยังไม่ส่งไม่ถูกนับเป็น 0 / Self-reported; denominator includes every completed response, including zero hours. Nonrespondents are not zero.'
            return 'ข้อมูลที่ผู้ตอบรายงานเอง ใช้เกณฑ์และตัวหารตามรุ่นแบบฟอร์มที่แสดง / Self-reported; use the criteria and denominator of the displayed form version.'
        return 'ข้อมูลทะเบียนกิจกรรมเดิม ใช้รายการตรวจรับและประชากรตามสูตรเดิม แยกจากแบบสอบถามรายปีรุ่นใหม่ / Historical activity register; accepted records and the original population denominator, separate from the newer annual survey.'
    notes = {
        'DIS_YES': 'ร้อยละผู้ตอบว่ามีประสบการณ์ไม่พึงพอใจ ค่าต่ำหมายถึงมีผู้ไม่พึงพอใจน้อยลง ไม่นับคำตอบที่ประเมินไม่ได้หรือเว้นว่างเป็นไม่มีปัญหา / Lower means fewer dissatisfied respondents; unavailable or missing answers are not “no”.',
        'MEAN_5': 'คะแนนเฉลี่ยเต็ม 5 ไม่ใช่ร้อยละหรือคะแนน NPS / Mean score out of 5; not a percentage or NPS.',
        'HAPPINESS_10': 'คะแนนความสุขเฉลี่ยเต็ม 10 คะแนน 0 เป็นคำตอบจริงและรวมคำนวณ / Mean happiness out of 10; zero is a valid response.',
        'DIMENSION_SAT': 'แสดงความพึงพอใจแยก 7 ด้าน ข้อเลือกปัจจัยสำคัญ G08 ไม่รวมในคะแนน / Seven separate satisfaction dimensions; G08 priorities do not contribute to the score.',
        'SELF_DIMENSION': 'คะแนนประเมินตนเองแยกแต่ละพันธกิจหรือกลยุทธ์ ไม่นับข้อที่ไม่เกี่ยวข้องเป็นศูนย์ / Self-rated scores by mission or strategy; not-applicable answers are excluded, not zero.',
        'SELF_DIGITAL_POP': 'ผู้ประเมินตนเองผ่านเกณฑ์ทักษะดิจิทัล หารด้วยผู้มีสิทธิ์ทั้งหมด ค่านี้ขึ้นกับการเข้าร่วมตอบด้วย ผู้ไม่ตอบยังสรุปไม่ได้ว่าทักษะต่ำ / Self-reported threshold attainment divided by all eligible people. Participation affects this rate; nonresponse does not establish low skill.',
        'ADMIN_MEAN': 'คะแนนเฉลี่ยเต็ม 5 แยกผู้ถูกประเมิน ตำแหน่ง หลักสูตร และช่วงดำรงตำแหน่ง / Mean out of 5; keep evaluatee, position, programme and tenure period separate.',
        'SELF_COMPETENCY': 'คะแนนประเมินตนเองเต็ม 5 ตามข้อที่กำหนดของแต่ละสายงาน / Self-rated score out of 5 using the required items for each staff group.',
        'SELF_VISION': 'สัดส่วนผู้ตอบที่ประเมินความเข้าใจของตนเองถึงเกณฑ์ ไม่ใช่ผลทดสอบความรู้ / Self-rated understanding meeting the configured threshold, not a knowledge test.',
        'SELF_VALUES': 'สัดส่วนผู้ตอบที่ประเมินความเข้าใจของตนเองถึงเกณฑ์ ไม่ใช่ผลทดสอบความรู้ / Self-rated understanding meeting the configured threshold, not a knowledge test.',
        'SELF_BEHAVIOUR': 'การรายงานพฤติกรรมของตนเอง แยกแต่ละค่านิยมและภาพรวมตามสูตร / Self-reported behaviour, with separate value dimensions and an overall formula.',
        'K_EXTERNAL': 'วัดการรับรู้และความเข้าใจตามคำตอบ ไม่ใช่การประเมินความพึงพอใจ เกณฑ์คำนวณเป็นข้อกำหนดของระบบ / Awareness and understanding, not satisfaction; thresholds are defined by the system.',
    }
    return notes.get(key, 'ใช้หน่วยและเกณฑ์ตามสูตรที่ผูกไว้ ไม่ใช่เกณฑ์ผ่านที่เอกสารตัวชี้วัดบังคับ / Use the bound unit and formula; the indicator document does not mandate these thresholds.')


def source_warning(code):
    if code == '7.4-8':
        return 'C3.2 ปรากฏเพียงบางรายการในเอกสาร แต่ยังไม่มีนิยามในทะเบียนกลุ่ม จึงคงกลุ่มเดิมไว้ รอยืนยันนิยามก่อนเพิ่มสิทธิ์ / C3.2 appears inconsistently and has no registry definition; existing eligibility is retained pending clarification.'
    return ''
