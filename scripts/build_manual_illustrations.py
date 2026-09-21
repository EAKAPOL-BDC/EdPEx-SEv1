#!/usr/bin/env python3
"""Render labelled instructional UI diagrams. Uses no live user data/browser."""
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.manuals.illustrations import FIGURES, STATIC_DIR


def build():
    from weasyprint import HTML
    import fitz
    destination = ROOT/'apps/manuals/static'/STATIC_DIR
    destination.mkdir(parents=True, exist_ok=True)
    fonts = ROOT/'docs/manuals/fonts'
    css = '''
    @font-face{font-family:Sarabun;src:url("REGULAR")}@font-face{font-family:Sarabun;src:url("BOLD");font-weight:700}
    @page{size:1080px 600px;margin:0}*{box-sizing:border-box}body{margin:0;font:22px/1.55 Sarabun;color:#263148;background:#f3f4fa}
    .top{position:absolute;left:0;top:0;right:0;height:88px;background:#fff;border-bottom:1px solid #dce0ed;padding:18px 36px}
    .top strong{display:block;color:#503278;font-size:16px;letter-spacing:1px}.top span{font-size:26px;font-weight:700}
    .card{position:absolute;background:#fff;border:1px solid #d8dce9;border-radius:14px;padding:22px;overflow:hidden}
    .soft{background:#eeeaf7}.card h2{font-size:25px;line-height:1.4;margin:0 0 9px;font-weight:700}.card p{margin:8px 0 16px}
    .muted,.small{color:#535f74;font-size:19px}.pin{display:inline-block;width:31px;height:31px;line-height:31px;vertical-align:middle;text-align:center;background:#644395;color:#fff;border-radius:50%;font-size:20px;margin-right:10px}
    .field{margin-bottom:16px}.field .pin{float:left;margin-top:0}.field label{display:block;font-size:20px;color:#3c3554;margin-bottom:7px}
    .input{border:1px solid #aab3c9;border-radius:7px;padding:9px 14px;min-height:49px;background:#fff;color:#505b6e;font-size:21px}
    .btn{display:inline-block;padding:10px 18px;background:#624292;color:white;border:1px solid #624292;border-radius:8px;font-size:20px;margin:2px 7px 4px 0}.secondary{background:#fff;color:#513878;border-color:#bcb0cd}
    .choice,.navitem{padding:10px 15px;border:1px solid #cfd4e3;border-radius:8px;background:#fff;margin:10px 0}.selected{border:2px solid #7655ab;background:#f4effc;color:#4a306e}
    .notice{padding:10px 13px;background:#edf5f2;border-left:3px solid #32816b;color:#265848;font-size:19px;margin-top:14px}
    .half{display:inline-block;width:48%;vertical-align:top;margin-right:1%}hr{border:0;border-top:1px solid #cfd3e2;margin:12px 0}
    .track{height:10px;border-radius:7px;background:#d5cce3;overflow:hidden}.track i{display:block;height:100%;background:#7655ab}
    .emblem{font-size:56px;color:#61418e;font-weight:bold;background:#fff;border-radius:24px;width:96px;height:96px;text-align:center;margin:18px 0}
    .bar-row{font-size:20px;margin:18px 0;white-space:nowrap}.bar{display:inline-block;background:#7354a3;height:26px;border-radius:4px;margin:0 8px;vertical-align:middle}.bar.teal{background:#338278}
    .arrow{position:absolute;color:#69498f;font-size:33px}.foot{position:absolute;left:36px;right:36px;bottom:16px;color:#526078;font-size:17px;border-top:1px solid #d8dce9;padding-top:9px}
    '''.replace('REGULAR',(fonts/'Sarabun-Regular.ttf').as_uri()).replace('BOLD',(fonts/'Sarabun-Bold.ttf').as_uri())
    for key, figure in FIGURES.items():
        for source in figure['sources']:
            if not (ROOT/source).is_file():
                raise ValueError('Missing source: '+source)
        html = '<!doctype html><html lang="th"><meta charset="utf-8"><style>'+css+'</style><body><header class="top"><strong>NEXORA / VISUAL GUIDE</strong><span>'+escape(figure['title'])+'</span></header>'+figure['body']+'<footer class="foot">ภาพจำลองอธิบายขั้นตอน • ย่อส่วนหน้าจอเพื่อให้อ่านง่าย • ตัวอย่างไม่ใช่ข้อมูลจริง</footer></body></html>'
        document = fitz.open(stream=HTML(string=html).write_pdf(), filetype='pdf')
        if len(document) != 1:
            raise ValueError('Illustration overflow: '+key)
        page = document[0]
        for block in page.get_text('dict')['blocks']:
            for line in block.get('lines',[]):
                x0,y0,x1,y1=line['bbox']
                if min(x0,y0)<0 or x1>page.rect.width or y1>page.rect.height:
                    raise ValueError('Illustration text outside page: '+key)
        page.get_pixmap(matrix=fitz.Matrix(8/3,8/3),alpha=False).save(destination/(key+'.png'))
        print(key,flush=True)


if __name__ == '__main__':
    build()
