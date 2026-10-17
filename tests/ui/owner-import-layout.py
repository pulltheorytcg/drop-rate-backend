"""Actual owner HTML/CSS/import script, local mocked history, no external traffic.

This is a responsive layout test, not a seller login, real import or physical
phone test. Chromium and WebKit cover 320-1440px and a reduced-height viewport.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / 'backend/app/static'
OUT = Path(os.environ.get('IMPORT_LAYOUT_ARTIFACT_DIR', '/tmp/drop-rate-import-layout'))
SIZES = [(320, 640), (360, 740), (390, 844), (430, 932), (660, 800), (768, 900), (1024, 900), (1440, 1000), (390, 460)]


def rectangle(locator):
    return locator.evaluate('el => { const r=el.getBoundingClientRect(); return {left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height}; }')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    original = (STATIC / 'owner.html').read_text()
    html = re.sub(r'<script\b[^>]*>.*?</script>', '', original, flags=re.S | re.I)
    results = []
    with sync_playwright() as p:
        for engine in ('chromium', 'webkit'):
            browser = getattr(p, engine).launch(headless=True)
            for width, height in SIZES:
                context = browser.new_context(viewport={'width': width, 'height': height})
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                def route_request(route):
                    url = urlsplit(route.request.url)
                    if url.hostname != 'import-layout.test':
                        route.abort()
                    elif url.path == '/owner':
                        route.fulfill(status=200, content_type='text/html', body=html)
                    elif url.path.startswith('/assets/'):
                        file = (STATIC / url.path.removeprefix('/assets/')).resolve()
                        if STATIC.resolve() not in file.parents or not file.is_file():
                            route.fulfill(status=404, body='')
                        else:
                            route.fulfill(status=200, content_type=mimetypes.guess_type(file.name)[0] or 'application/octet-stream', body=file.read_bytes())
                    else:
                        route.abort()
                page.route('**/*', route_request)
                page.goto('http://import-layout.test/owner', wait_until='load')
                page.evaluate('''() => {
                    document.body.classList.remove('hub-restoring');
                    document.querySelector('.hub-loading')?.remove();
                    document.getElementById('owner-auth-view').remove();
                    document.getElementById('owner-portal-view').classList.remove('hidden');
                    document.querySelectorAll('[id^="owner-view-"]').forEach(el => {
                        el.classList.add('hidden'); el.style.display='none';
                    });
                    const view=document.getElementById('owner-view-inventory');
                    view.classList.remove('hidden'); view.style.display='block';
                    const spacer=document.createElement('div'); spacer.style.height='1400px'; view.append(spacer);
                    window.apiRequest=async () => ({items:[]});
                }''')
                page.add_script_tag(content=(STATIC / 'owner-imports.js').read_text())
                trigger = page.locator('#owner-import-trigger')
                trigger.scroll_into_view_if_needed()
                trigger.click()
                menu = page.locator('#owner-import-menu')
                menu_box = rectangle(menu)
                assert menu_box['left'] >= -1 and menu_box['right'] <= width + 1, (engine, width, menu_box)
                labels = []
                for button in menu.locator('button').all():
                    box = rectangle(button)
                    assert box['left'] >= -1 and box['right'] <= width + 1, (engine, width, box)
                    for label in button.locator('strong,small').all():
                        text_box = rectangle(label)
                        assert text_box['left'] >= menu_box['left'] and text_box['right'] <= menu_box['right'] + 1
                        labels.append(label.inner_text())
                assert any('Collectr' in label for label in labels), labels
                if width == 390 and height == 844:
                    page.screenshot(path=str(OUT / f'{engine}-menu-{width}.png'))
                menu.locator('[data-owner-import-adapter="COLLECTR"]').click()
                dialog = page.locator('#owner-import-dialog')
                dialog.wait_for(state='visible')
                box = rectangle(dialog)
                assert box['left'] >= -1 and box['right'] <= width + 1, (engine, width, box)
                assert box['top'] >= -1 and box['bottom'] <= height + 1, (engine, width, height, box)
                assert dialog.evaluate('el => el.scrollWidth <= el.clientWidth + 1'), (engine, width, 'dialog overflow')
                # Render the real pending-row review, not hand-written form markup.
                page.evaluate('''() => {
                    const batch='2ac107db-2a16-4147-adf6-96be9db1a613';
                    const card='b975c7e7-9d56-4414-856f-6629b2370e56';
                    const candidate={id:'13b203a7-dbe7-4bfc-b671-acd3bf7e4332', source_row:2, quantity:1,
                        status:'REVIEW', issues:['unrecognised_collectr_grade'], catalogue_id:card,
                        normalized_record:{name:'Synthetic card needing slab confirmation',game:'Pokemon',set_name:'Synthetic Set',card_number:'001',product_type:'CARD',language:'English'}};
                    window.__reviewWrites=0;
                    window.apiRequest=async (url) => {
                        if(url.endsWith('/resolve')) {window.__reviewWrites++; throw new Error('No save expected in layout check');}
                        if(url.endsWith('/upload')) return {batch_id:batch,summary:{added_units:0,review_rows:1}};
                        if(url.endsWith('/'+batch)) return {batch:{id:batch,status:'PREVIEW',version:1,automatic_intake:true,adapter:'COLLECTR',source_rows:1,physical_units:1},candidates:[candidate]};
                        if(url.includes('/catalogue-search?')) return {items:[{id:card,...candidate.normalized_record}]};
                        return {items:[]};
                    };
                }''')
                page.locator('#owner-import-file').set_input_files({
                    'name': 'synthetic-review.csv', 'mimeType': 'text/csv',
                    'buffer': b'Name,Number\nSynthetic card,001\n',
                })
                page.wait_for_function("document.getElementById('owner-import-message').textContent.includes('headers detected')")
                page.locator('#owner-import-preview').click()
                page.locator('.owner-import-row-actions button').first.click()
                page.locator('.owner-import-resolver-result button').wait_for()
                page.get_by_label('Card format', exact=True).select_option('GRADED')
                page.get_by_label('Grading company', exact=True).fill('BGS')
                page.locator('.owner-import-resolver-result button').click()
                assert page.evaluate('window.__reviewWrites') == 0, 'Incomplete grade submitted'
                page.get_by_label('Grade on slab label', exact=True).fill('9.5')
                for control in page.locator('.owner-import-resolver input:visible, .owner-import-resolver select:visible, .owner-import-resolver button:visible').all():
                    bounds = rectangle(control)
                    assert bounds['left'] >= box['left'] and bounds['right'] <= box['right'] + 1, (engine, width, 'review control overflow', bounds)
                assert dialog.evaluate('el => el.scrollWidth <= el.clientWidth + 1')
                if (width, height) in ((390, 844), (1440, 1000)):
                    page.locator('.owner-import-card-details').scroll_into_view_if_needed()
                    page.screenshot(path=str(OUT / f'{engine}-review-{width}.png'))
                page.evaluate('''() => {
                    const results=document.getElementById('owner-import-preview-section'); results.hidden=false;
                    const rows=document.getElementById('owner-import-rows');
                    for(let i=0;i<40;i++) { const row=document.createElement('p'); row.textContent='Synthetic review row '+i+' — confirm the exact language and printing.'; rows.append(row); }
                }''')
                body = page.locator('.owner-import-dialog-body')
                body.evaluate('el => {el.scrollTop=el.scrollHeight;}')
                assert body.evaluate('el => el.scrollTop > 0'), (engine, width, 'body must scroll')
                close_box = rectangle(page.locator('#owner-import-close'))
                assert close_box['top'] >= 0 and close_box['bottom'] <= height, (engine, width, 'close clipped')
                if width == 390 and height == 844:
                    body.evaluate('el => {el.scrollTop=0;}')
                    page.screenshot(path=str(OUT / f'{engine}-dialog-{width}.png'))
                page.locator('#owner-import-close').click()
                assert not dialog.is_visible()
                assert page.locator('#owner-import-file').evaluate('el => el.files.length') == 0
                assert page.locator('#owner-import-rows').inner_text() == ''
                assert page.locator('#owner-import-summary').inner_text() == ''
                assert page.locator('#owner-import-map-fields').inner_text() == ''
                assert not errors, errors
                results.append({'engine': engine, 'width': width, 'height': height, 'menu': menu_box, 'dialog': box, 'passed': True})
                context.close()
            browser.close()
    (OUT / 'geometry.json').write_text(json.dumps(results, indent=2))
    print(f'PASS: {len(results)} Chromium/WebKit actual-template layout cases; menu labels inside viewport, dialog/close visible, inner content scrollable. Mocked history; no production requests.')


if __name__ == '__main__':
    main()
