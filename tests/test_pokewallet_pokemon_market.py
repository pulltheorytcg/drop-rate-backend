"""Offline free-tier contract and exact Japanese-printing safety tests."""
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app import pokewallet_pokemon_market as pokemon
from app.fx import FxQuote

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)


def reference(**fields):
    row = dict(provider='TCGdex', system_code='POKEMON_TCG', language='Japanese',
        provider_id='SV11B-001', set_id='SV11B', card_number='001/086',
        name='ピカチュウ', set_name='ブラックボルト', rarity='Common',
        has_detail_value=False, existing_catalogue_value=0, existing_source=None,
        existing_pricing_updated_at=None)
    row.update(fields)
    return row


def card(**fields):
    row = dict(id='pk_'+'a'*64,
        card_info={'card_number':'1/86', 'set_code':'23599', 'set_id':'23599',
                   'product_type':'card', 'name':'Pikachu - 001/086'},
        cardmarket={'product_name':'Pikachu',
            'product_url':'https://www.cardmarket.com/en/Pokemon/Products/Singles/Black-Bolt/Pikachu-SV11B1',
            'prices':[{'variant_type':'normal','trend':1.25,
                       'updated_at':'2026-10-24T10:00:00Z'}]},
        tcgplayer=None)
    row.update(fields)
    return row


def sets():
    return {'success':True,'data':[{'set_code':'SV11B','set_id':'23599',
        'language':'jap','name':'SV11B Black Bolt','card_count':1}]}


def search_page(*items, total=None, page=1):
    return {'query':'SV11B','results':list(items),
        'pagination':{'total':len(items) if total is None else total,
                      'page':page,'total_pages':1}}


def fx():
    return FxQuote('EUR','GBP',Decimal('.80'),NOW,NOW,'ECB_EURO_REFERENCE_RATES')


def test_reference_identity_requires_exact_japanese_set_and_collector_fraction():
    assert pokemon.reference_code(reference())=='sv11b'
    assert pokemon.collector_fraction('001/086')==(1,86)
    assert pokemon.collector_fraction('1/86')==(1,86)
    assert pokemon.collector_fraction('001') is None
    assert pokemon.collector_fraction('1.0/86') is None
    assert pokemon.reference_code(reference(language='English')) is None
    assert pokemon.reference_code(reference(provider_id='SV11B-002')) is None
    assert pokemon.reference_code(reference(card_number='001')) is None
    assert pokemon.reference_code(reference(set_id='UNKNOWN [SV11B]')) is None
    assert pokemon.reference_code(reference(provider_id='SV11B-001_p2')) is None


def test_only_unique_unpriced_canonical_numbers_are_eligible():
    # A source price older than the coverage freshness window is not a
    # present-day value: the SQL reader treats it as eligible for a new guide.
    assert "p.pricing_updated_at>=now()-interval '7 days'" in pokemon.READ_SQL
    refs=[reference(),reference(provider_id='SV11B-001')]
    assert not pokemon.reference_groups(refs)
    assert not pokemon.reference_groups([reference(has_detail_value=True)])
    assert not pokemon.reference_groups([reference(existing_catalogue_value=50)])
    assert pokemon.reference_groups([reference()])


def test_japanese_set_code_must_be_unique_across_provider_listing():
    assert pokemon.unique_japanese_sets(sets())['sv11b']['set_id']=='23599'
    body=sets() | {'data':sets()['data']+[{'set_code':'sv11b','set_id':'23600','language':'jap'}]}
    assert not pokemon.unique_japanese_sets(body)
    assert not pokemon.unique_japanese_sets(sets() | {'data':[
        {'set_code':'SV11B','set_id':'23599','language':'eng'}]})
    with pytest.raises(pokemon.ProviderResponseError):
        pokemon.unique_japanese_sets({'data':[]})


def test_own_source_refreshes_without_overwriting_other_adapters_or_dates():
    old = reference(existing_catalogue_value=50, existing_source=pokemon.SOURCE,
                    existing_pricing_updated_at=NOW-timedelta(days=8))
    before = dict(old)
    assert list(pokemon.reference_groups([old], NOW).values()) == [old]
    assert old == before
    assert not pokemon.reference_groups([old | {"has_detail_value": True}], NOW)
    assert not pokemon.reference_groups([old | {"existing_source": "OTHER_ADAPTER"}], NOW)
    assert not pokemon.reference_groups([old | {"existing_pricing_updated_at": NOW}], NOW)
    assert not pokemon.reference_groups([old | {"existing_pricing_updated_at": None}], NOW)
    assert not pokemon.reference_groups([old | {"existing_pricing_updated_at": NOW.replace(tzinfo=None)}], NOW)
    assert not pokemon.reference_groups([old, old | {"existing_catalogue_value": 0}], NOW)


