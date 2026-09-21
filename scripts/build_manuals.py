#!/usr/bin/env python3
"""Build one canonical web catalog and pre-rendered, version-matched Thai PDFs."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.manuals import respondents, operations, developer
from scripts.manuals.common import VERSION, UPDATED, BASELINE
from scripts.manuals.illustrations import attach, STATIC_DIR


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def normalize(value):
    if isinstance(value, str):
        return value.translate(str.maketrans({'\u2011':'-', '\u2013':'-', '\u2014':'-'}))
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, dict):
        return {key:normalize(item) for key,item in value.items()}
    return value


def build():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--content-only', action='store_true', help='Write content only; PDF downloads reject mismatched old artifacts.')
    args = parser.parse_args()
    folder=ROOT/'docs/manuals'
    manuals=normalize(respondents.build(ROOT)+operations.build()+[developer.build()])
    attach(manuals, ROOT)
    assert len(manuals)==26 and len({m['slug'] for m in manuals})==26
    for m in manuals:
        assert len({s['id'] for s in m['sections']})==len(m['sections'])
    data={'version':VERSION,'updated':UPDATED,'baseline':BASELINE,'manuals':manuals}
    (folder/'content').mkdir(parents=True,exist_ok=True)
    (folder/'content/manuals.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.content_only:
        print('Content written; rebuild PDFs before release.')
        return
    from django.conf import settings
    from django.template import Engine, Context
    from weasyprint import HTML, CSS
    from weasyprint.text.fonts import FontConfiguration
    from pypdf import PdfReader
    if not settings.configured:
        settings.configure(USE_I18N=False, USE_TZ=True, DEFAULT_CHARSET='utf-8')
    engine=Engine(dirs=[str(folder),str(ROOT/'apps/manuals/templates')])
    template=engine.get_template('print.html')
    fonts=FontConfiguration()
    css=CSS(filename=str(folder/'print.css'),font_config=fonts)
    (folder/'pdf').mkdir(exist_ok=True)
    manifest={'version':VERSION,'baseline':BASELINE,'manuals':{}}
    for m in manuals:
        html=template.render(Context({'manual':m, 'print_mode':True,
            'illustration_base':(ROOT/'apps/manuals/static'/STATIC_DIR).as_uri()+'/'},use_l10n=False))
        output=folder/'pdf'/m['filename']
        HTML(string=html,base_url=str(folder)).write_pdf(output,stylesheets=[css],font_config=fonts)
        reader=PdfReader(output)
        manifest['manuals'][m['slug']]={'filename':m['filename'],'pages':len(reader.pages),
            'bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
            'source_sha256':digest(m)}
        print(f"{m['slug']}: {len(reader.pages)} pages",flush=True)
    (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Built',len(manuals),'manuals;',sum(r['pages'] for r in manifest['manuals'].values()),'pages.')


if __name__=='__main__':
    build()
