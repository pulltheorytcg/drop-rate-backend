"""Beginner book review in phone/desktop browsers; synthetic provider + photos."""
import base64
import json
import os
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2] / 'backend/app/static'
OUT = Path(os.getenv('COLLECTION_LAYOUT_DIR', '/tmp/collection-confirmation'))
# Valid synthetic cover with book proportions; never a customer/publisher image.
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAKAAAADwCAIAAAAII/iNAAAFC0lEQVR4nO3czXFcRRhG4c9AEs6DLJwGXhGACcEOgB0hkRJVLG7hkiVmdGdu/7x9+py1i+p+HzeSJdkfPn76XMbtp9kHsL4JDE9geALDExiewPAEhicwPIHhCQxPYHgCwxMY3i/nf+nfX/7pdw57tF+//Xzml/mC4QkMT2B4AsMTGJ7A8ASGJzA8geEJDE9geALDExiewPAEhicwPIHhCQxPYHgCwxMYnsDwBIYnMDyB4QkMT2B4AsMTGJ7A8ASGJzA8geEJDE9geALDExiewPAEhicwPIHhCQxPYHgCw3vgHyM9+a9fWlS+YHgCwxMYnsDwBIYnMDyB4QkMT2B4AsMTGJ7A8ASGJzA8geEJDE9geALD2w74j99/m32Eoe0FfOhuZbwR8EvXfYw3At6zXYDfPtlNHvEWwLcsdzDmA99XxBvzgTcPDnzmgbIfMRn4vBzYGAv8qBnVGAtsR0zg554j8hEDga848YxpwNeFYMY0YHsVCrjV4yM9Yg5wWxWMMQS4hwfDmADcTwJgTAC2Oy0P3PuRrf6I1wYes/7SxgsDj9x9XeOFge1MqwKPf1KLPuIlgWdtvaLxesBzV17OeD1ge6jFgBMeUMIZzrcScM6yOSd5t2WA0zZNO8+tlgG251oDOPO5ZJ7qVQsAJ++YfLajdOD8BcNPmA5sF4sGDn8c30s+Zy5w8mpviz1tKHDsXnfKPHMicOZSZwo8eSKwNSwOOPARPFTa+bOA09Z5rqhbBAFH7XKxnLsEAVuPUoBzfsu3KuRGEcAhWzQv4V7zgRNW6Nf0280Htq5NBp7+G3xAc+84E3gH3aOJN50GvI/u0az7+jEY3hzg3Z7v0ZRbTwDeU/do/N1HA++sezR4gaHA6h6N3MFPsuCNA/b5vmzYGoOA1X3bmE1GAKt7qwHL+DEYXndgn+/9eu/TF1jdM3VdqSOwuufrt5Ufg+H1Avb5PlqnxboAq/tcPXZrD6zulZqv58dgeI2Bfb7Xa7thS2B1W9VwyZbAX//8q+F/becaLtn4f9EaX6/thu0/ydL4Ss3X6/JZtMbP1WO3Xn9M0vjROi3W8c/BGp+v31Z9v9Ch8Zm6rtT9K1ka36/3PiO+VKnxrQYsM+hr0Rq/bcwm477ZoPHLhq0x9LtJGh+N3GH0tws1HrzAhO8H72w8/u5zvuG/p/GUW0/7iY7djGfdd+aP7OxjPPGmk38mawfjuXec/0N3bOPpt5sPXAErdCrhXhHAlbFF20JulAJcMYs0KecuQcCVtMuVom6RBVxh6zxR2vnjgCtvo/MFnjwRuCKXerfMM3/4+Onz7DPca4m/DpNJexT6gr+XvN1R+AnTgSt7weSzHS0AXKk7Zp7qVWsAV96aaee51TLAlbRpzknebSXgylg24QznWwy4Zu+7lm6tCFzzVl5OtxYFrhlbr6hb6wLX2MUX1a2lgWvU7uvq1urA1X/9pXULAFw9DVbXLQZw9ZEA6BYGuFp7MHSLBFztVDC6BQOuFjYk3eIB1zUhmG4hgetZJ55uUYHrcS2kboGB6xEzqm6xgeucHFi38MD1nh9bt3YArtuKeN3aBLj+z3IH3doHuH4U3US3tgKu/1z30a38v5tkF9vrBW+YwPAEhicwPIHhCQxPYHgCwxMYnsDwBIYnMDyB4QkMT2B4AsMTGJ7A8ASGJzA8geEJDE9geALDExiewPAEhicwPIHhCQxPYHgCwxMYnsDw/gWkiE9v2HWHHwAAAABJRU5ErkJggg==')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        for engine in os.getenv('BROWSER_ENGINES', 'chromium,webkit').split(','):
            browser = getattr(p,engine).launch(headless=True)
            for width in (390,1440):
                print(f'Book research browser: {engine} {width}',flush=True)
                page = browser.new_page(viewport={'width':width,'height':900})
                errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
                html = re.sub(r'<script[^>]*>.*?</script>','',(ROOT/'owner.html').read_text(),flags=re.S)
                def respond(route):
                    if route.request.url=='https://book-research.test/':
                        route.fulfill(body=html,content_type='text/html')
                    elif '/books/research/' in route.request.url or '/catalogue-browser/reference-image?' in route.request.url:
                        assert route.request.headers.get('authorization')=='Bearer fixture-only'
                        route.fulfill(body=PNG,content_type='image/png')
                    elif route.request.url.startswith(('blob:','data:')):
                        route.continue_()
                    else:
                        route.abort()
                page.route('**/*',respond); page.goto('https://book-research.test/')
                for name in ('owner-portal.css','owner-imports.css','owner-books.css'):
                    page.add_style_tag(content=(ROOT/name).read_text())
                page.add_script_tag(content='''
                  const state={session:{access_token:'fixture-only',user:{id:'seller-a'}}};window.calls=[];
                  async function loadOwnerInventory(){} async function loadOwnerOverview(){}
                  async function apiRequest(url,options){calls.push({url,...options});return {catalogue:{name:'Fixture book'},inventory:{id:'fixture'}};}
                  window.run='11111111-1111-4111-8111-111111111111';
                  window.fields={system_code:'MARVEL_COMICS',series_title:'Fixture Adventure',issue_number:'1',
                    publisher:'Marvel',book_format:'SINGLE_ISSUE',language:'English',release_year:2025,printing_number:null};
                  window.options={run_id:run,status:'NEEDS_REVIEW',fields,uncertain_fields:['printing_number'],warnings:[],research:{
                    status:'CANDIDATES',message:'Compare these publisher covers with your copy.',candidates:[
                    {id:'aaaaaaaaaaaaaaaaaaaaaaaa',fields:{...fields,cover_code:'Cover A'},
                      source_url:'https://www.marvel.com/comics/issue/1/fixture',source_title:'Fixture A',
                      image_path:'/api/v1/owner/books/research/'+run+'/cover/aaaaaaaaaaaaaaaaaaaaaaaa',explanation:'First cover option.'},
                    {id:'bbbbbbbbbbbbbbbbbbbbbbbb',fields:{...fields,cover_code:'Cover B',printing_number:2},
                      source_url:'https://www.marvel.com/comics/issue/2/fixture',source_title:'Fixture B',
                      image_path:'/api/v1/owner/books/research/'+run+'/cover/bbbbbbbbbbbbbbbbbbbbbbbb',explanation:'Second cover option.'}
                  ]}};
                ''')
                page.add_script_tag(content=(ROOT/'owner-books.js').read_text())
                page.evaluate('DropRateBooks.open({recognition:options})')
                assert page.locator('#owner-book-title').inner_text()=='Confirm your book'
                assert page.locator('.owner-book-candidate').count()==2
                assert not page.locator('#owner-book-details').evaluate('(e)=>e.open')
                assert not page.locator('#owner-book-photo-details').evaluate('(e)=>e.open')
                assert not page.evaluate('calls.length')
                page.locator('.owner-book-candidate').nth(1).get_by_role('button').click()
                assert page.locator('#owner-book-cover').input_value()=='Cover B'
                assert page.locator('#owner-book-printing').input_value()=='2'
                assert page.locator('#owner-book-year').input_value()=='2025'
                assert page.locator('#owner-book-condition').input_value()==''
                assert page.locator('#owner-book-price').input_value()==''
                page.wait_for_function('Array.from(document.querySelectorAll(".owner-book-cover img:not([hidden])")).filter(img => img.complete && img.naturalWidth === 160 && img.naturalHeight === 240).length === 2')
                assert not page.evaluate('document.querySelector("#owner-book-dialog").scrollWidth > document.querySelector("#owner-book-dialog").clientWidth+2')
                assert page.locator('.owner-book-candidate').evaluate_all('(cards)=>cards.every(card => card.querySelector("button").getBoundingClientRect().right <= card.getBoundingClientRect().right)')
                page.screenshot(path=str(OUT/f'{engine}-{width}-book-cover-choice.png'))
                page.locator('#owner-book-save').click()
                page.get_by_role('button',name='Added to collection').wait_for()
                body=json.loads(page.evaluate('calls[0].body'))
                assert body['research_candidate_id']=='bbbbbbbbbbbbbbbbbbbbbbbb' and body['research_run_id']==page.evaluate('run')
                assert body['new_catalogue']['comic_printing']['cover_code']=='Cover B'
                assert body['condition'] is None and body['store_price_minor'] is None
                assert 'image_url' not in json.dumps(body) and 'market_value' not in json.dumps(body)
                page.locator('#owner-book-cancel').click()
                # Editing a researched edition drops its artwork linkage.
                page.evaluate('DropRateBooks.open({recognition:options})')
                page.locator('.owner-book-candidate').first.get_by_role('button').click()
                page.locator('#owner-book-details summary').click()
                page.locator('#owner-book-printing').fill('3')
                page.locator('#owner-book-save').click();page.get_by_role('button',name='Added to collection').wait_for()
                body=json.loads(page.evaluate('calls.at(-1).body'))
                assert 'research_candidate_id' not in body and body['new_catalogue']['comic_printing']['printing_number']==3
                page.locator('#owner-book-cancel').click()
                # Research outage keeps usable OCR and doesn't require expertise.
                page.evaluate("DropRateBooks.open({recognition:{...options,research:{status:'UNAVAILABLE',candidates:[],message:'Add a barcode photo to help.'}}})")
                assert page.locator('#owner-book-series').input_value()=='Fixture Adventure'
                assert page.locator('#owner-book-photo-details').evaluate('(e)=>e.open')
                assert 'save it as unknown' in page.locator('#owner-book-photo-help').inner_text()
                assert page.locator('#owner-book-printing').input_value()==''
                page.locator('#owner-book-close').click()
                # A catalogue book keeps its cover in a short, prefilled confirmation.
                page.evaluate("""() => {
                  const id='22222222-2222-4222-8222-222222222222';
                  const book={...fields,book_format:'SINGLE_ISSUE'};
                  DropRateBooks.open({book,catalogue:{catalogue_id:id,name:'Fixture Adventure #1',
                    reference_image_path:'/api/v1/catalogue-browser/reference-image?provider=Official+Publisher&system_code=MARVEL_COMICS&language=English&provider_id='+id+'&reference_kind=book'}});
                }""")
                assert page.locator('#owner-book-title').inner_text() == 'Is this your book?'
                assert not page.locator('#owner-book-details').evaluate('e=>e.open')
                assert not page.locator('#owner-book-copy-details').evaluate('e=>e.open')
                page.wait_for_function('document.querySelector("#owner-book-selected img").naturalWidth===160')
                assert page.locator('#owner-book-selected').is_visible()
                page.locator('#owner-book-details summary').click()
                page.locator('#owner-book-number').fill('2')
                assert not page.locator('#owner-book-selected').is_visible(), 'An edited edition kept the prior cover'
                # No foreign-owner cover fetches or stale source links survive reset.
                page.evaluate("state.session.user.id='seller-b';DropRateBooks.reset()")
                assert not page.locator('#owner-book-dialog').is_visible()
                assert not errors,errors
                page.close()
            browser.close()


if __name__=='__main__':main()