@pytest.mark.parametrize("set_id", ["-4", "-188", "-9999999999", "1", "23599"])
def test_documented_negative_cardmarket_set_ids_preserve_literal_identity(set_id):
    row = sets()["data"][0] | {"set_id": set_id}
    assert pokemon.unique_japanese_sets({"success": True, "data": [row]}) == {"sv11b": row}
    competitor = row | {"set_id": "999" if set_id != "999" else "998"}
    assert not pokemon.unique_japanese_sets({"success": True, "data": [row, competitor]})


@pytest.mark.parametrize("set_id", ["-0", "0", "-01", "01", "+4", "-10000000000", "-4.0", "-4/188", " -4"])
def test_malformed_numeric_set_ids_are_not_release_aliases(set_id):
    row = sets()["data"][0] | {"set_id": set_id}
    assert not pokemon.unique_japanese_sets({"success": True, "data": [row]})


def test_card_printing_must_be_unique_within_entire_japanese_set():
    wanted=pokemon.reference_groups([reference()])
    details={}
    assert pokemon.matching_printings(wanted,'sv11b','23599',[card()],details)==[(reference(),card())]
    assert details['unique_matched']==1
    assert pokemon.matching_printings(wanted,'sv11b','23599',[
        card(),card(id='pk_'+'b'*64,cardmarket=None)])==[]
    assert pokemon.matching_printings(wanted,'sv11b','23599',[
        card(card_info=card()['card_info'] | {'set_code':'other'})])==[]
    assert pokemon.matching_printings(wanted,'sv11b','23599',[
        card(card_info=card()['card_info'] | {'set_id':'23600'})])==[]
    assert pokemon.matching_printings(wanted,'sv11b','23599',[
        card(card_info=card()['card_info'] | {'card_number':'001/087'})])==[]
    assert pokemon.matching_printings(wanted,'sv11b','23599',[
        card(card_info=card()['card_info'] | {'product_type':'sealed'})])==[]


def test_provider_id_formats_include_long_tcgplayer_hashes():
    wanted=pokemon.reference_groups([reference()])
    for item_id in ['pk_'+'a'*88,'pk_'+'b'*96,'c'*64]:
        assert len(pokemon.matching_printings(wanted,'sv11b','23599',
            [card(id=item_id)]))==1
    for item_id in ['pk_'+'z'*88,'d'*80,'pk_'+'f'*129,'random']:
        assert pokemon.matching_printings(wanted,'sv11b','23599',
            [card(id=item_id)])==[]


def test_search_requires_all_pages_and_recognised_exact_query():
    assert pokemon.complete_search_page(search_page(card()),'sv11b',1)[2]==[card()]
    with pytest.raises(pokemon.ProviderResponseError,match='SEARCH_SCHEMA'):
        pokemon.complete_search_page(search_page(card()) | {'query':'other'},'sv11b',1)
    with pytest.raises(pokemon.ProviderResponseError,match='INCOMPLETE_SEARCH'):
        pokemon.complete_search_page(search_page(card()) | {
            'pagination':{'total':2,'page':1,'total_pages':1}},'sv11b',1)


def test_only_exact_public_cardmarket_guide_can_be_quoted():
    quote=pokemon.guide_quote(reference(),card(),'23599',fx(),NOW)
    assert quote['price_gbp_minor']==100
    assert quote['reference_language']=='Japanese'
    assert quote['source']=='POKEWALLET_POKEMON_CARDMARKET_CATALOGUE'
    assert quote['physical_valuation_eligible'] is False
    assert quote['physical_language_confirmed'] is False
    assert quote['condition_specific'] is False
    assert quote['sold_comparable'] is False
    assert quote['finish']=='normal'
    assert pokemon.guide_quote(reference(),card(cardmarket=None),'23599',fx(),NOW) is None
    market=card()['cardmarket']
    for uri in ['https://unrelated.test/en/Pokemon/Products/Singles/Black-Bolt/Pikachu',
                'http://www.cardmarket.com/en/Pokemon/Products/Singles/Black-Bolt/Pikachu',
                'https://www.cardmarket.com/en/Pokemon/Products/Sealed/Black-Bolt/Pikachu']:
        assert pokemon.guide_quote(reference(),card(cardmarket=market|{'product_url':uri}),
            '23599',fx(),NOW) is None
    bad_price=market | {'prices':market['prices']+market['prices']}
    assert pokemon.guide_quote(reference(),card(cardmarket=bad_price),'23599',fx(),NOW) is None
    holo=market | {'prices':[{'variant_type':'holo','trend':2.0}]}
    assert pokemon.guide_quote(reference(),card(cardmarket=holo),'23599',fx(),NOW)['finish']=='holo'


