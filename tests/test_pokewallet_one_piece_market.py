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


def test_alternate_printing_collisions_block_price_assignment():
    groups=market.collect_reference_groups([en()],NOW)
    assert len(market.matches_for_complete_set(groups,'English','OP01',[card()]))==1
    # Later-page variants are still in the complete source set.
    assert not market.matches_for_complete_set(groups,'English','OP01',[
        card(),card(id='op_alternate',cardmarket={'product_url':'https://www.cardmarket.com/en/OnePiece/Products/Singles/Other','prices':{'trend':999.99}})])
    assert not market.matches_for_complete_set(groups,'English','OP01',[card(name='Different Person')])
    assert not market.matches_for_complete_set(groups,'English','OP01',[card(rarity='SEC')])
    assert not market.matches_for_complete_set(groups,'English','OP01',[card(sub_type_name='Alternate Art')])


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
