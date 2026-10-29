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


def published_base_and_parallel():
    base = reference()
    base.update(provider_id='EB04-007', rarity='SR', evidence={
        'printing_id':'EB04-007','detail_level':'OFFICIAL_CHECKLIST'})
    parallel = {**base,'provider_id':'EB04-007_p1',
                'evidence':{'printing_id':'EB04-007_p1','detail_level':'OFFICIAL_CHECKLIST'}}
    return base, parallel


def test_publisher_confirmed_base_recovers_only_unambiguous_marketplace_sku():
    singles, packaging = fixtures()
    base, parallel = published_base_and_parallel()
    matches = market.matched_products([base,parallel],singles,packaging)
    assert set(matches)=={'EB04-007'}
    assert matches['EB04-007']['idProduct']==904150
    # The other provider can corroborate the same published identities, but
    # never permit an uncorroborated variant to borrow the base price.
    punk_base = {**base,'provider':'Punk Records','evidence':{'printing_id':'EB04-007'}}
    punk_parallel = {**parallel,'provider':'Punk Records',
                     'evidence':{'printing_id':'EB04-007_p1'}}
    assert set(market.matched_products([base,parallel,punk_base,punk_parallel],singles,packaging))=={
        'EB04-007'}


@pytest.mark.parametrize('change', [
    'missing_official_evidence','unverified_parallel','different_name','different_rarity',
    'different_finish','unknown_parallel_suffix','starter_release','ambiguous_marketplace',
])
def test_official_base_exception_rejects_unproven_and_ambiguous_printings(change):
    singles, packaging = fixtures()
    base, parallel = published_base_and_parallel()
    refs = [base,parallel]
    if change=='missing_official_evidence':
        parallel['evidence']={'printing_id':'EB04-007_p1','detail_level':'PROVIDER_INDEX'}
    elif change=='unverified_parallel':
        refs.append({**parallel,'provider':'Punk Records','provider_id':'EB04-007_p2',
                     'evidence':{'printing_id':'EB04-007_p2'}})
    elif change=='different_name':
        parallel['name']='Different Character'
    elif change=='different_rarity':
        parallel['rarity']='SEC'
    elif change=='different_finish':
        parallel['finish']='Holofoil'
    elif change=='unknown_parallel_suffix':
        parallel['provider_id']='EB04-007_PR'
        parallel['evidence']['printing_id']='EB04-007_PR'
    elif change=='starter_release':
        for ref in refs:ref['set_name']='STARTER DECK -The Three Captains- [ST-10]'
    elif change=='ambiguous_marketplace':
        singles['duplicate']={**singles['904150'],'idProduct':904999}
    assert not market.matched_products(refs,singles,packaging)


@pytest.mark.asyncio
async def test_published_base_guide_remains_reference_only_and_does_not_price_parallel(monkeypatch):
    singles, packaging = fixtures()
    base, parallel = published_base_and_parallel()
    now=datetime.now(timezone.utc);writes=[]
    async def download(client,path,**kwargs):
        if 'nonsingles' in path:return packaging,now
        if 'singles' in path:return singles,now
        return {'904150':{'idProduct':904150,'idCategory':1621,'trend':'3.00'}},now
    class Connection:
        async def fetch(self,sql):return [base,parallel]
        async def executemany(self,sql,values):writes.extend(values)
    @asynccontextmanager
    async def connection(*args):yield Connection()
    class FX:
        async def quote(self,**kwargs):return FxQuote('EUR','GBP',Decimal('.86'),now,now,
                                                     'ECB_EURO_REFERENCE_RATES')
    monkeypatch.setattr(market,'download',download)
    monkeypatch.setattr(market,'user_connection',connection)
    report=await market.refresh_one_piece_prices(object(),uuid4(),FX())
    assert report['official_base_groups_matched']==1
    assert report['official_base_priced']==1
    assert report['priced']==1
    by_id={row[3]:row for row in writes}
    assert by_id['EB04-007'][5]==258
    quote=by_id['EB04-007'][4][0]
    assert quote['match_basis']==market.OFFICIAL_BASE_PARALLEL_BASIS
    assert quote['physical_valuation_eligible'] is False
    assert quote['reference_printing_id']=='EB04-007'
    assert by_id['EB04-007_p1'][4]==[]
    assert by_id['EB04-007_p1'][5] is None
    # A mixed-language Cardmarket reference guide is not an exact physical
    # valuation: the downstream inventory fallback must reject this basis.
    from app.cardmarket_valuations import guide_values
    product=dict(product_type='CARD',game='One Piece',language='English',
                 name='Roronoa Zoro',set_name="The World's Strongest Warriors",
                 card_number='EB04-007',variant='Holofoil',rarity='SR')
    matched_ref=dict(provider='Bandai Official',system_code='ONE_PIECE_CARD_GAME',
                     provider_id='EB04-007',reference_language='English',
                     reference_name='Roronoa Zoro',reference_number='EB04-007',
                     reference_set_name=base['set_name'],reference_rarity='SR',
                     set_id=base['set_id'],quotes=[quote])
    assert guide_values(product,[matched_ref],now=now)==[]


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


