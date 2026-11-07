from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app import dragon_ball_market as db
from app.cardmarket_valuations import guide_values
from app.fx import FxQuote

NOW=datetime(2026,10,10,1,tzinfo=timezone.utc)
REF={'provider':'Bandai Official','system_code':db.MASTERS,'language':'English',
     'provider_id':'428013:BT13-029.png','set_id':'428013','name':'A Sudden Escape',
     'card_number':'BT13-029','rarity':'Common[C]','set_name':'UW04 Booster -Supreme Rivalry-'}
PRODUCT={'idProduct':549841,'name':'A Sudden Escape','idExpansion':3796,
         'idCategory':1049,'categoryName':'Dragon Ball Super Singles'}
PACK={'categoryName':'DBS Set','name':'Supreme Rivalry: Common Set','idExpansion':3796}
PRICE={'idProduct':549841,'idCategory':1049,'trend':.04,'trend-foil':.13}
FX=FxQuote('EUR','GBP',Decimal('.84763'),NOW-timedelta(hours=11),NOW,'ECB_EURO_REFERENCE_RATES')


def test_actual_public_export_shape_preserves_normal_and_foil_prices():
    matches=db.matched_products([REF],{'549841':PRODUCT},{'set':PACK})
    assert matches[(db.MASTERS,REF['provider_id'])]['idProduct']==549841
    quotes=db.guide_quotes(REF,PRODUCT,PRICE,NOW-timedelta(hours=1),FX)
    assert [(q['finish'],q['source_field'],q['price_gbp_minor']) for q in quotes]==[
        ('Normal','trend',3),('Holofoil','trend-foil',11)]
    assert all(q['physical_language_confirmed'] is False and not q['condition_specific'] for q in quotes)


@pytest.mark.parametrize('change',range(6))
def test_ambiguous_printings_numbers_regions_and_releases_are_not_guessed(change):
    refs=[deepcopy(REF)];products={'one':deepcopy(PRODUCT)};packaging={'set':deepcopy(PACK)}
    if change==0:refs.append(dict(REF,provider_id='428013:BT13-029_p1.png'))
    if change==1:refs.append(dict(REF,name='Different face',provider_id='428013:BT13-029_back.png'))
    if change==2:products['two']=dict(PRODUCT,idProduct=999)
    if change==3:packaging['other']=dict(PACK,idExpansion=999)
    if change==4:refs[0]['language']='Japanese'
    if change==5:refs[0]['set_name']='UW04 Booster -Another release-'
    assert not db.matched_products(refs,products,packaging)


def test_fusion_world_requires_collector_number_and_excludes_non_english_expansion():
    ref=dict(REF,system_code=db.FUSION,name='Vados',provider_id='583001:FB01-003',
             card_number='FB01-003',set_id='583001',set_name='BOOSTER PACK -AWAKENED PULSE- [FB01]')
    product=dict(PRODUCT,idProduct=756838,name='Vados (FB01-003) [Fusion World]',idExpansion=5552)
    pack=dict(PACK,idCategory=1050,categoryName='Dragon Ball Super Boosters',name='Awakened Pulse Booster [Fusion World]',idExpansion=5552)
    products={'own':product,'jp':dict(product,idProduct=999,idExpansion=5731)}
    packs={'own':pack,'jp':dict(pack,name=pack['name']+' (Non-English)',idExpansion=5731)}
    assert db.matched_products([ref],products,packs)[(db.FUSION,ref['provider_id'])]['idProduct']==756838
    assert not db.matched_products([dict(ref,card_number='FB01-004')],products,packs)


