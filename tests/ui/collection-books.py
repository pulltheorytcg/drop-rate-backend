"""Actual book form in phone/desktop browsers with synthetic API responses."""
import json
import os
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2] / 'backend/app/static'
OUT = Path(os.getenv('COLLECTION_LAYOUT_DIR', '/tmp/collection-confirmation'))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        for engine in os.getenv('BROWSER_ENGINES', 'chromium,webkit').split(','):
            options = {'headless': True}
            if engine == 'chromium' and os.getenv('CHROMIUM_EXECUTABLE'):
                options['executable_path'] = os.environ['CHROMIUM_EXECUTABLE']
            browser = getattr(p, engine).launch(**options)
            for width in (390, 1440):
                page = browser.new_page(viewport={'width': width, 'height': 900})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                html = re.sub(r'<script[^>]*>.*?</script>', '', (ROOT/'owner.html').read_text(), flags=re.S)
                # Match the deployed HTTPS secure context for crypto.randomUUID.
                # Every request is still intercepted; no account or live API is used.
                page.route('**/*', lambda route: route.fulfill(body=html, content_type='text/html')
                           if route.request.url == 'https://book-fixture.test/' else route.abort())
                page.goto('https://book-fixture.test/')
                for name in ('owner-portal.css', 'owner-imports.css', 'owner-books.css'):
                    page.add_style_tag(content=(ROOT/name).read_text())
                page.add_script_tag(content='''
                    const state={session:{user:{id:'seller-a'}}};
                    window.calls=[];window.marketCalls=[];window.mode='success';
                    async function loadOwnerInventory(){if(mode==='refresh-error')throw new Error('Refresh failed');}
                    async function loadOwnerOverview(){}
                    async function apiRequest(url,options){
                      if(url.endsWith('/market-value')){marketCalls.push({url,...options});return {status:'UNAVAILABLE',market_value_minor:null,reason:'No stored value for this fixture.'};}
                      calls.push({url,...options});
                      if(mode==='lost'){mode='success';throw new Error('Response lost');}
                      if(mode==='invalid'){const e=new Error('Check issue number');e.status=422;throw e;}
                      return {catalogue:{name:'Fixture comic'},inventory:{id:'fixture-copy'}};
                    }
                ''')
                page.add_script_tag(content=(ROOT/'owner-books.js').read_text())
                # Selecting a catalogue edition prefills only book facts. It
                # must never submit a copy, imply a first printing, or price it.
                page.evaluate("""DropRateBooks.open({book:{system_code:'MANGA',series_title:'One Piece',issue_number:'1',
                    publisher:'VIZ Media',book_format:'MANGA',language:'English',release_year:2003,
                    barcode_gtin:'9781569319017',printing_number:null,condition:'Mint',price:999}})""")
                assert page.locator('#owner-book-series').input_value() == 'One Piece'
                assert page.locator('#owner-book-barcode').input_value() == '9781569319017'
                for field in ('printing','condition','cost','price','grade','certificate'):
                    assert page.locator('#owner-book-'+field).input_value() == ''
                assert page.locator('#owner-book-number-text').inner_text() == 'Volume number'
                assert not page.evaluate('calls.length')
                page.locator('#owner-book-close').click()
                page.evaluate("document.querySelector('[data-owner-add-book]').click()")
                assert not errors, errors
                page.locator('#owner-book-series').fill('Amazing Spider-Man')
                page.locator('#owner-book-number').fill('1')
                page.locator('#owner-book-year').fill('2022')
                page.locator('#owner-book-cover').fill('Cover A')
                page.locator('#owner-book-copy-details').evaluate('e=>e.open=true')
                page.locator('#owner-book-state').select_option('GRADED')
                assert page.locator('#owner-book-grader option').evaluate_all('xs=>xs.map(x=>x.value)') == ['CGC']
                page.locator('#owner-book-grade').fill('9.8')
                page.locator('#owner-book-certificate').fill('fixture-cert')
                assert page.locator('#owner-book-condition').is_hidden()
                assert not page.evaluate('calls.length')
                assert page.locator('#owner-book-dialog').evaluate('e=>e.scrollWidth<=e.clientWidth+1')
                page.screenshot(path=str(OUT/f'{engine}-{width}-graded-book.png'))
                page.evaluate("mode='lost'")
                page.locator('#owner-book-save').click()
                page.get_by_role('button', name='Retry this book').wait_for()
                assert page.locator('#owner-book-series').is_disabled()
                page.locator('#owner-book-close').click()
                page.evaluate("document.querySelector('[data-owner-add-book]').click()")
                assert page.locator('#owner-book-series').input_value() == 'Amazing Spider-Man'
                page.locator('#owner-book-save').click()
                page.get_by_role('button', name='Added to collection').wait_for()
                writes = page.evaluate('calls')
                assert len(writes) == 2 and writes[0]['body'] == writes[1]['body']
                assert writes[0]['headers']['Idempotency-Key'] == writes[1]['headers']['Idempotency-Key']
                body = json.loads(writes[0]['body'])
                assert body['grading_company'] == 'CGC' and body['grade'] == '9.8' and body['condition'] is None
                assert body['new_catalogue']['comic_printing']['system_code'] == 'MARVEL_COMICS'
                page.locator('#owner-book-cancel').click()
                page.evaluate("document.querySelector('[data-owner-add-book]').click();mode='refresh-error'")
                page.locator('#owner-book-category').select_option('MANGA')
                page.locator('#owner-book-series').fill('One Piece')
                page.locator('#owner-book-number').fill('2')
                page.locator('#owner-book-publisher').fill('VIZ Media')
                page.locator('#owner-book-language').fill('Japanese')
                page.locator('#owner-book-copy-details').evaluate('e=>e.open=true')
                page.locator('#owner-book-condition').select_option('Very Good')
                page.locator('#owner-book-barcode').fill('978-1-234567-89-0')
                assert page.locator('#owner-book-format').is_hidden()
                assert page.locator('#owner-book-number-text').inner_text() == 'Volume number'
                page.screenshot(path=str(OUT/f'{engine}-{width}-manga.png'))
                page.locator('#owner-book-save').click()
                page.get_by_role('button', name='Added to collection').wait_for()
                assert page.locator('#owner-book-save').is_disabled()
                body = json.loads(page.evaluate('calls.at(-1).body'))
                assert body['new_catalogue']['comic_printing']['book_format'] == 'MANGA'
                assert body['condition'] == 'Very Good' and body['grading_company'] is None
                assert not any('/sync' in call['url'] for call in page.evaluate('calls'))
                page.locator('#owner-book-cancel').click()
                for company, grade in (('CGC', '9.8'), ('BGS', '9.5')):
                    page.evaluate("document.querySelector('[data-owner-add-book]').click();mode='success'")
                    page.locator('#owner-book-category').select_option('MANGA')
                    page.locator('#owner-book-copy-details').evaluate('e=>e.open=true')
                    page.locator('#owner-book-state').select_option('GRADED')
                    assert page.locator('#owner-book-grader option').evaluate_all('xs=>xs.map(x=>x.value)') == ['CGC', 'BGS']
                    if company == 'BGS':
                        page.locator('#owner-book-grade').fill('9.8')
                        page.locator('#owner-book-certificate').fill('old-cgc-cert')
                        page.locator('#owner-book-grader').select_option('BGS')
                        assert page.locator('#owner-book-grade').input_value() == ''
                        assert page.locator('#owner-book-certificate').input_value() == ''
                        page.locator('#owner-book-grade').fill('9.5')
                        page.locator('#owner-book-certificate').fill('old-bgs-cert')
                        for category in ('DC_COMICS', 'OTHER_COMICS', 'MARVEL_COMICS'):
                            page.locator('#owner-book-category').select_option(category)
                            assert page.locator('#owner-book-grader option').evaluate_all('xs=>xs.map(x=>x.value)') == ['CGC']
                            assert page.locator('#owner-book-grade').input_value() == ''
                            assert page.locator('#owner-book-certificate').input_value() == ''
                        page.locator('#owner-book-category').select_option('MANGA')
                        page.locator('#owner-book-grader').select_option('BGS')
                    page.locator('#owner-book-series').fill('One Piece')
                    page.locator('#owner-book-number').fill('1')
                    page.locator('#owner-book-publisher').fill('VIZ Media')
                    page.locator('#owner-book-grade').fill(grade)
                    page.locator('#owner-book-certificate').fill(f'fixture-manga-{company}')
                    page.locator('#owner-book-save').click()
                    page.get_by_role('button', name='Added to collection').wait_for()
                    body = json.loads(page.evaluate('calls.at(-1).body'))
                    assert body['new_catalogue']['comic_printing']['system_code'] == 'MANGA'
                    assert body['grading_company'] == company and body['grade'] == grade
                    assert body['certificate_number'] == f'fixture-manga-{company}' and body['condition'] is None
                    page.locator('#owner-book-cancel').click()
                page.evaluate("document.querySelector('[data-owner-add-book]').click();state.session={user:{id:'seller-b'}}")
                page.locator('#owner-book-form').dispatch_event('submit')
                assert not page.locator('#owner-book-dialog').is_visible()
                assert len(page.evaluate('calls')) == 5
                assert not errors, errors
                page.close()
            browser.close()
    print('PASS: CGC comics, CGC/BGS manga, category-specific choices, certificate reset, responsive form, immutable retry, refresh failure and account change; fixture API only.')


if __name__ == '__main__':
    main()