@pytest.mark.parametrize('reference_name,market_name', [
    ('Yosaku &amp; Johnny', 'Yosaku & Johnny'),
    ('Chaka &amp; Pell', 'Chaka & Pell'),
    ('Law &#38; Bepo', 'Law & Bepo'),
])
def test_html_entities_are_decoded_only_for_unique_exact_printing_matches(reference_name,market_name):
    ref={**reference(),'provider_id':'OP03-053','card_number':'OP03-053',
         'name':reference_name,'set_id':'real-set',
         'set_name':'BOOSTER PACK -PILLARS OF STRENGTH- [OP-03]'}
    product={'idProduct':720003,'name':f'{market_name} (OP03-053)',
             'idCategory':1621,'categoryName':'One Piece Single','idExpansion':5533}
    pack={'idCategory':1623,'categoryName':'One Piece Lots',
          'name':'Common Set - Pillars of Strength (OP03)','idExpansion':5533}
    assert market.matched_products([ref],{'one':product},{'one':pack})['OP03-053']==product
    assert ref['name']==reference_name  # original identity is never rewritten
    assert not market.matched_products([ref],{
        'one':product,'parallel':{**product,'idProduct':720004}}, {'one':pack})
    assert not market.matched_products([ref],{'one':product},{
        'one':{**pack,'idExpansion':5534}})
    assert not market.matched_products([ref],{
        'one':{**product,'name':'Different & Character (OP03-053)'}},{'one':pack})
    assert not market.matched_products([ref],{
        'one':{**product,'name':f'{market_name} (OP03-054)'}},{'one':pack})


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


def test_eb03_heroines_release_recovers_exact_english_matches_only():
    """Real Cardmarket source has English expansion 6449 and Asia expansion 6379."""
    ref = dict(provider='Punk Records', system_code='ONE_PIECE_CARD_GAME',
               language='English', provider_id='EB03-002', card_number='EB03-002',
               name='Ain', set_id='569203',
               set_name='EXTRA BOOSTER -ONE PIECE HEROINES EDITION- [EB-03]')
    english = {'idProduct': 871954, 'name': 'Ain (EB03-002)',
               'idCategory': 1621, 'categoryName': 'One Piece Single',
               'idExpansion': 6449}
    asia = {**english, 'idProduct': 990001, 'idExpansion': 6379}
    english_lot = {'name': 'Common Set - Heroines Edition (EB03)',
                   'categoryName': 'One Piece Lots', 'idExpansion': 6449}
    asia_pack = {'name': 'Heroines Edition Booster (Asia Region Legal)',
                 'categoryName': 'One Piece Booster', 'idExpansion': 6379}

    assert market.release_identity(ref['set_name']) == ('heroinesedition', 'EB03')
    assert market.release_identity('EXTRA BOOSTER -ONE PIECE HEROINES EDITION- [EB-02]') == (
        'onepieceheroinesedition', 'EB02'
    )
    result = market.matched_products([ref], {'english': english, 'asia': asia},
                                     {'english-lot': english_lot, 'asia-boost': asia_pack})
    assert result['EB03-002']['idProduct'] == 871954

    # Price existence, a regional product, or a shared collector number never
    # resolves conflicting exact artworks or a duplicated variant.
    assert not market.matched_products([ref], {'asia': asia}, {'english-lot': english_lot})
    assert not market.matched_products([ref], {
        'english': english, 'another-english': {**english, 'idProduct': 871955},
    }, {'english-lot': english_lot})
    assert not market.matched_products([ref, {**ref, 'provider_id': 'EB03-002_p1'}],
                                       {'english': english}, {'english-lot': english_lot})

    for change in ({'language': 'Japanese'}, {'card_number': 'EB03-003'},
                   {'name': 'Ain (Parallel)'}, {'set_name': 'EXTRA BOOSTER -OTHER- [EB-03]'},
                   {'provider': 'Unknown Provider'}):
        assert not market.matched_products([{**ref, **change}],
                                           {'english': english}, {'english-lot': english_lot})


@pytest.mark.asyncio
async def test_eb03_refresh_writes_only_verified_global_reference_guides(monkeypatch):
    ref = dict(provider='Punk Records', system_code='ONE_PIECE_CARD_GAME',
               language='English', provider_id='EB03-002', card_number='EB03-002',
               name='Ain', set_id='569203',
               set_name='EXTRA BOOSTER -ONE PIECE HEROINES EDITION- [EB-03]',
               rarity='Uncommon')
    single = {'idProduct': 871954, 'name': 'Ain (EB03-002)',
              'idCategory': 1621, 'categoryName': 'One Piece Single',
              'idExpansion': 6449}
    pack = {'name': 'Common Set - Heroines Edition (EB03)',
            'categoryName': 'One Piece Lots', 'idExpansion': 6449}
    now = datetime.now(timezone.utc)
    written = []

    async def download(client, path, **kwargs):
        if 'nonsingles' in path:
            return {'lot': pack}, now
        if 'singles' in path:
            return {'single': single}, now
        return {'871954': {'idProduct': 871954, 'idCategory': 1621, 'trend': '0.85'}}, now

    class Connection:
        async def fetch(self, sql):
            return [ref]
        async def executemany(self, sql, values):
            assert 'reference_market_prices' in sql
            assert 'inventory_items' not in sql and 'shopify' not in sql.lower()
            written.extend(values)
    @asynccontextmanager
    async def connection(*args):
        yield Connection()
    class FX:
        async def quote(self, **kwargs):
            return FxQuote('EUR','GBP',Decimal('.86'), now, now, 'ECB_EURO_REFERENCE_RATES')

    monkeypatch.setattr(market, 'download', download)
    monkeypatch.setattr(market, 'user_connection', connection)
    result = await market.refresh_one_piece_prices(object(), uuid4(), FX())
    assert result['provider_failures'] == 0
    assert result['checked'] == result['matched'] == result['priced'] == 1
    assert len(written) == 1
    assert written[0][5] == 73  # EUR 0.85 converted to GBP, rounded in pennies
    quote = written[0][4][0]
    assert quote['reference_printing_id'] == 'EB03-002'
    assert quote['expansion_id'] == 6449
    assert quote['valuation_role'] == 'MIXED_LANGUAGE_REFERENCE'
    assert quote['physical_language_confirmed'] is False
    assert quote['condition_specific'] is False
