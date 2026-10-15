"""Reference display never changes a copy's valuation or publishing authority."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.inventory_catalogue_reference import catalogue_guide
from app.inventory_reference_values import add_shared_reference_values, reference_totals, recommended_totals

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)


def fixtures():
    product = dict(id=uuid4(), product_type='CARD', game='Pokemon', name='Heat Rotom',
                   set_name='Destined Rivals', card_number='043/182', variant='sv10-043',
                   rarity='Unknown', language='English', blocked=False)
    quote = dict(source='TCGDEX_CARDMARKET', reference_language='English',
                 price_gbp_minor=85, original_minor=100, original_currency='EUR',
                 fx_source='ECB_EURO_REFERENCE_RATES', fx_rate_to_gbp='0.85',
                 observed_at=(NOW-timedelta(hours=1)).isoformat(), finish='Normal')
    ref = dict(provider='TCGdex', system_code='POKEMON_TCG', language='English',
               provider_id='sv10-043', name='Heat Rotom', set_name='Destined Rivals',
               set_id='sv10', card_number='043/182', rarity=None, quotes=[quote], catalogue_quotes=[])
    return product, ref, quote


def test_selected_reference_has_a_range_without_asserting_a_physical_finish():
    product, ref, quote = fixtures()
    ref['quotes'].append(dict(quote, finish='Reverse Holofoil', original_minor=200, price_gbp_minor=170))
    before = deepcopy((product, ref))
    value = catalogue_guide(product, [ref], 'English', now=NOW)
    assert (value['market_value_minor'], value['market_value_high_minor']) == (85, 170)
    assert value['status'] == 'CATALOGUE_GUIDE' and not value['physical_valuation_eligible']
    assert value['recommended_retail_minor'] is None
    assert (product, ref) == before


@pytest.mark.parametrize('change', [
    {'price_gbp_minor': 0}, {'price_gbp_minor': True}, {'price_gbp_minor': 999},
    {'observed_at': (NOW-timedelta(days=8)).isoformat()},
    {'observed_at': (NOW+timedelta(seconds=1)).isoformat()},
    {'source': 'TCGDEX_TCGPLAYER'}, {'original_currency': 'USD'},
    {'reference_language': 'Japanese'}, {'fx_rate_to_gbp': 'NaN'},
    {'fx_source': 'GUESSED'}, {'observed_at': '2026-10-15'},
])
def test_invalid_wrong_region_or_old_quotes_do_not_become_guides(change):
    product, ref, quote = fixtures();quote.update(change)
    assert catalogue_guide(product, [ref], 'English', now=NOW) is None


@pytest.mark.parametrize('change', [
    {'blocked': True}, {'variant': 'sv10-043-alt'}, {'set_name': 'Another release'},
    {'card_number': '044/182'}, {'name': 'Another card'}, {'rarity': 'Rare'},
])
def test_identity_or_review_mismatch_stays_unavailable(change):
    product, ref, _ = fixtures();product.update(change)
    assert catalogue_guide(product, [ref], 'English', now=NOW) is None


def test_legacy_finish_uses_only_its_quote_and_unpriced_duplicates_block():
    product, ref, quote = fixtures();product['variant'] = 'Normal'
    ref['quotes'].append(dict(quote, finish='Reverse Holofoil', original_minor=200, price_gbp_minor=170))
    value = catalogue_guide(product, [ref], 'English', now=NOW)
    assert value['market_value_minor'] == value['market_value_high_minor'] == 85
    duplicate = dict(ref, provider_id='another-printing', quotes=[])
    assert catalogue_guide(product, [ref, duplicate], 'English', now=NOW) is None


def test_bulk_guide_requires_current_identity_and_rarity():
    product, ref, quote = fixtures()
    quote.update(source='CARDMARKET_BULK_SINGLES', reference_printing_id=ref['provider_id'],
                 reference_rarity=None, reference_identity={k: ref[k] for k in ('name','set_id','card_number','set_name')})
    assert catalogue_guide(product, [ref], 'English', now=NOW)
    quote['reference_identity']['card_number'] = '044/182'
    assert catalogue_guide(product, [ref], 'English', now=NOW) is None


def test_japanese_import_requires_its_own_region_quote_and_explicit_counterpart():
    product, _, quote = fixtures()
    product.update(game='One Piece', name='Roronoa Zoro', set_name='Romance Dawn',
                   card_number='OP01-001', variant='Normal', rarity='L', language='Japanese')
    en = dict(provider='Punk Records',system_code='ONE_PIECE_CARD_GAME',language='English',
              provider_id='OP01-001',card_number='OP01-001',name='Roronoa Zoro',rarity='Leader',
              set_id='569101',set_name='BOOSTER PACK -ROMANCE DAWN- [OP-01]', quotes=[quote])
    jp = dict(en,language='Japanese',name='ロロノア・ゾロ',set_id='550101',
              set_name='ブースターパック ROMANCE DAWN【OP-01】',quotes=[])
    quote = dict(quote,source='CARDMARKET_BULK_SINGLES',reference_language='Japanese',
                 valuation_role='MIXED_NON_ENGLISH_REFERENCE', reference_printing_id='OP01-001', reference_rarity='Leader',
                 match_basis='OFFICIAL_JP_EN_BASE_ID_AND_UNIQUE_NONENGLISH_MARKET_PRODUCT',
                 english_checklist_provider_id='OP01-001',english_checklist_set_id='569101',
                 reference_identity={k:jp[k] for k in ('name','set_id','card_number','set_name')})
    jp['quotes'] = [quote]
    value = catalogue_guide(product, [en,jp], 'Japanese', now=NOW)
    assert value['label'] == 'Regional guide' and not value['physical_valuation_eligible']
    quote['valuation_role'] = 'MIXED_LANGUAGE_REFERENCE'
    assert catalogue_guide(product, [en,jp], 'Japanese', now=NOW) is None
    jp['quotes'] = []
    assert catalogue_guide(product, [en,jp], 'Japanese', now=NOW) is None


@pytest.mark.asyncio
async def test_read_only_display_is_identical_across_accounts_without_inflating_totals():
    product, ref, _ = fixtures();ref['catalogue_id'] = str(product['id'])
    class Connection:
        async def fetch(self, sql, *args):
            if 'snapshot_id' in sql:return []
            if 'jsonb_to_recordset' in sql:return [ref]
            return [product]
    items = [dict(catalogue_id=product['id'], product_type='CARD', language='English',
                  condition=condition, owner_id=owner, store_price_minor=asking)
             for owner,condition,asking in [('A',None,500),('B','Near Mint',700)]]
    await add_shared_reference_values(Connection(), items, now=NOW)
    assert items[0]['catalogue_reference'] == items[1]['catalogue_reference']
    assert all(i['market_value_minor'] is None and i['recommended_retail_minor'] is None for i in items)
    assert [i['store_price_minor'] for i in items] == [500,700]
    assert reference_totals(items)['total_minor'] is None
    assert recommended_totals(items)['active_recommended_retail_minor'] is None


@pytest.mark.asyncio
async def test_unfinished_capone_displays_nm_comparison_without_confirming_condition():
    from test_inventory_reference_values import snapshot, item, CAT
    evidence = snapshot(evidence_checked_at=NOW-timedelta(days=1), calculated_at=NOW,
                        oldest_sale_at=NOW-timedelta(days=10))
    class Connection:
        async def fetch(self, sql, *args):
            assert 'snapshot_id' in sql
            return [evidence]
    copy = item();copy.update(condition=None)
    await add_shared_reference_values(Connection(), [copy], now=NOW)
    assert copy['condition'] is None and copy['market_value_minor'] is None
    assert copy['catalogue_reference']['market_value_minor'] == 1200
    assert copy['catalogue_reference']['label'] == 'Near-mint reference'
    assert copy['catalogue_reference']['recommended_retail_minor'] is None
