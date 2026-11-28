from datetime import date
from pathlib import Path

import pytest

from app.reference_feeds import ReferenceFeedError
from app.reference_one_piece import OFFICIAL_SETS,booster_sets,official_cards,official_feed,released_products


INDEX='''<select><option value>Recording</option><option value="ALL">ALL</option>
 <option value="569114">BOOSTER PACK -Old- [OP14-EB04]</option>
 <option value="569115">BOOSTER PACK &lt;br class="spInline"&gt;-ADVENTURE ON KAMI’S ISLAND- [OP15-EB04]</option>
 <option value="569116">BOOSTER PACK -THE TIME OF BATTLE- [OP-16]</option>
 <option value="569117">BOOSTER PACK -THE WORLD’S STRONGEST WARRIORS- [OP-17]</option>
 <option value="569118">BOOSTER PACK -THE DOMINANCE OF GOD- [OP-18]</option></select>'''
RELEASES={'OP15EB04':date(2026,4,3),'OP16':date(2026,6,12),'OP17':date(2026,8,28),'OP18':date(2026,11,20)}


def test_discovery_adds_new_released_checklists_and_preserves_reviewed_identity():
    rows=booster_sets(INDEX,RELEASES,today=date(2026,10,10))
    assert [r['set_id'] for r in rows]==['569115','569116','569117']
    assert rows[1]['name']==OFFICIAL_SETS[0]['name']
    assert '<br' not in rows[0]['name']
    assert len(booster_sets(INDEX,RELEASES,today=date(2026,11,20)))==4
    with pytest.raises(ReferenceFeedError):booster_sets(INDEX,{},today=date(2026,10,10))


def test_release_metadata_pagination_and_dates_are_bounded():
    html='''<li class="linkListColBox"><h4 class="linkListColTitle">BOOSTER PACK -A- [OP-17]</h4>
      <time datetime="2026-08-28">August 28, 2026</time></li><a href="?page=18">Last</a>
      <a href="https://evil.test/products/?page=9999">Ignore</a>'''
    assert released_products(html)==({'OP17':date(2026,8,28)},18)
    with pytest.raises(ReferenceFeedError):released_products(html.replace('?page=18','?page=999'))
    with pytest.raises(ReferenceFeedError):released_products(html.replace('datetime="2026-08-28"','datetime="not-a-date"'))


def test_official_zoro_sp_and_promo_reprints_keep_the_exact_image_identity():
    content=(Path(__file__).parent/'fixtures/one_piece_op17_zoro.html').read_text()
    rows=official_cards(content,{**OFFICIAL_SETS[0],'declared_card_count':2})
    zoro=next(r for r in rows if r['card_number']=='EB04-007')
    assert zoro['provider_id']=='EB04-007_p2' and zoro['rarity']=='SP CARD'
    assert 'EB04-007_p2.png' in zoro['image_url']
    assert any(r['card_number']=='P-084' for r in rows)
    with pytest.raises(ReferenceFeedError):official_cards(content,{**OFFICIAL_SETS[0],'declared_card_count':3})


def _single_release_feed(content):
    """One released booster in range, so one checklist page is read."""
    from app.reference_one_piece import PRODUCTS
    index='<select><option value="569116">BOOSTER PACK -THE TIME OF BATTLE- [OP-16]</option></select>'
    products=('<li class="linkListColBox"><h4 class="linkListColTitle">Set [OP-16]</h4>'
              '<time datetime="2026-06-12"></time></li>')
    class Feed:
        def __init__(self):self.urls=[]
        async def get_text(self,url):
            self.urls.append(url)
            if url==PRODUCTS:return products
            return index if len(self.urls)==2 else content
    return Feed()


@pytest.mark.asyncio
@pytest.mark.parametrize('label',['2 results','2 Results','2 RESULTS'])
async def test_result_count_label_is_read_in_any_letter_case(label):
    # The site changed "results" to "Results" in November 2026; the exact-case
    # check then failed every run and OP-18 never reached the catalogue.
    content=(Path(__file__).parent/'fixtures/one_piece_op17_zoro.html').read_text().replace('2 results',label)
    assert label in content
    yielded=[row async for row in official_feed(_single_release_feed(content))]
    assert len(yielded)==1
    record,cards=yielded[0]
    assert record['set_id']=='569116' and record['declared_card_count']==2 and len(cards)==2


@pytest.mark.asyncio
@pytest.mark.parametrize('label,message',[
    ('2 cards','result count is missing'),          # a different wording still stops
    ('Results','result count is missing'),          # no number
    ('2 Results found','result count is missing'),  # extra text
    ('12345 Results','result count is missing'),    # beyond four digits
    ('3 Results','incomplete or contains duplicate'),  # count must equal the cards read
])
async def test_result_count_stays_strict_about_everything_but_case(label,message):
    content=(Path(__file__).parent/'fixtures/one_piece_op17_zoro.html').read_text().replace('2 results',label)
    yielded=[]
    with pytest.raises(ReferenceFeedError,match=message):
        async for row in official_feed(_single_release_feed(content)):yielded.append(row)
    assert not yielded


@pytest.mark.asyncio
async def test_duplicate_printings_across_releases_abort_before_any_set_is_written():
    from app.reference_one_piece import PRODUCTS
    content=(Path(__file__).parent/'fixtures/one_piece_op17_zoro.html').read_text()
    products=''.join(f'<li class="linkListColBox"><h4 class="linkListColTitle">Set [{code}]</h4><time datetime="{stamp.isoformat()}"></time></li>' for code,stamp in RELEASES.items())
    class Feed:
        index_read=False
        async def get_text(self,url):
            if url==PRODUCTS:return products
            if not self.index_read:
                self.index_read=True;return INDEX
            return content
    yielded=[]
    with pytest.raises(ReferenceFeedError,match='shared by multiple'):
        async for row in official_feed(Feed()):yielded.append(row)
    assert not yielded
