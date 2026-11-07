"""Offline safety and free-tier contract tests; no live key or priced inventory."""
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app import pokewallet_one_piece_market as market
from app.fx import FxQuote


NOW = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)


def jp(**fields):
    row = dict(provider='Punk Records',system_code='ONE_PIECE_CARD_GAME',language='Japanese',
        provider_id='OP01-001',card_number='OP01-001',name='ロロノア・ゾロ',
        set_id='jp-set-1',set_name='ブースターパック ROMANCE DAWN【OP-01】',rarity='Leader',
        has_detail_value=False,existing_catalogue_value=0,existing_source=None,
        existing_pricing_updated_at=None)
    row.update(fields)
    return row


def en(**fields):
    row = dict(provider='Bandai Official',system_code='ONE_PIECE_CARD_GAME',language='English',
        provider_id='OP01-001',card_number='OP01-001',name='Roronoa Zoro',
        set_id='en-set-1',set_name='BOOSTER PACK -ROMANCE DAWN- [OP-01]',rarity='L',
        has_detail_value=False,existing_catalogue_value=0,existing_source=None,
        existing_pricing_updated_at=None)
    row.update(fields)
    return row


def card(**fields):
    row = dict(id='op_abcdef',card_number='OP01-001',name='Roronoa Zoro',
        rarity='L',sub_type_name='Normal',
        cardmarket={'product_url':'https://www.cardmarket.com/en/OnePiece/Products/Singles/Romance-Dawn/Roronoa-Zoro',
            'prices':{'trend':12.34}})
    row.update(fields)
    return row


def japanese_cardmarket_card(*, printed='OP01-001', version=1, ordinal='1.0', **fields):
    label=f' (V.{version})' if version is not None else ''
    suffix=f'-V{version}' if version is not None else ''
    row=card(card_number=ordinal,rarity='Leader',sub_type_name=None,
        cardmarket={'product_name':f'Roronoa Zoro ({printed}){label}',
            'product_url':f'https://www.cardmarket.com/en/OnePiece/Products/Singles/Romance-Dawn-Japanese/Roronoa-Zoro-{printed}{suffix}',
            'prices':{'trend':12.34}})
    row.update(fields)
    return row


def numbered_english_base(**fields):
    row = card(name='Roronoa Zoro (001)', cardmarket={
        'product_name': 'Roronoa Zoro (OP01-001)',
        'product_url': 'https://www.cardmarket.com/en/OnePiece/Products/Singles/Romance-Dawn/Roronoa-Zoro-OP01-001',
        'prices': {'trend': 12.34},
    })
    row.update(fields)
    return row


def test_printed_number_title_matches_only_the_independently_identified_base():
    base = numbered_english_base()
    groups = market.collect_reference_groups([en()], NOW)
    alternate = card(id='op_alt', name='Roronoa Zoro (Alternate Art)', sub_type_name='Alternate Art')
    assert market.matches_for_complete_set(groups, 'English', 'OP01', [base, alternate]) == [(en(), base)]
    assert market.matches_for_complete_set(groups, 'English', 'OP01', [alternate, base]) == [(en(), base)]
    assert market.matches_for_complete_set(groups, 'English', 'OP01', [base, card(id='op_unknown', sub_type_name=None)]) == []
    assert market.matches_for_complete_set(groups, 'English', 'OP01', [base, numbered_english_base(id='op_other_normal')]) == []


@pytest.mark.parametrize('name', [
    'Roronoa Zoro (002)', 'Roronoa Zoro (1)', 'Roronoa Zoro (0001)',
    'Roronoa Zoro (001) (Alternate Art)', 'Roronoa Zoro (Alternate Art) (001)',
    'Roronoa Zoro (OP02-001)', 'Different Character (001)',
])
def test_printed_number_title_never_discards_conflicting_identity(name):
    assert not market.english_base_name_matches(en(), numbered_english_base(name=name))


