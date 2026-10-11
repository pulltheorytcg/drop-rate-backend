"""Actual Seller Hub DOM/CSS/import JS; mocked session and empty history API.
No production login, file upload, inventory mutation or checkout is performed.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]
STATIC=ROOT/'backend/app/static'
OUT=Path('/tmp/drop-rate-import-layout')
WIDTHS=(320,360,390,393,430,660,661,768,1024,1440)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    html=(STATIC/'owner.html').read_text()
    html=re.sub(r'<script\b[^>]*>.*?</script>','',html,flags=re.S|re.I)
    checks=[]
    with sync_playwright() as p:
        for engine in ('chromium','webkit'):
            browser=getattr(p,engine).launch()
            for width in WIDTHS:
                page=browser.new_page(viewport={'width':width,'height':850})
                def serve(route):
                    parsed=urlsplit(route.request.url)
                    if parsed.hostname!='drop-rate.test':
                        route.abort();return
                    if parsed.path=='/owner':
                        route.fulfill(status=200,body=html,content_type='text/html');return
                    file=(STATIC/parsed.path.removeprefix('/assets/')).resolve()
                    if parsed.path.startswith('/assets/') and file.is_relative_to(STATIC.resolve()) and file.is_file():
                        content_type='text/css' if file.suffix=='.css' else 'application/octet-stream'
                        route.fulfill(status=200,body=file.read_bytes(),content_type=content_type);return
                    route.abort()
                page.route('**/*',serve)
                page.goto('https://drop-rate.test/owner')
                page.evaluate('''() => {
                  document.body.classList.remove('hub-restoring');
                  document.querySelector('.hub-loading')?.remove();
                  document.getElementById('owner-auth-view').classList.add('hidden');
                  document.getElementById('owner-portal-view').classList.remove('hidden');
                  document.querySelectorAll('[data-owner-view-panel]').forEach(e=>e.classList.toggle('hidden',e.dataset.ownerViewPanel!=='inventory'));
                  window.__writes=[];
                  window.apiRequest=async(url,options={})=>{
                    if(options.method && options.method!=='GET') {window.__writes.push(url);throw Error('Unexpected mutation');}
                    if(url==='/api/v1/owner/imports?limit=8') return {items:[]};
                    throw Error('Unexpected API read '+url);
                  };
                }''')
                page.add_script_tag(content=(STATIC/'owner-imports.js').read_text())
                trigger=page.locator('#owner-import-trigger')
                trigger.scroll_into_view_if_needed();trigger.click()
                menu=page.locator('#owner-import-menu')
                assert menu.is_visible()
                # Reproduce original anchoring on the real assets, then remove
                # the override to test the actual committed stylesheet.
                if width==393:
                    previous=page.add_style_tag(content='@media(max-width:660px){.owner-portal-page .owner-import-menu-wrap{flex:0 0 auto}.owner-portal-page .owner-import-menu{left:auto;right:0;width:min(300px,85vw);max-width:none}}')
                    old=menu.bounding_box();assert old and old['x']<0,(engine,old)
                    previous.evaluate('e=>e.remove()')
                rect=menu.bounding_box();assert rect and rect['x']>=0 and rect['x']+rect['width']<=width+1,(engine,width,rect)
                assert menu.locator('button').count()==3
                for button in menu.locator('button').all():
                    button.scroll_into_view_if_needed()
                    assert button.evaluate('''e=>{const r=e.getBoundingClientRect();const hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return hit===e||e.contains(hit)}'''),(engine,width,'menu clipped')
                if width in (393,1440): page.screenshot(path=str(OUT/f'{engine}-menu-{width}.png'),full_page=True)
                menu.locator('[data-owner-import-adapter="COLLECTR"]').click()
                dialog=page.locator('#owner-import-dialog');assert dialog.is_visible()
                d=dialog.bounding_box();assert d and d['x']>=-1 and d['x']+d['width']<=width+1,(engine,width,d)
                # Long messages/content should scroll in the body, with close
                # available and no overflow beyond the dialog's clipped frame.
                page.evaluate('''() => {
                  const body=document.querySelector('.owner-import-dialog-body');
                  const p=document.createElement('p');p.textContent='Synthetic review details '.repeat(300);body.append(p);
                  const end=document.createElement('button');end.id='fixture-last';end.textContent='Last review action';body.append(end);
                }''')
                last=page.locator('#fixture-last');last.scroll_into_view_if_needed()
                assert last.evaluate('''e=>{const r=e.getBoundingClientRect();const hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return hit===e||e.contains(hit)}'''),(engine,width,'dialog bottom clipped')
                assert page.locator('#owner-import-close').is_visible()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(engine,width,'page overflow')
                if width<=660:
                    assert float(page.locator('#owner-import-language').evaluate('e=>parseFloat(getComputedStyle(e).fontSize)'))>=16
                if width in (393,1440): page.screenshot(path=str(OUT/f'{engine}-dialog-{width}.png'),full_page=True)
                page.locator('#owner-import-close').click();assert not dialog.is_visible()
                trigger.click();assert menu.is_visible()
                page.keyboard.press('Escape');assert not menu.is_visible()
                assert page.evaluate('window.__writes.length')==0
                checks.append({'engine':engine,'width':width,'pass':True})
                page.close()
            browser.close()
    (OUT/'results.json').write_text(json.dumps(checks,indent=2))
    print(f'PASS: {len(checks)} actual-asset responsive layout cases; original clipping reproduced at 393px. Session/history mocked; no production import claimed.')


if __name__=='__main__':main()
