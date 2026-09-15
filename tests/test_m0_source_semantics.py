"""Acceptance examples reviewed against the supplied Instruments 1.1 text."""
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
def read(name): return json.loads((ROOT/'catalog'/name).read_text(encoding='utf-8'))

class SourceSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.questions={q['question_id']:q for q in read('questions.json')}
        self.scales={s['scale_id']:s for s in read('scales.json')}

    def test_sat_dis_are_respondent_options_not_formula_rows(self):
        sat=[('1','พึงพอใจน้อยที่สุด',1),('2','น้อย',2),('3','ปานกลาง',3),('4','มาก',4),('5','มากที่สุด',5),('NA','ไม่ได้ใช้บริการหรือไม่มีประสบการณ์เพียงพอ',None)]
        dis=[('Y','มี',None),('N','ไม่มี',None),('NA','ไม่ได้ใช้บริการหรือไม่มีประสบการณ์เพียงพอ',None)]
        for sid,expected in [('SAT',sat),('DIS',dis)]:
            s=self.scales[sid]
            self.assertEqual([(o['code'],o['label']['th'],o['score']) for o in s['options']],expected)
            self.assertLess(s['source']['line'],30)
            for q in self.questions.values():
                if q['scale_id']==sid:
                    self.assertEqual(q['options'],s['options'],q['question_id'])

    def test_option_codes_and_translation_keys_are_unique(self):
        for q in self.questions.values():
            codes=[o['code'] for o in q['options']]
            self.assertEqual(len(codes),len(set(codes)),q['question_id'])
        keys=[t['key'] for t in read('translations.json')['inventory']]
        self.assertEqual(len(keys),len(set(keys)))

    def test_every_f04_role_question_is_a_rating(self):
        for role in ['DE','BO','VD','AS','PC']:
            for n in range(1,6):
                q=self.questions[f'F04-{role}{n:02}']
                self.assertEqual(q['answer_type'],'integer_scale')
                self.assertEqual(q['scale_id'],'ADM')
                self.assertEqual([o['code'] for o in q['options']],['1','2','3','4','5','NA'])

    def test_context_fields_keep_source_semantics(self):
        self.assertEqual(self.questions['F05-P01']['answer_type'],'context_reference')
        self.assertEqual(self.questions['F05-P01']['reference_source'],'personnel_registry.person_id')
        self.assertTrue(self.questions['F05-P01']['required'])
        q=self.questions['F02-P04']
        self.assertEqual(q['answer_type'],'single_choice')
        self.assertEqual([o['code'] for o in q['options']],['month_year','cannot_recall'])
        self.assertEqual(q['optional_fields']['last_service_month']['type'],'month_year')

    def test_same_incident_reuse_stays_optional(self):
        for n in range(1,6):
            q=self.questions[f'F01-D{n:02}']
            reuse=q['follow_up_reuse']
            self.assertFalse(reuse['required'])
            self.assertEqual(reuse['visible_if_value'],'Y')
            self.assertEqual(reuse['reuse_fields'],['CAUSE','FIX'])

    def test_table_question_text_matches_source_verbatim(self):
        import re
        lines=(ROOT/'docs/source/EdPEx_6_Instruments.md').read_text(encoding='utf-8').splitlines()
        for line in lines:
            if not line.startswith('|'): continue
            cells=[c.strip() for c in line.strip('|').split('|')]
            for position,cell in enumerate(cells):
                if re.fullmatch(r'F0[1-6]-[A-Z]+\d*',cell):
                    self.assertEqual(self.questions[cell]['text']['th'],cells[position+1],cell)

if __name__=='__main__': unittest.main()