@pytest.mark.parametrize('fields', [
    {'sub_type_name': 'Foil'}, {'sub_type_name': None}, {'card_number': 'OP02-001'},
    {'cardmarket': None},
])
def test_printed_number_title_requires_explicit_base_metadata(fields):
    assert not market.english_base_name_matches(en(), numbered_english_base(**fields))


@pytest.mark.parametrize('title', [
    '', 'Roronoa Zoro', 'Roronoa Zoro (OP02-001)', 'Roronoa Zoro (OP01-002)',
    'Different Character (OP01-001)', 'Roronoa Zoro (OP01-001) (V.2)',
])
def test_printed_number_title_requires_agreeing_cardmarket_title(title):
    source = numbered_english_base()
    source['cardmarket']['product_name'] = title
    assert not market.english_base_name_matches(en(), source)


@pytest.mark.parametrize('replacement', [
    'https://invalid.example/en/OnePiece/Products/Singles/Romance-Dawn/Roronoa-Zoro-OP01-001',
    'https://www.cardmarket.com/en/OnePiece/Products/Singles/Romance-Dawn/Roronoa-Zoro-OP01-002',
    'https://www.cardmarket.com/en/OnePiece/Products/Singles/Romance-Dawn/Roronoa-Zoro-OP01-001-V2',
    'https://www.cardmarket.com/en/OnePiece/Products/Singles/Romance-Dawn-Japanese/Roronoa-Zoro-OP01-001',
    'https://www.cardmarket.com/en/OnePiece/Products/Singles/Romance-Dawn-Non-English/Roronoa-Zoro-OP01-001',
    'https://www.cardmarket.com/en/OnePiece/Products/Singles/Romance-Dawn/Roronoa-Zoro-OP01-001?variant=2',
    'https://www.cardmarket.com/en/OnePiece/Products/Singles/Romance-Dawn/Roronoa-Zoro-OP01-001-V1',
    'https://[invalid',
])
def test_printed_number_title_requires_agreeing_cardmarket_url(replacement):
    source = numbered_english_base()
    source['cardmarket']['product_url'] = replacement
    assert not market.english_base_name_matches(en(), source)


def test_printed_number_title_does_not_match_japanese_or_parallel_reference():
    source = numbered_english_base()
    assert not market.english_base_name_matches(en(language='Japanese'), source)
    assert not market.english_base_name_matches(en(provider_id='OP01-001_p1'), source)
    quote = market.catalogue_guide(en(), source, '3188', FxQuote('EUR', 'GBP', Decimal('.86'), NOW, NOW, 'ECB_EURO_REFERENCE_RATES'), NOW)
    assert quote['physical_valuation_eligible'] is False
    assert quote['sold_comparable'] is False


def test_printed_number_title_requires_consistent_explicit_base_version():
    source = numbered_english_base()
    source['cardmarket']['product_name'] += ' (V.1)'
    assert not market.english_base_name_matches(en(), source)
    source['cardmarket']['product_url'] += '-V1'
    assert market.english_base_name_matches(en(), source)


def test_japanese_ordinals_require_printing_in_cardmarket_title_and_url():
    base=japanese_cardmarket_card()
    assert market.japanese_cardmarket_printing(base,'OP01')==('OP01-001',1)
    matches=market.matches_for_complete_set(
        market.collect_reference_groups([jp()],NOW),'Japanese','OP01',[base])
    assert matches==[(jp(),base)]
    assert market.japanese_cardmarket_printing(
        japanese_cardmarket_card(printed='OP02-001'),'OP01') is None
    assert market.japanese_cardmarket_printing(
        japanese_cardmarket_card(cardmarket=base['cardmarket'] |
            {'product_url':base['cardmarket']['product_url'].replace('Romance-Dawn-Japanese','Romance-Dawn')}),'OP01') is None
    assert market.japanese_cardmarket_printing(
        japanese_cardmarket_card(cardmarket=base['cardmarket'] |
            {'product_name':'Roronoa Zoro (OP01-002) (V.1)'}),'OP01') is None
    assert market.japanese_cardmarket_printing(
        japanese_cardmarket_card(cardmarket=base['cardmarket'] |
            {'product_url':base['cardmarket']['product_url'].replace('-V1','-V2')}),'OP01') is None
    assert market.japanese_cardmarket_printing(
        japanese_cardmarket_card(cardmarket=base['cardmarket'] |
            {'product_url':'https://not-cardmarket.example/en/OnePiece/Products/Singles/Romance-Dawn-Japanese/Roronoa-Zoro-OP01-001-V1'}),'OP01') is None


