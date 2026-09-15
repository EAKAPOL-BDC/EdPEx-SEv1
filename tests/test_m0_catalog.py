"""Offline catalog acceptance tests. Never load Django or connect to a database."""
import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
def read(name): return json.loads((ROOT/'catalog'/name).read_text(encoding='utf-8'))

class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.questions={q['question_id']:q for q in read('questions.json')}
        cls.indicators={i['code']:i for i in read('indicators.json')}
        cls.formulas={f['formula_id']:f for f in read('formulas.json')}

    def test_exact_63_codes_not_only_count(self):
        expected={f'7.2-{n}' for n in [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,17,18,19,20,24,25,34,35,36]}
        expected|={f'7.3-{n}' for n in [25,26,27,28,29,36,37,38,39,43,44,45,46,47,48,49,50,51,52,53,54,55]}
        expected|={'7.4-'+n for n in ['1','2','3','4','6','7','8','9','10','11','12','13','14','15','18A','18B','18C']}
        self.assertEqual(set(self.indicators),expected)
        self.assertEqual(len(read('indicators.json')),63)

    def test_no_orphan_bindings_and_group_compatibility(self):
        for code,i in self.indicators.items():
            b=i['binding']; self.assertIn(b['formula_id'],self.formulas)
            for qid in b['source_question_ids']:
                self.assertIn(qid,self.questions)
                q=self.questions[qid]
                self.assertIn(code,q['source_indicator_codes'])
                self.assertTrue(set(b['group_codes'])<=set(q['group_codes']),qid)

    def test_all_explicit_table_and_inline_questions_preserved(self):
        source=(ROOT/'docs/source/EdPEx_6_Instruments.md').read_text(encoding='utf-8')
        table_ids=set(re.findall(r'\| (F0[1-6]-[A-Z]+\d*) \|',source))
        self.assertTrue(table_ids<=set(self.questions))
        for form in ['F01','F02','F06']:
            for n in range(7): self.assertIn(f'{form}-K{n:02}',self.questions)
        for qid in ['F03-H01','F03-G08','F04-P03','F05-F04','F06-P05','F01-D05-FIX','F03-D02-CAUSE','F06-VP-EX']:
            self.assertIn(qid,self.questions)
        self.assertEqual(len(read('questions.json')),len(self.questions))

    def test_source_bytes_versions_and_sections(self):
        for s in read('manifest.json')['source_documents']:
            raw=(ROOT/s['path']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),s['sha256'])
            self.assertEqual(len(raw.decode('utf-8').splitlines()),s['lines'])
        b=(ROOT/'docs/source/EdPEx_System_Blueprint_v1.md').read_text(encoding='utf-8')
        self.assertIn('System Blueprint 1.2',b)
        self.assertEqual([int(n) for n in re.findall(r'^## (\d+)\.',b,re.M)],list(range(1,34)))
        self.assertEqual([r['section'] for r in read('requirements.json')],list(range(1,34)))

    def test_f06_self_report_without_evidence_or_reviewer(self):
        for q in self.questions.values():
            if q['instrument_id']=='F06':
                self.assertEqual(q['assessment_method'],'self_report')
                self.assertEqual(q['instrument_version'],'1.1')
                self.assertFalse(q['evidence_allowed'])
                self.assertFalse(q['reviewer_step'])
        for suffix in ['S','E','U','P']:
            self.assertFalse(self.questions['F06-V'+suffix+'-EX']['required'])
        b=self.indicators['7.4-6']['binding']
        self.assertFalse(b['examples_affect_score'])
        self.assertTrue(all(not q.endswith('-EX') for q in b['source_question_ids']))

    def test_different_denominators_and_external_k(self):
        self.assertEqual(self.indicators['7.3-43']['binding']['denominator'],'frozen_eligible_population_including_nonrespondents')
        self.assertEqual(self.indicators['7.4-3']['binding']['denominator'],'complete_scored_pair')
        self.assertEqual(self.indicators['7.4-4']['binding']['denominator'],'complete_scored_four')
        for code in ['7.4-8','7.4-10','7.4-12']:
            self.assertEqual(self.indicators[code]['binding']['formula_id'],'K_EXTERNAL')
        for code in ['7.4-3','7.4-4']:
            self.assertNotEqual(self.indicators[code]['binding']['formula_id'],'K_EXTERNAL')
        self.assertFalse(read('answer_keys.server.json')['F06_uses_this_key'])
        self.assertNotIn('correct_options',(ROOT/'catalog/questions.json').read_text(encoding='utf-8'))

    def test_critical_many_to_many_and_dimensions(self):
        a=self.indicators['7.2-13']['binding']; b=self.indicators['7.2-17']['binding']
        self.assertEqual(a['source_question_ids'],b['source_question_ids'])
        self.assertEqual(a['group_codes'],['C5.3'])
        self.assertEqual(self.indicators['7.3-50']['binding']['required_complete'],5)
        self.assertEqual(self.indicators['7.3-51']['binding']['required_complete'],9)
        self.assertNotIn('F03-G08',self.indicators['7.3-39']['binding']['source_question_ids'])
        for code in ['7.3-39','7.3-54','7.3-55']:
            self.assertFalse(self.indicators[code]['binding']['overall'])
        self.assertEqual(self.indicators['7.4-2']['binding']['formula_id'],'MEAN_5')
        self.assertEqual(self.indicators['7.4-18B']['binding']['minimum_answered'],4)

    def test_f05_separate_verified_workflow(self):
        for n in range(44,50):
            self.assertTrue(self.indicators[f'7.3-{n}']['binding']['parameters']['accepted_only'])
        self.assertEqual(self.indicators['7.3-47']['binding']['parameters']['category'],['T47S','T47H','T47E'])
        self.assertTrue(self.indicators['7.3-49']['binding']['parameters']['external_visit_only'])
        self.assertEqual(self.questions['F05-P05']['answer_type'],'evidence_reference')

    def test_branch_and_missing_semantics(self):
        self.assertEqual(self.questions['F01-D01-CAUSE']['visibility_condition'],{'op':'eq','question_id':'F01-D01','value':'Y'})
        self.assertEqual(self.questions['F03-G08']['max_selected'],3)
        self.assertEqual(self.questions['F04-P03']['terminal_option']['score'],None)
        self.assertEqual(read('answer_keys.server.json')['unknown_U_score'],0)
        self.assertEqual(read('answer_keys.server.json')['blank'],'missing')
        for f in self.formulas.values():
            self.assertFalse(f['missing_is_zero'])
            self.assertEqual(f['zero_denominator']['value'],None)

    def test_translation_inventory_is_honest_and_complete(self):
        t=read('translations.json')
        self.assertEqual(t['supported_locales'],['th','en'])
        self.assertFalse(t['publishable'])
        keys={x['key'] for x in t['inventory']}
        self.assertTrue({q+'.text' for q in self.questions}<=keys)
        for q in self.questions.values():
            for opt in q['options']: self.assertIn(q['question_id']+'.option.'+opt['code'],keys)
        self.assertTrue(all(x['status']=='needs_review' for x in read('glossary.json')))

    def test_answer_key_source_and_translation_stay_server_only(self):
        found=0
        for item in read('instrument_sections.json')+read('translations.json')['inventory']:
            text=item.get('content_th',item.get('th',''))
            if 'K01=B' in text or 'K06=D' in text:
                found+=1
                self.assertEqual(item.get('audience'),'server_only')
        self.assertGreaterEqual(found,2)

    def test_context_and_server_managed_fields(self):
        self.assertTrue(self.questions['F01-P04']['required'])
        self.assertEqual(self.questions['F01-P04']['group_codes'],['C3.1'])
        self.assertEqual(self.questions['F02-D03']['max_length'],500)
        for qid in ['F05-A01','F05-P02','F05-V02']:
            self.assertTrue(self.questions[qid]['system_assigned'])
        self.assertEqual(self.questions['F05-V02']['audience'],'server_only')

    def test_unknown_names_targets_not_fabricated(self):
        for i in self.indicators.values():
            self.assertIsNone(i['original_name'])
            self.assertIsNone(i['target'])
            self.assertIsNone(i['comparator'])
        self.assertNotIn('C3.2',{g['code'] for g in read('groups.json')})

if __name__=='__main__': unittest.main()