@pytest.mark.parametrize('system',[db.MASTERS,db.FUSION])
@pytest.mark.parametrize('change',['valid','wrong_title','different_game','duplicate_expansion','parallel','different_language'])
def test_starter_catalogue_references_preserve_game_release_and_print(system,change):
    fusion=system==db.FUSION
    ref=dict(REF,system_code=system,name='Vegeta',card_number='FS02-003' if fusion else 'SD13-003',
             set_name='STARTER DECK -VEGETA- [FS02]' if fusion else 'UW01 Starter 13 -Clan Collusion-')
    product=dict(PRODUCT,name='Vegeta (FS02-003) [Fusion World]' if fusion else 'Vegeta')
    pack=dict(PACK,idCategory=1053,categoryName='Dragon Ball Super Starter Decks',
              name='Starter Deck: Vegeta [Fusion World]' if fusion else 'Starter Deck: Clan Collusion')
    packs={'one':pack};refs=[ref]
    if change=='wrong_title':pack['name']='Starter Deck: Other'+(' [Fusion World]' if fusion else '')
    if change=='different_game':pack['name']=pack['name'].replace(' [Fusion World]','') if fusion else pack['name']+' [Fusion World]'
    if change=='duplicate_expansion':packs['other']=dict(pack,idExpansion=5555)
    if change=='parallel':refs.append(dict(ref,provider_id='parallel'))
    if change=='different_language':pack['name']+=' (Non-English)'
    assert bool(db.matched_products(refs,{'one':product},packs))==(change=='valid')
    assert db.release_identity(system,ref['set_name'],include_starters=False) is None


def test_starter_reference_does_not_expand_physical_copy_valuation_scope():
    product,ref=canonical_and_reference()
    product['set_name']='Clan Collusion';ref['reference_set_name']='UW01 Starter 13 -Clan Collusion-'
    for quote in ref['quotes']:quote['reference_identity']['set_name']=ref['reference_set_name']
    assert not guide_values(product,[ref],now=NOW)


def canonical_and_reference():
    product={'product_type':'CARD','game':'Dragon Ball Super','name':REF['name'],
             'set_name':'Supreme Rivalry','card_number':REF['card_number'],
             'variant':'Normal','rarity':'Common','language':'English'}
    ref={k:REF[k] for k in ('provider','system_code','provider_id','set_id')}
    ref.update(reference_language='English',reference_name=REF['name'],reference_set_name=REF['set_name'],
               reference_number=REF['card_number'],reference_rarity=REF['rarity'],
               quotes=db.guide_quotes(REF,PRODUCT,PRICE,NOW-timedelta(hours=1),FX))
    return product,ref


def test_both_physical_finishes_use_v4_without_inventing_sold_observations():
    product,ref=canonical_and_reference()
    normal=guide_values(product,[ref],now=NOW)[0]
    foil=guide_values(dict(product,variant='Foil'),[ref],now=NOW)[0]
    assert normal['result'].market_value_minor==3 and foil['result'].market_value_minor==11
    assert normal['result'].sold_observation_count==0 and normal['result'].confidence<=.60
    assert not normal['result'].auto_publish_eligible
    assert normal['evidence']['quote']['source']=='CARDMARKET_BULK_SINGLES'


@pytest.mark.parametrize('change',[
    {'language':'Japanese'},{'set_name':'Supreme Rivalry Pre-Release Cards'},
    {'name':'A Sudden Escape (Parallel)'},{'card_number':'BT13-028'},
    {'variant':'Reverse Holofoil'},{'rarity':'Super Rare'},
])
def test_physical_guide_rejects_edition_language_name_number_finish_and_rarity(change):
    product,ref=canonical_and_reference()
    assert not guide_values(dict(product,**change),[ref],now=NOW)


@pytest.mark.parametrize('field,value',[
    ('reference_printing_id','other'),('reference_rarity','Uncommon[UC]'),
    ('product_id','0'),('expansion_id',0),('match_basis','GUESSED'),
    ('original_currency','USD'),('price_gbp_minor',999),('original_minor',True),
    ('observed_at',(NOW-timedelta(days=8)).isoformat()),('observed_at',(NOW+timedelta(seconds=1)).isoformat()),
    ('fx_rate_to_gbp','NaN'),('source_field','low'),
])
def test_bad_or_stale_bulk_quote_is_never_applied(field,value):
    product,ref=canonical_and_reference();ref['quotes']=[dict(ref['quotes'][0],**{field:value})]
    assert not guide_values(product,[ref],now=NOW)


def test_reference_changes_and_unpriced_duplicate_still_block_inventory_value():
    product,ref=canonical_and_reference()
    changed=deepcopy(ref);changed['quotes'][0]['reference_identity']['name']='Changed source card'
    assert not guide_values(product,[changed],now=NOW)
    assert not guide_values(product,[ref,dict(ref,provider_id='other-print',quotes=[])],now=NOW)