def test_non_english_cardmarket_release_requires_exact_jp_printing_evidence():
    """Real PokéWallet JP rows use `Non-English`; they stay mixed guides only."""
    base=japanese_cardmarket_card(rarity=None)
    base['cardmarket']['product_url']=base['cardmarket']['product_url'].replace(
        'Romance-Dawn-Japanese','Romance-Dawn-Non-English')
    assert market.japanese_cardmarket_printing(base,'OP01')==('OP01-001',1)
    assert market.matches_for_complete_set(
        market.collect_reference_groups([jp()],NOW),'Japanese','OP01',[base])==[(jp(),base)]
    altered=base['cardmarket'].copy()
    altered['product_url']=altered['product_url'].replace('OP01-001','OP01-002')
    assert market.japanese_cardmarket_printing(japanese_cardmarket_card(cardmarket=altered),'OP01') is None
    altered=base['cardmarket'].copy()
    altered['product_url']=altered['product_url'].replace('Non-English','English')
    assert market.japanese_cardmarket_printing(japanese_cardmarket_card(cardmarket=altered),'OP01') is None
    fx=FxQuote('EUR','GBP',Decimal('.86'),NOW,NOW,'ECB_EURO_REFERENCE_RATES')
    quote=market.catalogue_guide(jp(),base,'-88',fx,NOW)
    assert quote['valuation_role']=='MIXED_NON_ENGLISH_REFERENCE'
    assert quote['physical_language_confirmed'] is False
    assert quote['physical_valuation_eligible'] is False


def test_japanese_cardmarket_italian_locale_and_unreported_rarity_are_not_false_mismatches():
    base=japanese_cardmarket_card(rarity=None)
    base['cardmarket']['product_url']=base['cardmarket']['product_url'].replace(
        '/en/OnePiece/', '/it/OnePiece/')
    assert market.japanese_cardmarket_printing(base,'OP01')==('OP01-001',1)
    groups=market.collect_reference_groups([jp()],NOW)
    counts={}
    assert market.matches_for_complete_set(groups,'Japanese','OP01',[base],counts)==[(jp(),base)]
    assert counts['matching_rarities']==1
    assert market.matches_for_complete_set(groups,'Japanese','OP01',[
        japanese_cardmarket_card(rarity='SR',cardmarket=base['cardmarket'])])==[]
    assert market.matches_for_complete_set(groups,'Japanese','OP01',[
        japanese_cardmarket_card(cardmarket=base['cardmarket'] | {
            'product_url':base['cardmarket']['product_url'].replace('/it/', '/ja/')})])==[]
    fx=FxQuote('EUR','GBP',Decimal('.86'),NOW,NOW,'ECB_EURO_REFERENCE_RATES')
    quote=market.catalogue_guide(jp(),base,'-88',fx,NOW)
    assert quote['source_rarity_confirmed'] is False
    assert quote['physical_valuation_eligible'] is False
    assert 'RARITY' not in quote['match_basis']