@pytest.mark.parametrize("market,reason", [
    (None, "CARDMARKET_ABSENT"),
    ({"prices": {}}, "PRICE_ARRAY_INVALID"),
    ({"prices": []}, "PRICE_ARRAY_EMPTY"),
    ({"prices": [{"variant_type": "normal", "trend": 2}], "product_url": "https://invalid.example/private"},
     "SINGLE_PRODUCT_URL_INVALID"),
    (card()["cardmarket"] | {"prices": [{"variant_type": "normal", "trend": 0, "avg30": 3}]},
     "POSITIVE_SUPPORTED_TREND_ABSENT"),
    (card()["cardmarket"] | {"prices": [{"variant_type": "untrusted label pk_live_secret", "trend": 9}]},
     "POSITIVE_SUPPORTED_TREND_ABSENT"),
    (card()["cardmarket"] | {"prices": [{"variant_type": ["normal"], "trend": 9}]},
     "POSITIVE_SUPPORTED_TREND_ABSENT"),
    (card()["cardmarket"] | {"prices": [{"variant_type": {"normal": True}, "trend": 9}]},
     "POSITIVE_SUPPORTED_TREND_ABSENT"),
    (card()["cardmarket"] | {"prices": card()["cardmarket"]["prices"] * 2}, "DUPLICATE_FINISH_QUOTES"),
])
def test_quote_diagnostics_explain_missing_fields_without_promoting_another_price(market, reason):
    diagnostics = {}
    assert pokemon.guide_quote(reference(), card(cardmarket=market), "23599", fx(), NOW, diagnostics) is None
    assert diagnostics["reason"] == reason
    assert set(diagnostics) == {"reason", "source_shape"}
    assert all(type(value) is int for value in diagnostics["source_shape"].values())
    serialised = json.dumps(diagnostics)
    assert "pk_live_secret" not in serialised and "https://" not in serialised
    if market and market.get("prices") == [{"variant_type": "normal", "trend": 0, "avg30": 3}]:
        assert diagnostics["source_shape"]["positive_avg30_rows"] == 1
        assert diagnostics["source_shape"]["positive_trend_rows"] == 0


@pytest.mark.parametrize("last_changed", ["2026-09-30T04:00:00Z", "2026-09-30T04:00:00.123456"])
def test_provider_last_price_change_is_preserved_separately_from_observation(last_changed):
    # Pokewallet documents daily checks even while updated_at remains old;
    # a timezone-less literal must not be guessed into a UTC evidence date.
    source = card()
    source["cardmarket"]["prices"][0]["updated_at"] = last_changed
    quote = pokemon.guide_quote(reference(), source, "23599", fx(), NOW)
    assert quote["provider_updated_at"] == last_changed
    assert quote["observed_at"] == NOW.isoformat()


class Response:
    def __init__(self, data, status=200, headers=None):
        self.status_code=status
        self.headers=headers or {}
        self.content=json.dumps(data).encode()
        self.data=data
    def json(self):
        return self.data


class FakeHttp:
    def __init__(self, items=None, *, status=200, headers=None):
        self.items=items if items is not None else [card()]
        self.status=status
        self.headers=headers or {}
        self.calls=[]
    async def get(self, url, params=None, headers=None):
        assert url.startswith(pokemon.BASE_URL)
        assert headers['X-API-Key']=='pk_live_test_fixture'
        self.calls.append((url,params))
        data=sets() if url.endswith('/sets') else search_page(*self.items)
        return Response(data,status=self.status,headers=self.headers)