@pytest.mark.parametrize('prefix',['Series 1','Series 7','Series 9','Z10','UB01'])
@pytest.mark.parametrize('category,category_id,suffix',[
    ('Dragon Ball Super Boosters',1050,'Booster'),
    ('Dragon Ball Super Booster Boxes',1052,'Booster Box'),
])
def test_masters_numbered_releases_use_full_title_from_boosters_and_boxes(prefix,category,category_id,suffix):
    ref=dict(REF,set_name=f'{prefix} Booster -HISTORY OF Z-')
    pack=dict(PACK,idCategory=category_id,categoryName=category,name=f'History of Z {suffix}')
    assert db.matched_products([ref],{'one':PRODUCT},{'one':pack})[(db.MASTERS,ref['provider_id'])]==PRODUCT
    # A matching set-product and box reinforce the same expansion, not a
    # duplicate. A contradictory expansion from either source blocks it.
    same=dict(PACK,name='History of Z: Common Set')
    assert db.matched_products([ref],{'one':PRODUCT},{'one':pack,'same':same})
    assert not db.matched_products([ref],{'one':PRODUCT},{'one':pack,'conflict':dict(same,idExpansion=9999)})


@pytest.mark.parametrize('name',[
    'History of Z Pre-Release Pack','History of Z Release Pack',
    'History of Z Booster [Fusion World]','History of Z Booster (Non-English)',
    'History of Z Booster (Version Française)','History of Z Booster (Asia Region Legal)',
    'History of Z Collector´s Booster','History of Z Booster Box Case',
])
def test_masters_does_not_borrow_release_event_collector_or_regional_packaging(name):
    ref=dict(REF,set_name='Z10 Booster -HISTORY OF Z-')
    pack=dict(PACK,idCategory=1050,categoryName='Dragon Ball Super Boosters',name=name)
    assert not db.matched_products([ref],{'one':PRODUCT},{'one':pack})


@pytest.mark.parametrize('category,category_id',[
    ('Dragon Ball Super Boosters',1052),('Dragon Ball Super Booster Boxes',1050),
    ('Dragon Ball Super Boosters',None),('Other',1050),
])
def test_added_packaging_sources_require_matching_category_ids(category,category_id):
    ref=dict(REF,set_name='Z10 Booster -HISTORY OF Z-')
    suffix='Booster Box' if category.endswith('Boxes') else 'Booster'
    pack=dict(PACK,idCategory=category_id,categoryName=category,name='History of Z '+suffix)
    assert not db.matched_products([ref],{'one':PRODUCT},{'one':pack})


@pytest.mark.parametrize('title,code',[('MANGA BOOSTER','SB'),('STORY BOOSTER','ST')])
@pytest.mark.parametrize('change',['valid','wrong_code','wrong_number','wrong_name','wrong_game','parallel','duplicate_product','unpriced_duplicate'])
def test_fusion_supplemental_release_requires_explicit_game_title_number_and_unique_print(title,code,change):
    ref=dict(REF,system_code=db.FUSION,set_name=f'{title} 01 [{code}01]',
             card_number=f'{code}01-002',name='Android 16')
    product=dict(PRODUCT,name=f'Android 16 ({code}01-002) [Fusion World]')
    pack=dict(PACK,idCategory=1050,categoryName='Dragon Ball Super Boosters',name=f'{title.title()} 01 Booster [Fusion World]')
    refs=[ref];products={'one':product}
    if change=='wrong_code':ref['set_name']=f'{title} 01 [{code}02]'
    if change=='wrong_number':product['name']=f'Android 16 ({code}01-003) [Fusion World]'
    if change=='wrong_name':product['name']=f'Android 17 ({code}01-002) [Fusion World]'
    if change=='wrong_game':pack['name']=pack['name'].replace(' [Fusion World]','')
    if change=='parallel':refs.append(dict(ref,provider_id='another-print'))
    if change in {'duplicate_product','unpriced_duplicate'}:products['other']=dict(product,idProduct=9999)
    assert bool(db.matched_products(refs,products,{'one':pack}))==(change=='valid')
    assert db.release_identity(db.FUSION,ref['set_name'],include_supplemental=False) is None