def test_japanese_v1_disambiguates_explicit_parallel_but_not_unknown():
    groups=market.collect_reference_groups([jp()],NOW)
    base=japanese_cardmarket_card()
    v2=japanese_cardmarket_card(version=2,id='op_other')
    counts={}
    assert market.matches_for_complete_set(groups,'Japanese','OP01',[base,v2],counts)==[(jp(),base)]
    assert counts['japanese_v1_disambiguated']==1
    assert market.matches_for_complete_set(groups,'Japanese','OP01',[v2])==[]
    assert market.matches_for_complete_set(groups,'Japanese','OP01',[
        base,japanese_cardmarket_card(version=None,id='op_unversioned')])==[]
    assert market.matches_for_complete_set(groups,'Japanese','OP01',[
        base,japanese_cardmarket_card(id='op_duplicate_v1')])==[]


def lists():
    return {
        'Japanese':{'success':True,'data':[{'set_code':'OP01','group_id':'-88','language':'jp'}]},
        'English':{'success':True,'data':[]},
    }


def set_response(*products, total=None, language='jp', group_id='-88', page=1):
    return {'success':True,'set':{'set_code':'OP01','group_id':group_id,'language':language},
            'page':page,'limit':200,'total':len(products) if total is None else total,
            'data':list(products)}


class FakeHttpResponse:
    def __init__(self,body=None,status=200,headers=None):
        self.body=body or {}
        self.status_code=status
        self.headers=headers or {}
        self.content=json.dumps(self.body).encode()

    def json(self):
        return self.body


class FakeHttp:
    def __init__(self, first=None, second=None, *, status=200, page2=None):
        self.first=first or set_response(card())
        self.second=second or lists()
        self.status=status
        self.page2=page2
        self.calls=[]

    async def get(self,url,params=None,headers=None):
        assert url.startswith(market.BASE_URL)
        assert headers['X-API-Key']=='pk_live_secret_fixture'
        self.calls.append((url,params))
        if self.status != 200:
            return FakeHttpResponse(status=self.status)
        if url.endswith('/op/sets'):
            return FakeHttpResponse(self.second['Japanese' if params['language']=='jp' else 'English'])
        if params['page'] == 2 and self.page2 is not None:
            return FakeHttpResponse(self.page2)
        return FakeHttpResponse(self.first)


def test_only_exact_release_base_ids_are_eligible():
    assert market.code_from_reference(jp())=='OP01'
    assert market.code_from_reference(en())=='OP01'
    assert market.code_from_reference(jp(provider_id='OP01-001_p1')) is None
    assert market.code_from_reference(jp(set_name='プロモーションカード')) is None
    assert market.code_from_reference(jp(set_name='ブースターパック ROMANCE DAWN【OP-02】')) is None
    assert market.code_from_reference(en(set_name='UNKNOWN [OP-01]')) is None
    assert market.code_from_reference(en(card_number='OP01-002')) is None


def test_cross_source_ambiguities_fail_closed():
    references=[en(),en(provider='Punk Records',set_id='other',
        set_name='BOOSTER PACK -OTHER PRINTING- [OP-01]')]
    assert not market.collect_reference_groups(references,NOW)
    references=[en(),en(provider='Punk Records',set_id='other',rarity='SR')]
    assert not market.collect_reference_groups(references,NOW)
    assert not market.unique_source_sets({'English':{'success':True,'data':[
        {'set_code':'OP01','group_id':'1','language':'en'},
        {'set_code':'OP01','group_id':'2','language':'en'},
    ]}})


def test_japanese_locale_suffix_maps_to_the_same_numbered_release_only_in_japanese():
    assert market.source_release_code('OP-01-JP','Japanese')=='OP01'
    assert market.source_release_code('EB-02-JP','Japanese')=='EB02'
    assert market.source_release_code('OP-01-JP','English') is None
    assert market.source_release_code('OP-01-JP-SPECIAL','Japanese') is None
    sources=market.unique_source_sets({'Japanese':{'success':True,'data':[
        {'set_code':'OP-01-JP','group_id':'-88','language':'jp'}]},
        'English':{'success':True,'data':[]}})
    assert sources[('Japanese','OP01')]['group_id']=='-88'
    total,products=market.unique_market_products(
        set_response(card(),group_id='-88') | {
            'set':{'set_code':'OP-01-JP','group_id':'-88','language':'jp'}},
        'Japanese','-88','OP01')
    assert total==1 and len(products)==1
    assert market.matches_for_complete_set(market.collect_reference_groups([jp()],NOW),
        'Japanese','OP01',products)


