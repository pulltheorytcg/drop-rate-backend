"""Existing source prices must arrive with search/set cards, independent of owner."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.catalogue_display_prices import reference_key, shared_prices, with_shared_price
from app.catalogue_browser import product_query
from app.cardmarket_valuations import rarity_key
from test_inventory_reference_values import snapshot

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)


def fixtures():
    product = dict(id=uuid4(), product_type='CARD', game='One Piece',
                   name='Capone"Gang"Bege (101)', set_name='A Fist of Divine Speed',
                   card_number='OP11-101', variant='Foil', rarity='SR', language=None, blocked=False)
    base = dict(catalogue_id=str(product['id']), provider='Punk Records', system_code='ONE_PIECE_CARD_GAME',
                provider_id='OP11-101', card_number='OP11-101', name='Capone"Gang"Bege', rarity='SuperRare',
                language='English', set_id='569111', set_name='BOOSTER PACK -A FIST OF DIVINE SPEED- [OP-11]',
                quotes=[], catalogue_quotes=[])
    parallel = dict(base, provider_id='OP11-101_p1')
    japanese = dict(base, language='Japanese', name='カポネ・ベッジ', set_id='550111',
                    set_name='ブースターパック 神速の拳【OP-11】')
    evidence = snapshot(catalogue_id=product['id'], basis_language='English', market_value_minor=132,
                        evidence_checked_at=NOW-timedelta(days=1), calculated_at=NOW,
                        oldest_sale_at=NOW-timedelta(days=10))
    return product, [base, parallel, japanese], evidence


def test_exact_base_reference_uses_same_inventory_evidence_without_pricing_parallel_or_japanese():
    product, refs, evidence = fixtures()
    original = deepcopy((product, refs, evidence))
    prices = shared_prices([product], refs, [evidence], now=NOW)
    assert set(prices) == {'c:' + str(product['id']), reference_key(refs[0])}
    value = prices[reference_key(refs[0])]
    assert value['market_value_minor'] == 132
    assert value['shared_price']['status'] == 'CONDITION_REFERENCE'
    assert value['shared_price']['recommended_retail_minor'] is None
    assert value['shared_price']['physical_valuation_eligible'] is False
    assert value['pricing_updated_at'] == evidence['evidence_checked_at']
    for owner in ('account-a', 'account-b'):
        row = dict(key=reference_key(refs[0]), catalogue_id=None, owned_quantity=0,
                   market_value_minor=None, owner=owner, market_refresh_needed=True)
        display = with_shared_price(row, prices)
        assert display['market_value_minor'] == 132 and not display['market_refresh_needed']
        assert display['catalogue_id'] is None and display['owned_quantity'] == 0
        assert row['market_value_minor'] is None
    assert (product, refs, evidence) == original


@pytest.mark.parametrize('change', [
    {'blocked': True}, {'variant': 'Alternate Art'}, {'rarity': 'SEC'},
    {'set_name': 'Romance Dawn'}, {'card_number': 'OP11-102'}, {'language': 'Japanese'},
])
def test_changed_identity_or_rejected_mapping_never_borrows_the_price(change):
    product, refs, evidence = fixtures(); product.update(change)
    assert not shared_prices([product], refs, [evidence], now=NOW)


def test_unpriced_duplicate_canonical_record_blocks_reference_alias_resolution():
    product, refs, evidence = fixtures()
    duplicate = dict(product, id=uuid4())
    duplicate_refs = [dict(r, catalogue_id=str(duplicate['id'])) for r in refs]
    prices = shared_prices([product, duplicate], refs + duplicate_refs, [evidence], now=NOW)
    assert reference_key(refs[0]) not in prices
    assert prices['c:' + str(product['id'])]['market_value_minor'] == 132


def test_old_shared_price_remains_dated_history_without_becoming_current_or_sort_value():
    product, refs, evidence = fixtures()
    evidence['evidence_checked_at'] = NOW-timedelta(days=8)
    prices = shared_prices([product], refs, [evidence], now=NOW)
    value = prices[reference_key(refs[0])]
    assert value['market_value_minor'] is None
    assert value['shared_price']['last_known_minor'] == 132
    assert value['shared_price']['status'] == 'STALE'
    assert value['pricing_updated_at'] == NOW-timedelta(days=8)


def test_cached_reference_price_and_identity_take_precedence_over_alias_fallback():
    product, refs, evidence = fixtures()
    prices = shared_prices([product], refs, [evidence], now=NOW)
    row = dict(key=reference_key(refs[0]), market_value_minor=150,
               market_value_source='CARDMARKET_BULK_SINGLES', catalogue_id=None)
    assert with_shared_price(row, prices) == row


@pytest.mark.asyncio
async def test_page_shared_price_fetches_only_number_matched_ids_including_padded_siblings():
    from app import catalogue_display_prices as display
    ids = [uuid4(), uuid4(), uuid4()]
    products = [dict(id=ids[0], card_number="OP04-083", product_type="CARD"),
                dict(id=ids[1], card_number="OP4-83", product_type="CARD"),
                dict(id=ids[2], card_number="OP04-084", product_type="CARD")]
    calls = []
    class Connection:
        async def fetch(self, sql, *args):
            calls.append(sql)
            if sql == display.PAGE_IDS_SQL:
                assert "OP04083" in args[0] and "OP483" in args[0]
                return products
            if sql == display.PRODUCTS_SQL:
                assert list(args[0]) == ids[:2]
                return products[:2]
            raise AssertionError("Page lookup must never read every catalogue product")
    found = await display._page_products(Connection(), [dict(product_type="CARD",card_number="OP04-083")])
    assert [p['id'] for p in found] == ids[:2]
    assert calls == [display.PAGE_IDS_SQL, display.PRODUCTS_SQL]


@pytest.mark.asyncio
async def test_legacy_58_102_does_not_price_any_unrelated_number_58():
    from app import catalogue_display_prices as display
    ids = [uuid4(), uuid4()]
    legacy = dict(id=ids[0], product_type='CARD', game='Pokemon',
                  name='Pikachu', set_name='Base Set (Unlimited)',
                  card_number='58', variant='Normal', rarity='Common', language='English')
    unrelated = dict(legacy, id=ids[1], name='Other')
    class Connection:
        async def fetch(self, sql, *args):
            if sql == display.PAGE_IDS_SQL:
                assert '58' in args[0]
                return [legacy,unrelated]
            assert sql == display.PRODUCTS_SQL
            return [legacy,unrelated]
    found = await display._page_products(Connection(), [dict(card_number='58/102')])
    assert [p['id'] for p in found] == [ids[0]]


@pytest.mark.asyncio
async def test_book_only_page_without_card_number_still_resolves_book_price(monkeypatch):
    from app import catalogue_display_prices as display
    book = dict(catalogue_id=uuid4(), product_type='COMIC', card_number=None)
    expected = {'c:' + str(book['catalogue_id']): {'market_value_minor': 1200}}
    class Connection:
        async def fetch(self, sql, *args):
            return []
    async def book_prices(connection, rows, *, now):
        assert rows == [book] and now == NOW
        return expected
    monkeypatch.setattr(display, 'read_book_prices', book_prices)
    assert await display.read_shared_prices(Connection(), [book], now=NOW) == expected


@pytest.mark.asyncio
async def test_shared_price_ranking_skips_unrelated_games_and_book_lookups(monkeypatch):
    from app import catalogue_display_prices as display
    one_piece, _, _ = fixtures()
    pokemon = dict(one_piece, id=uuid4(), game='Pokémon', card_number='001/100')
    visited = []
    class Connection:
        async def fetch(self, sql, *args):
            if sql == display.PRODUCTS:
                return [one_piece, pokemon]
            if sql == display.CACHE_SQL:
                lookups = __import__('json').loads(args[0])
                visited.extend(lookups)
                return []
            if sql == display.REFERENCE_VALUES_SQL:
                return []
            raise AssertionError('Unrelated book or provider query during card ranking')
    def system(product):
        return 'POKEMON_TCG' if product['game'] == 'Pokémon' else 'ONE_PIECE_CARD_GAME'
    async def forbidden(*args, **kwargs):
        raise AssertionError('Book prices should not be loaded for card-only ranking')
    monkeypatch.setattr(display, 'catalogue_system', system)
    monkeypatch.setattr(display, 'read_book_prices', forbidden)
    result = await display.read_shared_prices(Connection(), system_code='POKEMON_TCG',
                                              product_type='CARD', now=NOW)
    assert result == {}
    assert [row['catalogue_id'] for row in visited] == [str(pokemon['id'])]


@pytest.mark.parametrize('sort', ['value_asc', 'value_desc'])
def test_value_sort_includes_shared_price_before_pagination(sort):
    import json
    product, refs, evidence = fixtures()
    prices = shared_prices([product], refs, [evidence], now=NOW)
    sql, params = product_query(owner_id=uuid4(), sort=sort, shared_prices=prices, limit=1, offset=1)
    assert sql.index('left join shared_display d') < sql.index('limit $')
    assert 'coalesce(v.market_value_minor,e.reference_value_minor,d.market_value_minor)' in sql
    assert json.loads(params[-3])[0]['shared_price']['physical_valuation_eligible'] is False
    assert params[-2:] == [2, 1]


@pytest.mark.parametrize('text,expected', [('SuperRare', 'SR'), ('Super Rare', 'SR'), ('SR', 'SR'),
                                         ('SecretRare', 'SEC'), ('Secret Rare', 'SEC'),
                                         ('SpecialRare', 'SPECIALRARE'), ('SuperRare Parallel', 'SUPERRARE PARALLEL')])
def test_explicit_provider_rarity_spellings_do_not_collapse_parallel_rarities(text, expected):
    assert rarity_key(text) == expected
