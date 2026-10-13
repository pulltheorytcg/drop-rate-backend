"""Japanese One Piece market data must never inherit an English-priced printing.

This is a published *Non-English regional* Cardmarket guide. It is not an
exact Japanese-language sold comparison and cannot reprice physical stock.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from random import Random
from uuid import uuid4
from copy import deepcopy

import pytest

from app import one_piece_market as english
from app.one_piece_japanese_market import (
    JP_MATCH_BASIS, japanese_release_code,
    matched_japanese_products, japanese_nonenglish_quote,
)
from app.fx import FxQuote

NOW = datetime(2026,10,13,9,30,tzinfo=timezone.utc)


def references():
    en = {
        'provider':'Punk Records','system_code':'ONE_PIECE_CARD_GAME',
        'language':'English','provider_id':'OP01-001','card_number':'OP01-001',
        'set_id':'569101','set_name':'BOOSTER PACK -ROMANCE DAWN- [OP-01]',
        'name':'Roronoa Zoro','rarity':'Leader'
    }
    jp = {
        **en,'language':'Japanese','set_id':'550101',
        'set_name':'ブースターパック ROMANCE DAWN【OP-01】',
        'name':'ロロノア・ゾロ'
    }
    return en,jp


def marketplace():
    en_p = {'idProduct': 1001,'name':'Roronoa Zoro (OP01-001)',
            'idCategory':1621,'categoryName':'One Piece Single','idExpansion':5229}
    jp_p = {**en_p,'idProduct':768234,'idExpansion':5484}
    other = {**jp_p,'idProduct':9991,'idExpansion':9911}
    return {'en':en_p,'jp':jp_p,'other':other}, {
        'jp_pack':{'idProduct':693904,'name':'Romance Dawn Booster (Non-English)',
                   'idCategory':1622,'categoryName':'One Piece Booster','idExpansion':5484},
        'en_pack':{'idProduct':911340,'name':'Common Set - Romance Dawn (OP01)',
                    'categoryName':'One Piece Lots','idExpansion':5229},
    }


def fx():
    return FxQuote('EUR','GBP',Decimal('.85'), NOW,NOW,'ECB_EURO_REFERENCE_RATES')


def test_official_printing_and_marketplace_region_are_proven_independently():
    en,jp=references()
    products,packaging=marketplace()
    found=matched_japanese_products([en,jp],products,packaging)
    assert found['OP01-001']['product']['idProduct']==768234
    assert found['OP01-001']['english_provider_id']=='OP01-001'
    assert found['OP01-001']['english_set_id']=='569101'
    assert found['OP01-001']['region_marker']=='Non-English'
    q=japanese_nonenglish_quote(jp,found['OP01-001'],
         {'idProduct':768234,'idCategory':1621,'trend': '1.00'},NOW,fx())
    assert q['price_gbp_minor']==85
    assert q['source']=='CARDMARKET_BULK_SINGLES'
    assert q['match_basis']==JP_MATCH_BASIS
    assert q['valuation_role']=='MIXED_NON_ENGLISH_REFERENCE'
    assert q['reference_language']=='Japanese'
    assert not q['physical_language_confirmed']
    assert not q['condition_specific']
    assert not q['physical_valuation_eligible']
    assert q['reference_identity']['name']=='ロロノア・ゾロ'
    assert q['english_checklist_set_id']=='569101'
    assert q['marketplace_region_label']=='Non-English'


@pytest.mark.parametrize('mutation',[
    'Japanese is parallel','Japanese is reprint','Different set','Different printed number',
    'Wrong JP title','Different Japanese rarity','Wrong English rarity',
    'Wrong English release','Second English printing','Wrong marketplace language',
    'Wrong market product number','Two marketplace variants',
    'Two market expansion identifiers','English region only','No official English',
])
def test_unsafe_japanese_market_alias_is_not_priced(mutation):
    en,jp=references()
    singles,packaging=marketplace()
    refs=[en,jp]
    if mutation=='Japanese is parallel': jp['provider_id']='OP01-001_p2'
    if mutation=='Japanese is reprint':jp['set_name']='プレミアムブースター ONE PIECE CARD THE BEST【PRB-01】'
    if mutation=='Different set':jp['set_name']='ブースターパック PARAMOUNT WAR【OP-02】'
    if mutation=='Different printed number':jp['card_number']='OP01-999';jp['provider_id']='OP01-999'
    if mutation=='Wrong JP title':jp['set_name']='One Piece Promos【OP-01】'
    if mutation=='Different Japanese rarity':jp['rarity']='Rare'
    if mutation=='Wrong English rarity':en['rarity']='Rare'
    if mutation=='Wrong English release':en['set_name']='BOOSTER PACK -OTHER- [OP-01]'
    if mutation=='Second English printing':refs.append({**en,'set_id':'OTHER'})
    if mutation=='Wrong marketplace language':packaging['jp_pack']['name']='Romance Dawn Booster (English)'
    if mutation=='Wrong market product number':singles['jp']['name']='Roronoa Zoro (OP01-002)'
    if mutation=='Two marketplace variants':singles['jp2']={**singles['jp'],'idProduct':768236}
    if mutation=='Two market expansion identifiers':
        packaging['second']={**packaging['jp_pack'],'idExpansion':12345}
    if mutation=='English region only':del packaging['jp_pack']
    if mutation=='No official English':refs.remove(en)
    assert not matched_japanese_products(refs,singles,packaging), mutation


def test_malformed_and_zero_marketplace_quotes_cannot_claim_priced_state():
    en,jp=references()
    single,pack=marketplace()
    mapping=matched_japanese_products([en,jp],single,pack)['OP01-001']
    for row in (None,{}, {'idProduct':768234,'idCategory':1621,'trend':None},
                {'idProduct':768234,'idCategory':1621,'trend':0},
                {'idProduct':768234,'idCategory':1621,'trend':-2},
                {'idProduct':768234,'idCategory':1621,'trend':'oops'},
                {'idProduct':768235,'idCategory':1621,'trend':10},
                {'idProduct':768234,'idCategory':9999,'trend':10}):
        assert japanese_nonenglish_quote(jp,mapping,row,NOW,fx()) is None


@pytest.mark.asyncio
async def test_existing_daily_job_stores_safe_japanese_public_references_only(monkeypatch):
    en,jp=references()
    products,packaging=marketplace()
    writes=[]
    async def download(client,path,**kwargs):
        if 'nonsingles' in path:return packaging,NOW
        if 'singles' in path:return products,NOW
        return {'768234':{'idProduct':768234,'idCategory':1621,'trend': '1.00'}},NOW
    class Connection:
        async def fetch(self,sql):
            assert "r.language='Japanese'" in sql and "r.language='English'" in sql
            return [en,jp]
        async def executemany(self,sql,rows):
            assert "reference_market_prices" in sql
            assert "update tcg.inventory_items" not in sql and "shopify" not in sql
            writes.extend(rows)
    @asynccontextmanager
    async def connection(*args):
        yield Connection()
    class FX:
        async def quote(self,**kwargs):return fx()
    monkeypatch.setattr(english,'download',download)
    monkeypatch.setattr(english,'user_connection',connection)
    report=await english.refresh_one_piece_prices(object(),uuid4(),FX())
    assert report['japanese_checked']==report['japanese_matched']==report['japanese_priced']==1
    assert report['provider_failures']==0
    assert writes[1][2]=='Japanese' and writes[1][5]==85
    assert writes[1][4][0]['physical_valuation_eligible'] is False
    assert writes[0][2]=='English' and writes[0][5] is None
    assert report['priced']==1


def test_japanese_matcher_1024_random_collisions_never_guesses():
    rng=Random(94716)
    en,jp=references()
    products,packaging=marketplace()
    stable=deepcopy((en,jp,products,packaging))
    for seed in range(1024):
        refs=[dict(en),dict(jp)]
        p=deepcopy(products);packs=deepcopy(packaging)
        if seed&1:
            refs.append({**jp,'provider_id':'OP01-001_p2'})
        if seed&2:
            p['duplicate']={**p['jp'],'idProduct':rng.randint(10000,90000)}
        if seed&4:
            packs['other-expansion']={**packs['jp_pack'],'idExpansion':rng.randint(10000,90000)}
        if seed&8:
            refs[0]['rarity']='Special'
        result=matched_japanese_products(refs,p,packs)
        # A separate parallel sibling doesn't make the verified base print
        # itself ambiguous, but a duplicate market product or release does.
        assert ('OP01-001' in result)==(not(seed&2 or seed&4 or seed&8))
    assert (en,jp,products,packaging)==stable