def test_source_list_quality_reveals_ambiguous_release_groups_without_guessing():
    report=market.source_list_diagnostics({'Japanese':{'success':True,'data':[
        {'set_code':'OP01','group_id':'-1','language':'jp'},
        {'set_code':'OP01','group_id':'-2','language':'jp'},
    ]}},market.collect_reference_groups([jp()],NOW))
    assert report['Japanese']['multiple_group_ids']==1
    assert report['Japanese']['ambiguous_code_sample']==['OP01']


def test_alternate_printing_collisions_block_price_assignment():
    groups=market.collect_reference_groups([en()],NOW)
    assert len(market.matches_for_complete_set(groups,'English','OP01',[card()]))==1
    # Later-page variants are still in the complete source set.
    assert not market.matches_for_complete_set(groups,'English','OP01',[
        card(),card(id='op_alternate',cardmarket={'product_url':'https://www.cardmarket.com/en/OnePiece/Products/Singles/Other','prices':{'trend':999.99}})])
    assert not market.matches_for_complete_set(groups,'English','OP01',[card(name='Different Person')])
    assert not market.matches_for_complete_set(groups,'English','OP01',[card(rarity='SEC')])
    assert not market.matches_for_complete_set(groups,'English','OP01',[card(sub_type_name='Alternate Art')])


def test_single_explicit_normal_can_be_separated_from_labelled_parallel_art():
    groups=market.collect_reference_groups([en()],NOW)
    base=card()
    alt=card(id='op_different_print',sub_type_name='Alternate Art',
        cardmarket={'product_url':'https://www.cardmarket.com/en/OnePiece/Products/Singles/Other',
                    'prices':{'trend':1999.99}})
    counts={}
    assert market.matches_for_complete_set(groups,'English','OP01',[base,alt],counts)==[(en(),base)]
    assert counts['parallel_number_collisions']==1 and counts['base_art_disambiguated']==1
    assert not market.matches_for_complete_set(groups,'English','OP01',[
        base,card(id='op_unlabelled',sub_type_name='Unknown Special')])
    assert not market.matches_for_complete_set(groups,'English','OP01',[
        base,card(id='op_second_normal')])


def test_only_cardmarket_trend_yields_nonphysical_eur_guide():
    fx=FxQuote('EUR','GBP',Decimal('.86'),NOW,NOW,'ECB_EURO_REFERENCE_RATES')
    q=market.catalogue_guide(jp(),card(),'-88',fx,NOW)
    assert q['price_gbp_minor']==1061
    assert q['original_minor']==1234
    assert q['source']==market.SOURCE
    assert q['reference_language']=='Japanese'
    assert q['physical_valuation_eligible'] is False and q['sold_comparable'] is False
    assert q['reference_identity']['name']=='ロロノア・ゾロ'
    for c in (card(cardmarket=None),card(cardmarket={'prices':{'trend':12.34}}),
              card(cardmarket={'product_url':'https://www.tcgplayer.com/cards/1','prices':{'trend':12.34}}),
              card(cardmarket={'product_url':'https://www.cardmarket.com/en/OnePiece/Products/Singles/X','prices':{'low':1.00}})):
        assert market.catalogue_guide(jp(),c,'-88',fx,NOW) is None


