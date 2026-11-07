import asyncio
from copy import deepcopy

import pytest

from app.reference_artwork import match_existing_artwork, punk_pack_artwork, punk_pack_url
from app.reference_feeds import ReferenceFeeds


def card(ident='OP12-058', **changes):
    return dict(id=ident, pack_id='550112', name='Exact card',
                img_full_url=f'https://www.onepiece-cardgame.com/images/cardlist/card/{ident}.png?2602273', **changes)


def test_exact_parallel_and_language_images_are_kept():
    rows=[card(),card('OP12-058_p1')]
    art,evidence=punk_pack_artwork(rows,language='Japanese',set_id='550112')
    assert art['OP12-058']['image_url']!=art['OP12-058_p1']['image_url']
    assert evidence['source_url'].endswith('/japanese/data/550112.json')
    assert len(evidence['snapshot_sha256'])==64
    assert match_existing_artwork([{'provider_id':'OP12-058_p1','name':'Exact card'}],art)==[art['OP12-058_p1']]
    assert match_existing_artwork([{'provider_id':'OP12-058','name':'Other printing'}],art)==[]
    assert match_existing_artwork([{'provider_id':'OP12-058_p2','name':'Exact card'}],art)==[]
    assert punk_pack_artwork(rows,language='English',set_id='550112')[0]=={}


@pytest.mark.parametrize('image',[
 'http://www.onepiece-cardgame.com/images/cardlist/card/OP12-058.png',
 'https://www.onepiece-cardgame.com.evil.test/images/cardlist/card/OP12-058.png',
 'https://evil.test/images/cardlist/card/OP12-058.png',
 'https://user@www.onepiece-cardgame.com/images/cardlist/card/OP12-058.png',
 'https://www.onepiece-cardgame.com:444/images/cardlist/card/OP12-058.png',
 'https://www.onepiece-cardgame.com/images/cardlist/card/../../private.png',
 'https://www.onepiece-cardgame.com/images/cardlist/card/OP12-058.svg',
 'https://en.onepiece-cardgame.com/images/cardlist/card/OP12-058.png', None])
def test_unsafe_or_wrong_language_art_is_not_used(image):
    row=card();row['img_full_url']=image
    assert punk_pack_artwork([row],language='Japanese',set_id='550112')[0]=={}


def test_conflicting_pack_and_duplicate_printing_fail_closed():
    row=card();row['pack_id']='550111'
    with pytest.raises(ValueError):punk_pack_artwork([row],language='Japanese',set_id='550112')
    duplicate=card();duplicate['name']='Another card'
    with pytest.raises(ValueError):punk_pack_artwork([card(),duplicate],language='Japanese',set_id='550112')
    with pytest.raises(ValueError):punk_pack_url('Japanese','../550112')
    with pytest.raises(ValueError):punk_pack_url('Korean','550112')


def test_sync_hydrates_art_from_full_pack_not_lightweight_index():
    async def run():
        feed=ReferenceFeeds()
        async def get(url):
            if url.endswith('cards_by_id.json'):
                return {'OP12-058':{'name':'Exact card','pack_id':'550112'}}
            if url.endswith('packs.json'):return {'550112':{'name':'A pack'}}
            result=card()
            if '/english/' in url:result['img_full_url']=result['img_full_url'].replace('www.','en.')
            return [result]
        feed.get=get
        try:return [entry async for entry in feed.punk()]
        finally:await feed.close()
    entries=asyncio.run(run())
    assert len(entries)==2
    assert entries[0][1][0]['image_url'].startswith('https://en.onepiece-cardgame.com/')
    assert entries[1][1][0]['image_url'].startswith('https://www.onepiece-cardgame.com/')
    assert entries[1][1][0]['evidence']['image_reference']['language']=='Japanese'


def test_parsing_does_not_mutate_provider_evidence():
    payload=[card()];before=deepcopy(payload)
    punk_pack_artwork(payload,language='Japanese',set_id='550112')
    assert payload==before