@pytest.mark.parametrize('title,code',[('MANGA BOOSTER','SB'),('STORY BOOSTER','ST')])
def test_supplemental_reference_guides_do_not_expand_physical_valuation(title,code):
    product,ref=canonical_and_reference()
    product.update(game='Dragon Ball Super Fusion World',set_name=title+' 01')
    ref.update(system_code=db.FUSION,reference_set_name=f'{title} 01 [{code}01]')
    for quote in ref['quotes']:quote['reference_identity']['set_name']=ref['reference_set_name']
    assert not guide_values(product,[ref],now=NOW)


@pytest.mark.parametrize('suffix',[' (BT13-029)',' (029)',' - BT13-029'])
def test_repeated_matching_collector_number_does_not_hide_an_exact_guide(suffix):
    product,ref=canonical_and_reference();product['name']+=suffix
    assert guide_values(product,[ref],now=NOW)[0]['result'].market_value_minor==3
    assert not guide_values(product,[ref,dict(ref,provider_id='different-print',quotes=[])],now=NOW)


@pytest.mark.parametrize('suffix',[' (028)',' (BT13-028)',' - BT13-028',' (Alternate Art)',
                                   ' (029 Parallel)',' (BT13-029_p1)',' (029) (Pre-Release)'])
def test_title_normalization_never_discards_printing_or_conflicting_number(suffix):
    product,ref=canonical_and_reference();product['name']+=suffix
    assert not guide_values(product,[ref],now=NOW)


def test_intrinsically_foil_rarity_with_imported_normal_finish_requires_review():
    product,ref=canonical_and_reference();product['rarity']='Super Rare';ref['reference_rarity']='Super Rare[SR]'
    for quote in ref['quotes']:quote['reference_rarity']='Super Rare[SR]'
    assert not guide_values(product,[ref],now=NOW)


def test_one_piece_base_rarity_does_not_give_a_foil_price_to_normal_or_parallel():
    product,ref=canonical_and_reference()
    product.update(game='One Piece',name='Alpha',set_name="Adventure on Kami's Island",
                   card_number='EB04-042',variant='Normal',rarity='C')
    ref.update(provider='Bandai Official',system_code='ONE_PIECE_CARD_GAME',provider_id='EB04-042',set_id='569115',
               reference_name='Alpha',reference_number='EB04-042',reference_rarity='C',
               reference_set_name='BOOSTER PACK -ADVENTURE ON KAMI’S ISLAND- [OP15-EB04]')
    quote=ref['quotes'][0]
    quote.update(finish='Printing guide',reference_printing_id='EB04-042',reference_rarity='C',
        reference_identity={'name':ref['reference_name'],'set_id':ref['set_id'],
            'card_number':ref['reference_number'],'set_name':ref['reference_set_name']},
        match_basis='UNIQUE_RELEASE_NAME_NUMBER_IN_BOTH_CHECKLISTS')
    ref['quotes']=[quote]
    assert guide_values(product,[ref],now=NOW)[0]['result'].market_value_minor==3
    assert not guide_values(dict(product,variant='Foil'),[ref],now=NOW)
    assert not guide_values(product,[dict(ref,provider_id='EB04-042_p1')],now=NOW)


@pytest.mark.asyncio
async def test_refresh_handles_outage_without_erasing_existing_quotes(monkeypatch):
    writes=[]
    async def download(client,path,**kwargs):
        if 'nonsingles' in path:return {'set':PACK},NOW
        if 'singles' in path:return {'549841':PRODUCT},NOW
        return {'549841':PRICE},NOW
    class Connection:
        async def fetch(self,sql):return [REF]
        async def executemany(self,sql,values):
            assert 'inventory_items' not in sql
            writes.extend(values)
    @asynccontextmanager
    async def connection(*args):yield Connection()
    class Rates:
        async def quote(self,**kwargs):return FX
    monkeypatch.setattr(db,'download',download);monkeypatch.setattr(db,'user_connection',connection)
    result=await db.refresh_dragon_ball_prices(object(),uuid4(),Rates())
    assert result=={'checked':1,'matched':1,'priced':1,'provider_failures':0}
    assert writes[0][5:7]==(3,11)
    writes.clear()
    async def failure(*args,**kwargs):raise ValueError('Provider failed')
    monkeypatch.setattr(db,'download',failure)
    assert (await db.refresh_dragon_ball_prices(object(),uuid4(),Rates()))['provider_failures']==1
    assert not writes