@pytest.mark.asyncio
async def test_dry_run_then_guarded_apply_without_physical_repricing(monkeypatch):
    captures=[]
    class Connection:
        async def fetch(self, sql):
            assert 'tcg.inventory_items' not in sql
            return [reference()]
        async def executemany(self, sql, rows):
            assert 'tcg.reference_catalogue_prices' in sql
            assert 'tcg.inventory_items' not in sql
            captures.extend(rows)
    @asynccontextmanager
    async def context(*_):
        yield Connection()
    monkeypatch.setattr(pokemon,'user_connection',context)
    class Fx:
        async def quote(self, **kwargs):
            assert kwargs['base_currency']=='EUR' and kwargs['quote_currency']=='GBP'
            return fx()
    http=FakeHttp()
    trial=await pokemon.refresh_pokewallet_pokemon(None,uuid4(),Fx(),
        'pk_live_test_fixture',dry_run=True,http_client=http)
    assert trial['requests']==2 and trial['eligible_quotes']==1
    assert trial['writes_attempted']==0 and captures==[]
    assert [url.rsplit('/',1)[-1] for url,_ in http.calls]==['sets','search']
    assert http.calls[-1][1]=={'q':'sv11b','page':1,'limit':100}
    applied=await pokemon.refresh_pokewallet_pokemon(None,uuid4(),Fx(),
        'pk_live_test_fixture',dry_run=False,http_client=FakeHttp())
    assert applied['writes_attempted']==1
    assert len(captures)==1 and captures[0][0:4]==('TCGdex','POKEMON_TCG','Japanese','SV11B-001')
    assert captures[0][5]==100 and captures[0][-1]==pokemon.SOURCE


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "empty_quote", "rate_limit"])
async def test_old_own_guide_rechecks_source_and_failure_never_re_dates_it(monkeypatch, outcome):
    old = reference(existing_catalogue_value=50, existing_source=pokemon.SOURCE,
                    existing_pricing_updated_at=NOW-timedelta(days=8))
    before = dict(old)
    writes = []
    class Connection:
        async def fetch(self, _):
            return [old]
        async def executemany(self, _, rows):
            writes.extend(rows)
    @asynccontextmanager
    async def context(*_):
        yield Connection()
    monkeypatch.setattr(pokemon, "user_connection", context)
    class Fx:
        async def quote(self, **_):
            return fx()
    item = card() if outcome == "success" else card(cardmarket=card()["cardmarket"] | {"prices": []})
    report = await pokemon.refresh_pokewallet_pokemon(None, uuid4(), Fx(), "pk_live_test_fixture",
        dry_run=False, http_client=FakeHttp(items=[item], status=429 if outcome == "rate_limit" else 200))
    assert report["eligible_references"] == 1 and report["requests"] > 0
    assert old == before
    if outcome == "success":
        assert report["writes_attempted"] == len(writes) == 1
        quote = json.loads(writes[0][4])[0]
        assert quote["provider_updated_at"] == card()["cardmarket"]["prices"][0]["updated_at"]
        assert quote["observed_at"] == writes[0][7].isoformat()
        assert quote["observed_at"] != before["existing_pricing_updated_at"].isoformat()
    else:
        assert report["writes_attempted"] == 0 and writes == []
    if outcome == "empty_quote":
        assert report["quote_rejections"] == {"PRICE_ARRAY_EMPTY": 1}
        assert report["quote_rejection_samples"][0]["reference_id"] == old["provider_id"]


@pytest.mark.asyncio
async def test_quote_rejection_samples_are_bounded_without_losing_counts(monkeypatch):
    refs = [reference(provider_id=f"SV11B-{n:03d}", card_number=f"{n:03d}/086") for n in range(1, 9)]
    items = [card(id="pk_"+f"{n:064x}", card_info=card()["card_info"] | {"card_number": f"{n}/86"},
                  cardmarket=card()["cardmarket"] | {"prices": []}) for n in range(1, 9)]
    class Connection:
        async def fetch(self, _):
            return refs
        async def executemany(self, *_):
            raise AssertionError("Missing quotes must not rewrite old prices")
    @asynccontextmanager
    async def context(*_):
        yield Connection()
    monkeypatch.setattr(pokemon, "user_connection", context)
    class Fx:
        async def quote(self, **_):
            return fx()
    class CompleteHttp(FakeHttp):
        async def get(self, url, params=None, headers=None):
            result = await super().get(url, params=params, headers=headers)
            if url.endswith("/sets"):
                result.data["data"][0]["card_count"] = len(items)
            return result
    report = await pokemon.refresh_pokewallet_pokemon(None, uuid4(), Fx(), "pk_live_test_fixture",
        dry_run=False, http_client=CompleteHttp(items=items))
    assert report["quote_rejections"] == {"PRICE_ARRAY_EMPTY": 8}
    assert len(report["quote_rejection_samples"]) == 5
    assert report["eligible_quotes"] == report["writes_attempted"] == 0