def test_existing_price_from_another_adapter_is_immutable():
    assert not market.quote_eligible(jp(has_detail_value=True),NOW)
    assert not market.quote_eligible(jp(existing_catalogue_value=500,existing_source='CARDMARKET_CATALOGUE'),NOW)
    assert not market.quote_eligible(jp(existing_catalogue_value=500,existing_source=market.SOURCE,
        existing_pricing_updated_at=NOW),NOW)
    assert market.quote_eligible(jp(existing_catalogue_value=500,existing_source=market.SOURCE,
        existing_pricing_updated_at=NOW-timedelta(days=2)),NOW)
    assert 'inventory_items' not in market.WRITE_SQL.lower()
    assert 'shopify' not in market.WRITE_SQL.lower()
    assert 'reference_catalogue_prices' in market.WRITE_SQL
    assert "quotes->0->>'source'=$16" in market.WRITE_SQL


def test_client_refuses_all_paid_endpoints_before_network():
    client=market.FreePokewalletOnePieceClient('pk_live_secret_fixture',request_limit=3,client=FakeHttp())
    async def check():
        with pytest.raises(market.ProviderResponseError,match='PAID_OR_UNRECOGNISED_ENDPOINT'):
            await client.get('/op/prices?set_code=OP01')
        with pytest.raises(market.ProviderResponseError,match='PAID_OR_UNRECOGNISED_ENDPOINT'):
            await client.get('/dbs/prices/BT01')
        assert client.requests==0
    import asyncio
    asyncio.run(check())


@pytest.mark.asyncio
@pytest.mark.parametrize('dry_run,expected_writes',[(True,0),(False,1)])
async def test_bounded_importer_dry_run_then_atomic_guide_only(monkeypatch,dry_run,expected_writes):
    writes=[]
    @asynccontextmanager
    async def connection(*args):
        class Conn:
            async def fetch(self,sql):
                assert sql==market.READ_SQL
                return [jp()]
            async def executemany(self,sql,rows):
                assert sql==market.WRITE_SQL
                writes.extend(rows)
        yield Conn()
    monkeypatch.setattr(market,'user_connection',connection)
    class FX:
        async def quote(self,**kwargs):
            assert kwargs['base_currency']=='EUR' and kwargs['quote_currency']=='GBP'
            return FxQuote('EUR','GBP',Decimal('.86'),NOW,NOW,'ECB_EURO_REFERENCE_RATES')
    http=FakeHttp()
    result=await market.refresh_pokewallet_one_piece(object(),uuid4(),FX(),'pk_live_secret_fixture',
        dry_run=dry_run,request_limit=10,http_client=http)
    assert result['provider_failures']==0
    assert result['requests']==3 and result['set_pages']==1
    assert result['matching_printings']==1 and result['eligible_quotes']==1
    assert result['writes_attempted']==expected_writes and len(writes)==expected_writes
    if writes:
        row=writes[0]
        assert row[0:4]==('Punk Records','ONE_PIECE_CARD_GAME','Japanese','OP01-001')
        assert row[5]==row[6]==1061
        assert row[4][0]['reference_identity']['set_id']=='jp-set-1'


@pytest.mark.asyncio
async def test_429_pauses_without_losing_existing_prices(monkeypatch):
    @asynccontextmanager
    async def connection(*args):
        class Conn:
            async def fetch(self,*args):return [jp()]
            async def executemany(self,*args):raise AssertionError('Rate-limit must not write')
        yield Conn()
    monkeypatch.setattr(market,'user_connection',connection)
    result=await market.refresh_pokewallet_one_piece(object(),uuid4(),object(),
        'pk_live_secret_fixture',dry_run=False,http_client=FakeHttp(status=429))
    assert result['reason']=='RATE_LIMITED'
    assert result['provider_failures']==1 and result['writes_attempted']==0
    assert result['requests']==1


@pytest.mark.asyncio
async def test_ecb_outage_reports_bounded_failure_without_writing(monkeypatch):
    @asynccontextmanager
    async def connection(*args):
        class Conn:
            async def fetch(self,*args):return [jp()]
            async def executemany(self,*args):raise AssertionError('No stale FX conversion')
        yield Conn()
    monkeypatch.setattr(market,'user_connection',connection)
    class OfflineFX:
        async def quote(self,**kwargs):
            raise RuntimeError('ECB FX request failed')
    result=await market.refresh_pokewallet_one_piece(object(),uuid4(),OfflineFX(),
        'pk_live_secret_fixture',dry_run=False,http_client=FakeHttp())
    assert result['provider_failures']==1 and result['writes_attempted']==0
    assert result['reason']=='RuntimeError' and result['requests']==3


