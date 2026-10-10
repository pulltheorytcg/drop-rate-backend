from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime,timezone
from decimal import Decimal
from random import Random
from uuid import uuid4

import pytest

from app import one_piece_market as market
from app.fx import FxQuote


def reference(**changes):
    return dict(provider='Bandai Official',system_code='ONE_PIECE_CARD_GAME',language='English',
        provider_id='EB04-007_p2',name='Roronoa Zoro',card_number='EB04-007',
        set_id='569117',set_name='BOOSTER PACK -THE WORLD’S STRONGEST WARRIORS- [OP-17]',**changes)


def fixtures():
    singles={'904150':{'idProduct':904150,'name':'Roronoa Zoro (EB04-007)',
        'idCategory':1621,'categoryName':'One Piece Single','idExpansion':6492},
        '904797':{'idProduct':904797,'name':'Roronoa Zoro (EB04-007)',
        'idCategory':1621,'categoryName':'One Piece Single','idExpansion':6723}}
    packaging={'911340':{'idProduct':911340,'name':"Common Set - The World's Strongest Warriors (OP17)",
        'categoryName':'One Piece Lots','idExpansion':6492}}
    return singles,packaging


def test_recorded_zoro_special_print_does_not_inherit_asia_region_price():
    singles,packaging=fixtures()
    result=market.matched_products([reference()],singles,packaging)
    assert result['EB04-007_p2']['idProduct']==904150
    assert market.release_identity('BOOSTER PACK -ADVENTURE ON KAMI’S ISLAND- [OP15-EB04]')==('adventureonkamis island'.replace(' ',''),'OP15')
    for field,value in [('provider','Unknown Provider'),('language','Japanese'),('system_code','POKEMON_TCG'),('set_name','Other [OP-17]'),('card_number','EB04-008')]:
        ref=reference();ref[field]=value
        assert not market.matched_products([ref],singles,packaging)


def test_older_checklists_and_known_release_title_spelling_are_supported():
    singles,packaging=fixtures();ref={**reference(),'provider':'Punk Records'}
    assert market.matched_products([ref],singles,packaging)[ref['provider_id']]['idProduct']==904150
    assert market.release_identity('BOOSTER PACK -500 YEARS IN THE FUTURE- [OP-07]')==('500yearsintothefuture','OP07')
    assert market.release_identity('EXTRA BOOSTER -MEMORIAL COLLECTION- [EB-01]')==('memorialcollection','EB01')
    # The same provider ID must not inherit whichever conflicting set was last.
    other={**ref,'provider':'Bandai Official','set_id':'different','set_name':'Other [OP-17]'}
    packaging['other']={'categoryName':'One Piece Lots','name':'Common Set - Other (OP17)','idExpansion':1234}
    singles['other']={**singles['904150'],'idProduct':123,'idExpansion':1234}
    assert not market.matched_products([ref,other],singles,packaging)


@pytest.mark.parametrize('change',['valid','japanese','prerelease','different_title','duplicate_expansion','parallel','wrong_number'])
def test_starter_deck_requires_exact_full_release_and_unique_print(change):
    ref={**reference(),'provider_id':'ST05-008','card_number':'ST05-008','name':'Shiki',
         'set_name':'STARTER DECK -ONE PIECE FILM edition- [ST-05]'}
    product={'idProduct':1,'name':'Shiki (ST05-008)','idCategory':1621,'categoryName':'One Piece Single','idExpansion':5255}
    pack={'idCategory':1625,'categoryName':'One Piece Preconstructed Decks','name':'Starter Deck: ONE PIECE FILM edition','idExpansion':5255}
    packs={'one':pack};refs=[ref]
    if change=='japanese':pack['name']+=' (Japanese)'
    if change=='prerelease':pack['name']='Super PreRelease '+pack['name']
    if change=='different_title':pack['name']='Starter Deck: Straw Hat Crew'
    if change=='duplicate_expansion':packs['other']={**pack,'idExpansion':5555}
    if change=='parallel':refs.append({**ref,'provider_id':'ST05-008_p1'})
    if change=='wrong_number':product['name']='Shiki (ST05-009)'
    assert bool(market.matched_products(refs,{'one':product},packs))==(change=='valid')
    assert market.release_identity(ref['set_name'],include_starters=False) is None


