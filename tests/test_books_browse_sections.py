"""Only actual seller-entered collectible books appear in comics/manga browse.
No catalogue rows, price records or Shopify listings are invented.
"""
import json
from pathlib import Path
from uuid import uuid4

from app import catalogue_browser as browser

ROOT=Path(__file__).resolve().parents[1]


def test_book_categories_always_exist_without_invented_inventory():
    assert browser.browse_systems('COMICS') == ['MARVEL_COMICS','DC_COMICS','OTHER_COMICS']
    assert browser.browse_systems('MANGA') == ['MANGA']
    grouped=browser.browse_games([
        {'system_code':'MARVEL_COMICS','game':'Marvel Comics','languages':['English'],'products':2,'sets':1},
        {'system_code':'DC_COMICS','game':'DC Comics','languages':['English'],'products':3,'sets':2},
        {'system_code':'OTHER_COMICS','game':'Other Comics','languages':['Spanish'],'products':1,'sets':1},
        {'system_code':'MANGA','game':'Manga','languages':['English','Japanese'],'products':0,'sets':0},
    ])
    assert grouped[0]['system_code']=='COMICS'
    assert grouped[0]['game']=='Comics'
    assert grouped[0]['products']==6
    assert grouped[0]['sets']==4
    assert grouped[0]['languages']==['English','Spanish']
    assert grouped[1]['system_code']=='MANGA'
    assert grouped[1]['products']==0


def test_comics_manga_are_real_canonical_profiles_not_fabricated_reference_games():
    sql=browser.SOURCE_CTE
    assert "p.product_type='COMIC' and pr.collectible_type='COMIC'" in sql
    assert "pr.system_code in ('MARVEL_COMICS','DC_COMICS','OTHER_COMICS','MANGA')" in sql
    assert "i.owner_id=$1" in sql
    assert "'CATALOGUE'::text" in sql
    assert "tcg.reference_market_prices" in sql
    assert "e.provider=''" not in sql
    for game in ('COMICS','MANGA'):
        query,args=browser.product_query(owner_id=uuid4(),system_code=game,product_type='COMIC')
        assert args[1]==browser.browse_systems(game)
        assert 'e.product_type=' in query
        assert 'e.system_code=any(' in query
        assert 'i.owner_id=$1' in query
        assert 'from tcg.inventory_items' in query
        assert 'insert into' not in query.lower()
    # The existing browser card-intake API deliberately doesn't accept COMIC,
    # because books use the separate owner/books/intake flow with full printing.
    assert 'product_type: Literal["", "CARD", "SEALED", "COMIC"]' in ROOT.joinpath('backend/app/catalogue_browser.py').read_text()


def test_unpublished_brand_theme_has_real_comics_and_manga_sections():
    root=ROOT/'storefront/theme'
    template=(root/'templates/index.json').read_text()
    body=template.split('*/',1)[1].strip()
    data=json.loads(body)
    discovery=data['sections']['discovery']
    assert discovery['block_order']==['pokemon','onepiece','comics','manga']
    assert discovery['blocks']['comics']['settings']['collection']=='comics'
    assert discovery['blocks']['manga']['settings']['collection']=='manga'
    assert 'product' not in discovery['blocks']['comics']['settings']
    assert 'product' not in discovery['blocks']['manga']['settings']
    nav=(root/'sections/drop-rate-collection-routes.liquid').read_text()
    assert "assign comics = collections['comics']" in nav
    assert "assign manga = collections['manga']" in nav
    assert 'href="{{ comics.url }}">Comics</a>' in nav
    assert 'href="{{ manga.url }}">Manga</a>' in nav
    readme=(root/'README.md').read_text()
    assert "Role: `UNPUBLISHED`" in readme
    assert "live `Horizon` theme is not modified" in readme


def test_book_opening_never_uses_card_intake_or_infers_prices():
    js=(ROOT/'backend/app/static/catalogue-browser.js').read_text()
    owner=(ROOT/'backend/app/static/owner-books.js').read_text()
    entry=(ROOT/'backend/app/static/catalogue-browser-entry.js').read_text()
    assert "if(row.product_type===\"COMIC\")" in js
    assert "this.openBookIntake()" in js
    assert "window.DropRateBooks = {open" in owner
    assert "books:()=>seller?window.DropRateBooks?.open()" in entry
    assert "No independently verified market price is available" in js
    # Generic card ISBN/certificate data cannot be forged by the catalogue
    # browser; the existing book form enforces exact printing and owner.
    assert 'fetch(' not in js[js.index('openBookIntake()'):js.index('pickGame(game)')]