@pytest.mark.asyncio
async def test_incomplete_provider_set_is_quarantined_then_next_set_is_used(monkeypatch):
    next_ref=jp(provider_id='OP02-001',card_number='OP02-001',name='エドワード・ニューゲート',
        set_id='jp-set-2',set_name='ブースターパック 頂上決戦【OP-02】')
    writes=[]
    @asynccontextmanager
    async def connection(*args):
        class Conn:
            async def fetch(self,*args):return [jp(),next_ref]
            async def executemany(self,sql,rows):writes.extend(rows)
        yield Conn()
    monkeypatch.setattr(market,'user_connection',connection)
    class TwoSetHttp:
        async def get(self,url,params=None,headers=None):
            if url.endswith('/op/sets'):
                data=[{'set_code':'OP01','group_id':'-88','language':'jp'},
                      {'set_code':'OP02','group_id':'-89','language':'jp'}]
                return FakeHttpResponse({'success':True,'data':data if params['language']=='jp' else []})
            if url.endswith('/-88'):
                return FakeHttpResponse(set_response(card(),total=2))
            if url.endswith('/-89'):
                next_card=card(id='op_second',card_number='OP02-001',
                    cardmarket={'product_url':'https://www.cardmarket.com/en/OnePiece/Products/Singles/Paramount-War/Edward-Newgate',
                                'prices':{'trend':2.50}})
                return FakeHttpResponse(set_response(next_card,group_id='-89',language='jp') | {
                    'set':{'set_code':'OP02','group_id':'-89','language':'jp'}})
            raise AssertionError('Unexpected endpoint')
    class FX:
        async def quote(self,**kwargs):
            return FxQuote('EUR','GBP',Decimal('.86'),NOW,NOW,'ECB_EURO_REFERENCE_RATES')
    result=await market.refresh_pokewallet_one_piece(object(),uuid4(),FX(),
        'pk_live_secret_fixture',dry_run=False,request_limit=10,http_client=TwoSetHttp())
    assert result['skipped_invalid_sets']==1 and result['provider_failures']==1
    assert result['invalid_set_samples'][0]['reason']=='INCOMPLETE_OR_DUPLICATE_SET'
    assert result['eligible_quotes']==1 and result['writes_attempted']==1
    assert result['cursor']=='Japanese:-89' and result['requests']==4
    assert len(writes)==1 and writes[0][3]=='OP02-001'


@pytest.mark.asyncio
@pytest.mark.parametrize('conflicting,expected_writes',[(False,1),(True,0)])
async def test_duplicate_provider_ids_only_collapse_identical_rows(monkeypatch,conflicting,expected_writes):
    writes=[]
    @asynccontextmanager
    async def connection(*args):
        class Conn:
            async def fetch(self,*args):return [jp()]
            async def executemany(self,sql,rows):writes.extend(rows)
        yield Conn()
    monkeypatch.setattr(market,'user_connection',connection)
    first=card()
    duplicate=card(name='Other Artist') if conflicting else dict(first)
    http=FakeHttp(first=set_response(first,duplicate,total=2))
    class FX:
        async def quote(self,**kwargs):
            return FxQuote('EUR','GBP',Decimal('.86'),NOW,NOW,'ECB_EURO_REFERENCE_RATES')
    result=await market.refresh_pokewallet_one_piece(object(),uuid4(),FX(),
        'pk_live_secret_fixture',dry_run=False,http_client=http)
    assert result['writes_attempted']==expected_writes
    assert len(writes)==expected_writes
    assert result['collapsed_identical_duplicate_rows']==(0 if conflicting else 1)
    assert result['skipped_invalid_sets']==int(conflicting)

