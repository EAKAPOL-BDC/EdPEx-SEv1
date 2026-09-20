import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from build_f01_preview import build_data

def test_public_bilingual_payload():
    data=build_data()
    assert len(data['questions']) == 37
    assert data['instructions'] and data['instructions_en']
    allowed={'id','text','text_en','type','options','rule','fixed','fixed_en'}
    for question in data['questions']:
        assert set(question)==allowed
        assert question['text'] and question['text_en']
        for option in question['options']:
            assert set(option)=={'value','label','label_en'}
            assert option['label'] and option['label_en']
        assert len({o['value'] for o in question['options']})==len(question['options'])
        assert sum(o['label_en']=='Unable to assess' for o in question['options'])<=1
        if question['fixed']:
            assert question['fixed_en']

if __name__=='__main__':
    test_public_bilingual_payload()
    print('PASS: all 37 public definitions translated; field allowlist excludes answer keys; no duplicate Unable to assess options.')
