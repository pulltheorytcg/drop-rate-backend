"""Real browser photo intake and late-response guards; synthetic API only."""
import base64
import json
import os
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]/'backend/app/static'
OUT=Path(os.getenv('COLLECTION_LAYOUT_DIR','/tmp/collection-confirmation'))


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        for engine in os.getenv('BROWSER_ENGINES','chromium,webkit').split(','):
            browser=getattr(p,engine).launch(headless=True)
            for width in (390,1440):
                print(f'Book scanner browser: {engine} {width}',flush=True)
                page=browser.new_page(viewport={'width':width,'height':900})
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                html=re.sub(r'<script[^>]*>.*?</script>','',(ROOT/'owner.html').read_text(),flags=re.S)
                def route_request(route):
                    if route.request.url=='https://book-scan.test/':route.fulfill(body=html,content_type='text/html')
                    elif route.request.url.startswith(('blob:https://book-scan.test/','data:image/')):route.continue_()
                    else:route.abort()
                page.route('**/*',route_request)
                page.goto('https://book-scan.test/')
                for name in ('owner-portal.css','owner-imports.css','owner-books.css','scanner-flow.css'):
                    page.add_style_tag(content=(ROOT/name).read_text())
                page.add_script_tag(content='''
                  const state={session:{user:{id:'seller-a'}}};window.calls=[];window.mode='ok';
                  window.scanResult={status:'NEEDS_REVIEW',fields:{system_code:'MANGA',book_format:'MANGA',series_title:'Fixture Manga',issue_number:'1',publisher:'VIZ Media'},uncertain_fields:['language','printing_number'],warnings:['Check the copyright page.']};
                  window.quote={status:'AVAILABLE',market_value_minor:1234,basis:'English · Near Mint'};
                  async function loadOwnerInventory(){} async function loadOwnerOverview(){}
                  async function apiRequest(url,options,retry){calls.push({url,...options,retry});
                    if(mode==='defer')return await new Promise(resolve=>window.release=resolve);
                    if(mode==='fail')throw new Error('Fixture provider unavailable');
                    if(url.endsWith('/recognize'))return scanResult;
                    if(url.endsWith('/market-value'))return quote;
                    return {catalogue:{name:'Fixture Manga'},inventory:{id:'fixture'}};
                  }
                ''')
                page.add_script_tag(content=(ROOT/'owner-books.js').read_text())
                page.add_script_tag(content=(ROOT/'scanner-flow.js').read_text())
                page.evaluate('''window.scanner=new DropRateScanner.Scanner({role:'seller',session:()=>state.session,request:apiRequest,afterSave:async()=>{},viewInventory:()=>{},openBooks:()=>DropRateBooks.open({scan:true})});scanner.dialog.showModal();''')
                page.locator('[data-action="books"]').click()
                assert page.locator('#owner-book-dialog').is_visible()
                assert page.evaluate('!scanner.dialog.open')
                assert page.locator('#owner-book-camera-file').get_attribute('capture')=='environment'
                data=page.evaluate("(()=>{const c=document.createElement('canvas');c.width=220;c.height=320;c.getContext('2d').fillRect(0,0,220,320);return c.toDataURL('image/png').split(',')[1]})()")
                photo={'name':'fixture.png','mimeType':'image/png','buffer':base64.b64decode(data)}
                def photo_count(count):
                    try:page.wait_for_function('n=>document.querySelectorAll("#owner-book-photos img").length===n',arg=count,timeout=10000)
                    except Exception as exc:
                        raise AssertionError(f'{engine} {width}: photos={page.locator("#owner-book-photos img").count()}, status={page.locator("#owner-book-scan-message").inner_text()}, errors={errors}') from exc
                def upload():
                    page.locator('#owner-book-gallery-file').set_input_files([photo])
                    photo_count(1)
                page.locator('#owner-book-gallery-file').set_input_files([photo,photo,photo])
                photo_count(3)
                assert page.locator('#owner-book-gallery').is_disabled()
                page.locator('#owner-book-recognize').click()
                page.wait_for_function("document.querySelector('#owner-book-series').value==='Fixture Manga'")
                assert page.locator('#owner-book-language').input_value()==''
                assert page.locator('#owner-book-printing').input_value()==''
                assert page.locator('#owner-book-condition').input_value()==''
                assert 'Check:' in page.locator('#owner-book-scan-message').inner_text()
                assert len(page.evaluate('calls'))==1 and page.evaluate('calls[0].retry') is False
                page.locator('#owner-book-language').fill('English')
                page.locator('#owner-book-printing').fill('1')
                page.locator('#owner-book-condition').select_option('Near Mint')
                page.locator('#owner-book-market-check').click()
                page.wait_for_function("document.querySelector('#owner-book-market-result').textContent.includes('£12.34')")
                assert page.locator('#owner-book-price').input_value()==''
                assert page.locator('#owner-book-dialog').evaluate('e=>e.scrollWidth<=e.clientWidth+1')
                page.screenshot(path=str(OUT/f'{engine}-{width}-book-scanner.png'))
                page.locator('#owner-book-save').click()
                page.get_by_role('button',name='Added to inventory').wait_for()
                writes=page.evaluate("calls.filter(x=>x.url.endsWith('/intake'))")
                assert len(writes)==1
                body=json.loads(writes[0]['body'])
                assert body['condition']=='Near Mint' and body['store_price_minor'] is None and body['acquisition_cost_minor'] is None
                assert body['new_catalogue']['comic_printing']['system_code']=='MANGA'
                assert page.locator('#owner-book-recognize').is_disabled()
                page.locator('#owner-book-cancel').click()
                page.evaluate("DropRateBooks.open();mode='defer'");upload()
                page.locator('#owner-book-recognize').click()
                page.wait_for_function("typeof release==='function'")
                page.evaluate("state.session={user:{id:'seller-b'}};release(scanResult)")
                page.wait_for_timeout(25)
                assert page.locator('#owner-book-series').input_value()==''
                page.locator('#owner-book-close').click();page.evaluate("DropRateBooks.open();mode='ok'");upload()
                page.locator('#owner-book-recognize').click()
                page.wait_for_function("document.querySelector('#owner-book-series').value==='Fixture Manga'")
                page.locator('#owner-book-language').fill('English')
                page.locator('#owner-book-condition').select_option('Near Mint')
                page.evaluate("mode='defer';release=null")
                page.locator('#owner-book-market-check').click()
                page.wait_for_function("typeof release==='function'")
                page.locator('#owner-book-number').fill('2')
                page.evaluate('release(quote)');page.wait_for_timeout(25)
                assert '£12.34' not in page.locator('#owner-book-market-result').inner_text()
                page.evaluate("mode='defer';release=null")
                page.locator('#owner-book-recognize').click()
                page.wait_for_function("typeof release==='function'")
                page.locator('#owner-book-close').click()
                page.evaluate("DropRateBooks.open();release(scanResult)");page.wait_for_timeout(25)
                assert page.locator('#owner-book-series').input_value()==''
                page.evaluate("mode='fail'");upload();page.locator('#owner-book-recognize').click()
                page.wait_for_function("document.querySelector('#owner-book-scan-message').textContent.includes('unavailable')")
                assert page.locator('#owner-book-photos img').count()==1
                assert not page.locator('#owner-book-fields').is_disabled()
                assert len(page.evaluate("calls.filter(x=>x.url.endsWith('/intake'))"))==1
                assert not errors,errors
                page.close()
            browser.close()
    print('PASS: book scanner launcher, real photo decoding, 3-photo limit, uncertain fields, market reference, explicit save, provider failure and late scan/price responses after edit, close or account change; synthetic API only.')


if __name__=='__main__':main()