def op16(**fields):
    row=en(provider_id="OP16-032",card_number="OP16-032",name="Boa Hancock",
           set_id="569116",set_name="The Time of Battle [OP-16]",rarity="SR")
    row.update(fields)
    return row


def test_reviewed_prefixless_release_requires_exact_official_identity():
    assert market.code_from_reference(op16())=="OP16"
    for ref in (op16(provider="Punk Records"),op16(set_id="other"),
                op16(set_name="Other Printing [OP-16]"),
                op16(provider_id="OP16-032_p1"),op16(card_number="OP15-032"),
                op16(language="Japanese")):
        assert market.code_from_reference(ref) is None
    assert market.code_from_reference(en(set_name="Other [OP-01]")) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run,expected_writes",[(True,0),(False,1)])
async def test_op16_scope_never_fetches_or_writes_other_releases(monkeypatch,dry_run,expected_writes):
    writes=[]
    @asynccontextmanager
    async def connection(*args):
        class Conn:
            async def fetch(self,sql):return [en(),op16()]
            async def executemany(self,sql,rows):writes.extend(rows)
        yield Conn()
    monkeypatch.setattr(market,"user_connection",connection)
    product=card(id="op_boa",card_number="OP16-032",name="Boa Hancock",rarity="SR")
    payload=set_response(product,language="en",group_id="16") | {
        "set":{"set_code":"OP16","group_id":"16","language":"en"}}
    http=FakeHttp(first=payload,second={
        "Japanese":{"success":True,"data":[]},
        "English":{"success":True,"data":[
            {"set_code":"OP01","group_id":"1","language":"en"},
            {"set_code":"OP16","group_id":"16","language":"en"}]}})
    class FX:
        async def quote(self,**kwargs):
            return FxQuote("EUR","GBP",Decimal(".86"),NOW,NOW,"ECB_EURO_REFERENCE_RATES")
    run_id=str(uuid4())
    result=await market.refresh_pokewallet_one_piece(object(),uuid4(),FX(),"pk_live_secret_fixture",
        dry_run=dry_run,request_limit=60,http_client=http,reference_set_id="569116",
        operator_run_id=run_id)
    assert result["requests"]==3 and result["target_groups"]==1
    assert result["preview"][0]["provider_id"]=="OP16-032"
    assert result["preview"][0]["physical_valuation_eligible"] is False
    assert result["writes_attempted"]==expected_writes and len(writes)==expected_writes
    assert all(row[3]=="OP16-032" for row in writes)
    assert all(row[4][0]["operator_run_id"]==run_id for row in writes)
    assert not any(url.endswith("/1") for url,_ in http.calls)


@pytest.mark.asyncio
async def test_unknown_operator_scope_rejected_before_any_database_call():
    with pytest.raises(ValueError,match="UNREVIEWED_REFERENCE_SET"):
        await market.refresh_pokewallet_one_piece(None,uuid4(),None,"fixture",
            reference_set_id="other")


def test_op16_scope_does_not_resolve_conflicting_catalogue_printings():
    competing=op16(set_id="other",set_name="BOOSTER PACK -OTHER PRINTING- [OP-16]")
    assert not market.collect_reference_groups([op16(),competing],NOW)
    assert not market.quote_eligible(op16(has_detail_value=True),NOW)
    assert not market.quote_eligible(op16(existing_catalogue_value=500,existing_source="OTHER"),NOW)


@pytest.mark.asyncio
@pytest.mark.parametrize("scope,run_id",[(None,str(uuid4())),("569116","not-a-uuid")])
async def test_operator_attribution_requires_exact_scope_and_uuid(scope,run_id):
    with pytest.raises(ValueError):
        await market.refresh_pokewallet_one_piece(None,uuid4(),None,"fixture",
            reference_set_id=scope,operator_run_id=run_id)