@pytest.mark.parametrize('seed',range(2048))
def test_price_matching_collision_matrix(seed):
    """Different numbers, releases, regions and parallel collisions; no HTTP or stock writes."""
    rng=Random(seed);number=f'{rng.choice(["OP","EB","ST","PRB"])}{rng.randrange(1,20):02}-{rng.randrange(1000):03}'
    release=f'OP{rng.randrange(1,50):02}';expansion=rng.randrange(1000,9000)
    ref={**reference(),'provider_id':number+'_p2','card_number':number,'set_id':str(expansion),
        'name':'Character '+str(seed),'set_name':f'BOOSTER PACK -Release {seed}- [{release[:2]}-{release[2:]}]'}
    product={'idProduct':seed+1,'name':f'Character {seed} ({number})','idCategory':1621,
        'categoryName':'One Piece Single','idExpansion':expansion}
    products={'target':product,'other-region':{**product,'idProduct':seed+10001,'idExpansion':expansion+10000}}
    packaging={'set':{'categoryName':'One Piece Lots','name':f'Common Set - Release {seed} ({release})','idExpansion':expansion}}
    refs=[ref]
    # The same number in another release is harmless; two prints within this
    # exact release or two conflicting expansion identities must block a quote.
    refs.append({**ref,'provider_id':number+'_r9','set_id':'another-set','set_name':'Another ['+release+']'})
    if seed & 1:refs.append({**ref,'provider_id':number+'_p3'})
    if seed & 2:products['parallel']={**product,'idProduct':seed+20001}
    if seed & 4:packaging['conflict']={**packaging['set'],'idExpansion':expansion+20000}
    if seed & 8:products['target']={**product,'name':f'Other Character ({number})'}
    before=deepcopy((refs,products,packaging))
    matched=market.matched_products(refs,products,packaging)
    assert (ref['provider_id'] in matched)==(seed & 15==0)
    assert (refs,products,packaging)==before


@pytest.mark.asyncio
async def test_refresh_normalizes_guide_and_never_writes_inventory(monkeypatch):
    singles,packaging=fixtures();now=datetime.now(timezone.utc);writes=[]
    async def download(client,path,**kwargs):
        if 'nonsingles' in path:return packaging,now
        if 'singles' in path:return singles,now
        return {'904150':{'idProduct':904150,'idCategory':1621,'trend':'326.80'},
                '904797':{'idProduct':904797,'idCategory':1621,'trend':'186.43'}},now
    class Connection:
        async def fetch(self,sql):return [reference()]
        async def executemany(self,sql,values):
            assert 'inventory' not in sql and 'catalogue_products' not in sql
            assert 'r.name=$11' in sql and 's.name=$14' in sql
            writes.extend(values)
    @asynccontextmanager
    async def connection(*args):yield Connection()
    class FX:
        async def quote(self,**kwargs):return FxQuote('EUR','GBP',Decimal('.86'),now,now,'ECB_EURO_REFERENCE_RATES')
    monkeypatch.setattr(market,'download',download);monkeypatch.setattr(market,'user_connection',connection)
    report=await market.refresh_one_piece_prices(object(),uuid4(),FX())
    assert report=={'checked':1,'matched':1,'priced':1,'provider_failures':0}
    quote=writes[0][4][0]
    assert quote['product_id']=='904150' and quote['price_gbp_minor']==28105
    assert quote['condition_specific'] is False and quote['physical_language_confirmed'] is False
    assert quote['reference_identity']['card_number']=='EB04-007'
    writes.clear()
    async def failure(*args,**kwargs):raise ValueError('Stale guide')
    monkeypatch.setattr(market,'download',failure)
    report=await market.refresh_one_piece_prices(object(),uuid4(),FX())
    assert report['provider_failures']==1 and not writes
