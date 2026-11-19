#!/usr/bin/env python3
"""Serve an interactive local review page for page-preprocessing candidates."""
import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from preprocess_page import preprocess
import cv2


ROOT = Path(__file__).resolve().parents[1]
GENEALOGY = ROOT / 'scan' / 'genealogy'

HTML = r'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>족보 전처리 검수</title>
<style>
body{margin:0;background:#181818;color:#eee;font:15px system-ui,sans-serif}header{position:sticky;top:0;padding:12px;background:#252525;display:flex;gap:10px;align-items:center;z-index:2}button,select,label{font:inherit}main{padding:14px;display:flex;gap:18px;align-items:flex-start}.page{position:relative;line-height:0;background:#000}.page img{display:block;max-width:min(72vw,900px);max-height:82vh}.overlay{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}.band{fill:none;stroke:#f33;stroke-width:2}.column{fill:none;stroke:#38f;stroke-width:1}.frame{fill:none;stroke:#fd0;stroke-width:2}aside{max-width:300px;line-height:1.5}.warning{color:#ffcc66}kbd{background:#444;padding:2px 5px;border-radius:3px}</style>
<header><button id="prev">← 이전</button><select id="pages"></select><button id="next">다음 →</button><label><input id="bands" type="checkbox" checked> 단(빨강)</label><label><input id="columns" type="checkbox" checked> 열(파랑)</label><label><input id="frame" type="checkbox" checked> 본문 틀(노랑)</label></header>
<main><div class="page"><img id="image" alt="족보 쪽"><svg id="svg" class="overlay"></svg></div><aside><strong id="title"></strong><p>빨간 상자는 세대 단 후보, 파란 상자는 세로 글줄 후보입니다. 빈 단도 빨강 상자로 남아야 합니다.</p><div id="info"></div><p><kbd>←</kbd> <kbd>→</kbd> 키로 쪽을 이동합니다.</p></aside></main>
<script>
const $=id=>document.getElementById(id), sel=$('pages'), image=$('image'), svg=$('svg'); let pages=[], current=0, data;
function rect(c,b){let e=document.createElementNS('http://www.w3.org/2000/svg','rect');e.setAttribute('class',c);e.setAttribute('x',b[0]);e.setAttribute('y',b[1]);e.setAttribute('width',b[2]-b[0]);e.setAttribute('height',b[3]-b[1]);svg.append(e)}
function draw(){svg.replaceChildren();svg.setAttribute('viewBox',`0 0 ${data.width} ${data.height}`);if($('frame').checked)rect('frame',data.frame);for(const b of data.bands){if($('bands').checked)rect('band',b.bbox);if($('columns').checked)for(const c of b.columns)rect('column',c.bbox)} $('info').innerHTML=`상태: ${data.status}<br>단: ${data.bands.length}, 열 후보: ${data.bands.reduce((n,b)=>n+b.columns.length,0)}<br><br>${data.warnings.map(x=>`<div class="warning">${x}</div>`).join('')}`}
async function load(i){current=(i+pages.length)%pages.length;sel.value=pages[current];data=await fetch(`/api/page/${pages[current]}`).then(r=>r.json());image.src=`/scan/genealogy/${pages[current]}.jpg`;image.onload=draw;$('title').textContent=`${pages[current]}쪽`;location.hash=pages[current]}
Promise.all([fetch('/api/pages').then(r=>r.json())]).then(([p])=>{pages=p;for(const n of p){let o=document.createElement('option');o.value=o.textContent=n;sel.append(o)}let requested=location.hash.slice(1);load(Math.max(0,pages.indexOf(requested)))});
$('prev').onclick=()=>load(current-1);$('next').onclick=()=>load(current+1);sel.onchange=()=>load(pages.indexOf(sel.value));for(const id of ['bands','columns','frame'])$(id).onchange=draw;document.onkeydown=e=>{if(e.key==='ArrowLeft')load(current-1);if(e.key==='ArrowRight')load(current+1)};
</script>'''


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == '/':
            body = HTML.encode()
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == '/api/pages':
            self.json_response([p.stem for p in sorted(GENEALOGY.glob('[0-9][0-9][0-9].jpg'))])
            return
        if path.startswith('/api/page/'):
            page = path.removeprefix('/api/page/')
            image = GENEALOGY / f'{page}.jpg'
            if not page.isdigit() or len(page) != 3 or not image.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            loaded = cv2.imread(str(image))
            self.json_response(preprocess(loaded) | {'image': str(image)})
            return
        if path.startswith('/scan/genealogy/'):
            filename = Path(path).name
            if filename != path.rsplit('/', 1)[-1] or not filename.endswith('.jpg'):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            target = GENEALOGY / filename
            if target.is_file():
                self.send_response(HTTPStatus.OK)
                self.send_header('Content-Type', mimetypes.guess_type(str(target))[0] or 'image/jpeg')
                self.send_header('Content-Length', str(target.stat().st_size))
                self.end_headers()
                with target.open('rb') as f:
                    self.copyfile(f, self.wfile)
                return
        self.send_error(HTTPStatus.NOT_FOUND)

    def json_response(self, value):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'Open http://127.0.0.1:{args.port}')
    server.serve_forever()


if __name__ == '__main__':
    main()
