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


def op15_sources():
    """Live-shaped official English abbreviations and JP full rarity labels."""
    en={
        'provider':'Bandai Official','system_code':'ONE_PIECE_CARD_GAME',
        'language':'English','provider_id':'OP15-079','card_number':'OP15-079',
        'set_id':'569115','set_name':'BOOSTER PACK -ADVENTURE ON KAMI’S ISLAND- [OP15-EB04]',
        'name':'Absalom','rarity':'C'
    }
    jp={
        **en,'provider':'Punk Records','language':'Japanese','set_id':'550115',
        'set_name':'ブースターパック 神の島の冒険【OP-15】',
        'name':'アブサロム','rarity':'Common'
    }
    product={
        'idProduct':875000,'name':'Absalom (OP15-079)','idCategory':1621,
        'categoryName':'One Piece Single','idExpansion':6504
    }
    pack={
        'idProduct':860000,'name':"Adventure on Kami's Island Booster (Asia Region Legal)",
        'idCategory':1622,'categoryName':'One Piece Booster','idExpansion':6504
    }
    return en,jp,{'single':product},{'region':pack}


def test_bandai_english_base_and_japanese_base_recover_only_region_guide():
    en,jp,singles,packs=op15_sources()
    match=matched_japanese_products([en,jp],singles,packs)['OP15-079']
    assert match['english_checklist_provider']=='Bandai Official'
    assert match['english_provider_id']=='OP15-079'
    assert match['region_marker']=='Asia Region Legal'
    quote=japanese_nonenglish_quote(jp,match,{
        'idProduct':875000,'idCategory':1621,'trend':'1.00'
    },NOW,fx())
    assert quote['price_gbp_minor']==85
    assert quote['english_checklist_provider']=='Bandai Official'
    assert quote['valuation_role']=='MIXED_NON_ENGLISH_REFERENCE'
    assert quote['physical_valuation_eligible'] is False
    assert quote['physical_language_confirmed'] is False
    assert quote['condition_specific'] is False


@pytest.mark.parametrize('mutation',[
    'Unknown English rarity','Wrong English rarity','Wrong Japanese rarity',
    'English parallel','Japanese parallel','Wrong release code',
    'Wrong English release title','Wrong Japanese release title',
    'Marketplace duplicate','Marketplace English-only','Conflicting regional expansions',
    'Second English counterpart','Wrong English provider',
])
def test_bandai_english_bridge_fails_closed_on_unknown_identity(mutation):
    en,jp,singles,packs=op15_sources()
    refs=[en,jp]
    if mutation=='Unknown English rarity':en['rarity']='ALT'
    if mutation=='Wrong English rarity':en['rarity']='R'
    if mutation=='Wrong Japanese rarity':jp['rarity']='Rare'
    if mutation=='English parallel':en['provider_id']='OP15-079_p1'
    if mutation=='Japanese parallel':jp['provider_id']='OP15-079_p1'
    if mutation=='Wrong release code':en['card_number']=en['provider_id']='OP14-079'
    if mutation=='Wrong English release title':en['set_name']='BOOSTER PACK -UNRELATED- [OP15-EB04]'
    if mutation=='Wrong Japanese release title':jp['set_name']='ブースターパック WRONG【OP-15】'
    if mutation=='Marketplace duplicate':
        singles['second']={**singles['single'],'idProduct':875001}
    if mutation=='Marketplace English-only':packs['region']['name']="Adventure on Kami's Island Booster"
    if mutation=='Conflicting regional expansions':
        packs['second']={**packs['region'],'idProduct':860001,'idExpansion':9999}
    if mutation=='Second English counterpart':refs.append({**en,'provider':'Punk Records'})
    if mutation=='Wrong English provider':en['provider']='Unknown Provider'
    assert not matched_japanese_products(refs,singles,packs), mutation


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



@pytest.mark.asyncio
async def test_unmatched_japanese_starter_never_inherits_same_id_english_quote(monkeypatch):
    """The real incident: 454 JP prices came from matching English source ids.

    ST05-004 is common to both publisher language checklists. The Japanese
    booster-only match rules reject the starter, so English market prices must
    be excluded even though the numeric provider_id collides.
    """
    en = {
        'provider':'Punk Records','system_code':'ONE_PIECE_CARD_GAME',
        'language':'English','provider_id':'ST05-004','card_number':'ST05-004',
        'set_id':'569005','set_name':'STARTER DECK -ONE PIECE FILM edition- [ST-05]',
        'name':'Uta','rarity':'SuperRare'
    }
    jp = {
        **en,'language':'Japanese','set_id':'550005',
        'set_name':'スタートデッキ ONE PIECE FILM edition【ST-05】',
        'name':'ウタ'
    }
    product = {'idProduct':123,'name':'Uta (ST05-004)',
               'idCategory':1621,'categoryName':'One Piece Single','idExpansion':5255}
    pack = {'name':'Starter Deck: ONE PIECE FILM edition',
            'idCategory':1625,'categoryName':'One Piece Preconstructed Decks',
            'idExpansion':5255}
    writes=[]
    async def download(client,path,**kwargs):
        if 'nonsingles' in path: return {'pack':pack},NOW
        if 'singles' in path: return {'one':product},NOW
        return {'123':{'idProduct':123,'idCategory':1621,'trend':'2.00'}},NOW
    class Connection:
        async def fetch(self,query):
            return [en,jp]
        async def executemany(self,query,rows):
            writes.extend(rows)
    @asynccontextmanager
    async def connection(*args):
        yield Connection()
    class FX:
        async def quote(self,**kwargs): return fx()
    monkeypatch.setattr(english,'download',download)
    monkeypatch.setattr(english,'user_connection',connection)
    report=await english.refresh_one_piece_prices(object(),uuid4(),FX())
    assert report['matched']==1  # English identity only
    assert report['japanese_matched']==0
    assert report['japanese_priced']==0
    assert report['english_priced']==1
    assert writes[0][2]=='English'
    assert writes[0][5]==170
    assert writes[1][2]=='Japanese'
    assert writes[1][5] is None and writes[1][4]==[]


@pytest.mark.asyncio
async def test_japanese_wrong_release_never_inherits_matching_english_product(monkeypatch):
    en,jp=references()
    products,packaging=marketplace()
    # Same provider id would match English, but this JP printing's official
    # release marker is invalid for the targeted non-English expansion.
    jp['set_name']='ブースターパック WRONG EDITION【OP-02】'
    writes=[]
    async def download(client,path,**kwargs):
        if 'nonsingles' in path:return packaging,NOW
        if 'singles' in path:return products,NOW
        return {'1001':{'idProduct':1001,'idCategory':1621,'trend':'3.00'},
                '768234':{'idProduct':768234,'idCategory':1621,'trend':'8.00'}},NOW
    class Connection:
        async def fetch(self,sql):return [en,jp]
        async def executemany(self,sql,values):writes.extend(values)
    @asynccontextmanager
    async def connection(*args):yield Connection()
    class FX:
        async def quote(self,**kwargs):return fx()
    monkeypatch.setattr(english,'download',download)
    monkeypatch.setattr(english,'user_connection',connection)
    result=await english.refresh_one_piece_prices(object(),uuid4(),FX())
    assert result['japanese_priced']==0
    assert writes[0][2]=='English' and writes[0][5]==255
    assert writes[1][2]=='Japanese' and writes[1][5] is None