@pytest.mark.asyncio
async def test_bounded_free_endpoint_access_and_fail_closed_quota():
    client=pokemon.FreePokewalletPokemonClient('pk_live_test_fixture',request_limit=5,client=FakeHttp())
    with pytest.raises(pokemon.ProviderResponseError,match='PAID_OR_UNKNOWN_ENDPOINT'):
        await client.get('/prices/SV11B')
    with pytest.raises(pokemon.ProviderResponseError,match='PAID_OR_UNKNOWN_ENDPOINT'):
        await client.get('/cards/pk_id/price-history')
    low=pokemon.FreePokewalletPokemonClient('pk_live_test_fixture',request_limit=5,
        client=FakeHttp(headers={'X-RateLimit-Remaining-Day':'3'}))
    with pytest.raises(pokemon.ProviderResponseError,match='PROVIDER_BUDGET_LOW'):
        await low.get('/sets')
    error=pokemon.FreePokewalletPokemonClient('pk_live_test_fixture',request_limit=5,
        client=FakeHttp(status=429))
    with pytest.raises(pokemon.ProviderResponseError,match='RATE_LIMITED'):
        await error.get('/sets')


@pytest.mark.asyncio
async def test_scheduler_is_opt_in_hourly_and_replays_trial_when_enabled(monkeypatch):
    from types import SimpleNamespace
    from app import catalogue_maintenance as jobs
    now=datetime.now(timezone.utc)
    calls=[]
    state={'prior':None}
    class Conn:
        async def fetchval(self,*args):return True
        async def execute(self,*args):return None
        async def fetch(self,sql,*args):
            if 'reference_sync_runs' in sql:
                return [dict(source=s,status='COMPLETE',started_at=now,
                    report={'importer_revision':jobs.SOURCE_REVISIONS.get(s,1)}) for s in jobs.SOURCES]
            revs={'REFERENCE_PRICES':jobs.REFERENCE_JOB_REVISION,
                'SEALED_REFERENCE_PRICES':jobs.SEALED_MARKET_REVISION,
                'CATALOGUE_VALUES':jobs.CATALOGUE_VALUE_REVISION,
                'CARDMARKET_VALUES':jobs.CARDMARKET_VALUE_REVISION,
                'POKEWALLET_PRICES':jobs.POKEWALLET_JOB_REVISION*10+1}
            rows=[dict(job=job,status='COMPLETE',started_at=now,
                report={'importer_revision':revision}) for job,revision in revs.items()]
            rows.append(dict(job='CATALOGUE_COVERAGE',status='COMPLETE',started_at=now,report={}))
            if state['prior'] is not None:
                rows.append(dict(job='POKEWALLET_POKEMON_PRICES',status='COMPLETE',
                    started_at=state.get('started_at',now),report=state['prior']))
            return rows
    @asynccontextmanager
    async def connection(*_):yield Conn()
    @asynccontextmanager
    async def acquire(*_):yield Conn()
    async def noop(*_):pass
    async def capacity(*_):
        from app.database_capacity import assess_capacity
        return assess_capacity(321_334_419,'off')
    async def refresh(*args,**kwargs):
        calls.append(kwargs)
        return {'requests':3,'eligible_quotes':2,'writes_attempted':0,
            'input_cursor':kwargs.get('previous_cursor'),'cursor':'23600',
            'dry_run':kwargs.get('dry_run')}
    monkeypatch.setattr(jobs,'user_connection',connection)
    monkeypatch.setattr(jobs,'require_platform_admin',noop)
    monkeypatch.setattr(jobs,'check_database_capacity',capacity)
    monkeypatch.setattr(jobs,'refresh_pokewallet_pokemon',refresh)
    monkeypatch.setattr(jobs,'receipt',noop)
    pool=SimpleNamespace(acquire=acquire)
    settings=SimpleNamespace(catalogue_maintenance_actor_user_id=str(uuid4()),
        pokewallet_api_key='pk_live_test_fixture',pokewallet_pricing_apply_enabled=True,
        pokewallet_pricing_request_limit=10,
        pokewallet_pokemon_enabled=False,pokewallet_pokemon_apply_enabled=False)
    await jobs.daily_pass(pool,settings)
    assert not calls
    settings.pokewallet_pokemon_enabled=True
    await jobs.daily_pass(pool,settings)
    assert len(calls)==1 and calls[0]['request_limit']==7 and calls[0]['dry_run'] is True
    assert jobs.DBS_HOURLY_REQUEST_BUDGET+jobs.ONE_PIECE_HOURLY_REQUEST_BUDGET+jobs.POKEMON_HOURLY_REQUEST_BUDGET==35
    state['prior']={'importer_revision':jobs.POKEWALLET_POKEMON_JOB_REVISION*10,
        'dry_run':True,'input_cursor':'23599','cursor':'23600'}
    await jobs.daily_pass(pool,settings)
    assert len(calls)==1  # not every five minutes
    settings.pokewallet_pokemon_apply_enabled=True
    await jobs.daily_pass(pool,settings)
    assert len(calls)==2 and calls[-1]['dry_run'] is False
    assert calls[-1]['previous_cursor']=='23599'
