from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from uuid import uuid4

import pytest

from app.uk_eu_reference_display import (
    IDENTITY_KEYS, METHOD, MODEL_DISPLAY_SQL, REFERENCE_KEYS, add_uk_eu_estimates,
    cached_browse_report, cardmarket_model_guide, estimate_from_reference, public_model_view,
)

NOW = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
MATCHING = dict(provider_variant=None, variant_title_terms=None, set_title_terms=None, set_name=None)


def fixture():
    reference = dict(provider='TCGdex', system_code='POKEMON_TCG', language='English',
        provider_id='swsh4-25', name='Charizard', set_id='swsh4', card_number='25/185',
        set_name='Vivid Voltage', finish=None, rarity=None, evidence={})
    quote = dict(source='TCGDEX_CARDMARKET', product_id='12345', variant_id='normal',
        variant_label='Normal', finish='Normal', reference_language='English', source_field='trend',
        price_gbp_minor=1000, original_minor=1250, original_currency='EUR', fx_rate_to_gbp='0.8',
        fx_source='ECB_EURO_REFERENCE_RATES', observed_at=NOW.isoformat(),
        fx_effective_at=(NOW-timedelta(days=1)).isoformat(), fx_retrieved_at=NOW.isoformat())
    reference.update(quotes=[quote], catalogue_quotes=[])
    identity = {k: reference.get(k) for k in IDENTITY_KEYS}
    comparables = [dict(item_id=str(1000+i), seller_hash=hashlib.sha256(f'seller{i}'.encode()).hexdigest(),
        price_gbp_minor=price, shipping_gbp_minor=200, title='Charizard 25/185',
        listing_evidence={'acquisition': 'GET_ITEM', 'condition_id': '4000'})
        for i, price in enumerate((1000, 1100, 1200))]
    evidence = dict(source='EBAY_OFFICIAL_BROWSE', shipping_basis='ITEM_PLUS_SHIPPING',
        shipping_context='CONFIGURED_SHOP_POSTCODE_BENCHMARK', condition='Near Mint', finish='Normal',
        matching_reference_evidence=dict(MATCHING), reference_group_count=1, comparables=comparables,
        match_proof=dict(game='POKEMON_TCG', language='english', card_number='25/185'))
    record = dict(**{k: reference[k] for k in REFERENCE_KEYS}, key='r:fixture', snapshot_id=uuid4(),
        method_version='EBAY_UK_RAW_ASK_V1', currency='GBP', estimate_minor=1300, estimate_high_minor=1400,
        listing_count=3, seller_count=3, observed_at=NOW, expires_at=NOW+timedelta(days=3),
        reference_identity=deepcopy(identity), current_identity=deepcopy(identity),
        current_matching_reference_evidence=dict(MATCHING), current_reference_group_count=1,
        reference_evidence={}, evidence=evidence, market_quotes=[quote], catalogue_quotes=[])
    return reference, record, quote


def complete(coroutine):
    """All awaits here are in-memory mocks, requiring no network/event-loop sockets."""
    with pytest.raises(StopIteration) as stopped:
        coroutine.send(None)
    return stopped.value.value


def test_actual_cached_evidence_produces_item_only_public_model_without_private_evidence():
    reference, record, _ = fixture()
    before = deepcopy((reference, record))
    report = cached_browse_report(record, now=NOW)
    result = estimate_from_reference(reference, report, now=NOW)
    assert result['status'] == 'READY'
    view = public_model_view(result)
    assert view['estimate_minor'] == 1050
    assert view['method'] == METHOD and view['shipping_basis'] == 'ITEM_ONLY'
    assert view['finish'] == 'Normal' and view['computed_at'] == NOW.isoformat()
    assert view['sold_observation_count'] == 0 and view['physical_valuation_eligible'] is False
    assert 'seller_hash' not in json.dumps(view) and 'item_id' not in json.dumps(view)
    assert (reference, record) == before


@pytest.mark.parametrize('changes', [
    {'source': 'TCGDEX_CARDMARKET_VARIANT'}, {'source': 'CARDMARKET_CATALOGUE'},
    {'variant_label': 'Normal · unlimited'}, {'finish': 'Reverse Holofoil'},
    {'reference_language': 'Japanese'}, {'source_field': 'low'}, {'source_field': 'avg30'},
    {'source_field': 'trend-holo'}, {'product_id': True}, {'product_id': '0'}, {'variant_id': ''},
    {'original_currency': 'USD'}, {'fx_source': 'GUESS'}, {'fx_rate_to_gbp': 'NaN'},
    {'price_gbp_minor': 1200}, {'price_gbp_minor': True}, {'original_minor': 0},
    {'observed_at': (NOW+timedelta(seconds=1)).isoformat()},
    {'observed_at': (NOW-timedelta(days=8)).isoformat()},
    {'fx_effective_at': (NOW+timedelta(seconds=1)).isoformat()},
    {'fx_effective_at': (NOW-timedelta(days=8)).isoformat()}, {'fx_effective_at': None},
    {'fx_retrieved_at': (NOW+timedelta(seconds=1)).isoformat()}, {'fx_retrieved_at': 'bad'},
    {'reference_identity': {'name': 'Wrong card'}},
])
def test_wrong_or_unverifiable_guide_never_enters_model(changes):
    reference, _, quote = fixture()
    quote.update(changes)
    assert cardmarket_model_guide(reference, 'Normal', now=NOW) is None


def test_reverse_holo_uses_the_importer_trend_holo_field():
    reference, _, quote = fixture()
    quote.update(finish='Reverse Holofoil', variant_label='Reverse Holofoil', source_field='trend-holo')
    assert cardmarket_model_guide(reference, 'Reverse Holo', now=NOW)['finish'] == 'Reverse Holo'


def test_conflicting_exact_source_products_are_not_resolved_by_price():
    reference, _, quote = fixture()
    reference['quotes'].append(dict(quote, product_id='98765'))
    assert cardmarket_model_guide(reference, 'Normal', now=NOW) is None


def test_duplicate_source_snapshot_is_one_guide_and_conflicting_snapshot_is_rejected():
    reference, _, quote = fixture()
    reference['quotes'].append(dict(quote))
    assert cardmarket_model_guide(reference, 'Normal', now=NOW)['price_gbp_minor'] == 1000
    reference['quotes'].append(dict(quote, price_gbp_minor=1080, original_minor=1350))
    assert cardmarket_model_guide(reference, 'Normal', now=NOW) is None


def test_known_listing_end_is_preserved_and_cannot_renew_a_model():
    reference, record, _ = fixture()
    record['evidence']['comparables'][0]['listing_evidence']['item_end_date'] = NOW.isoformat()
    report = cached_browse_report(record, now=NOW)
    assert report['comparables'][0]['listing_evidence']['item_end_date'] == NOW.isoformat()
    assert estimate_from_reference(reference, report, now=NOW)['status'] == 'INSUFFICIENT_INDEPENDENT_LISTINGS'


@pytest.mark.parametrize('change', [
    {'expires_at': NOW}, {'current_identity': {}}, {'current_reference_group_count': 2},
    {'observed_at': NOW+timedelta(seconds=1)}, {'evidence': 'invalid json'},
])
def test_invalid_or_stale_cache_is_not_reconstructed(change):
    _, record, _ = fixture()
    record.update(change)
    assert cached_browse_report(record, now=NOW) is None


class Connection:
    def __init__(self, records):
        self.records, self.calls = records, []

    async def fetch(self, query, keys, now):
        self.calls.append((query, json.loads(keys), now))
        return self.records


def test_page_projection_keeps_existing_price_fields_and_batches_duplicate_references():
    reference, record, _ = fixture()
    rows = [dict(reference, key='r:one', source_kind='REFERENCE', product_type='CARD', market_value_minor=1000),
            dict(reference, key='r:two', market_value_minor=None)]
    before = deepcopy(rows)
    connection = Connection([record])
    result = complete(add_uk_eu_estimates(connection, rows, now=NOW))
    assert rows == before
    assert [r['market_value_minor'] for r in result] == [1000, None]
    assert all(r['uk_eu_market_estimate']['estimate_minor'] == 1050 for r in result)
    assert len(connection.calls) == 1 and len(connection.calls[0][1]) == 1
    assert 'reference_group_count' in MODEL_DISPLAY_SQL and 'a.snapshot_id' in MODEL_DISPLAY_SQL


def test_cache_expiry_removes_previously_attached_model_without_changing_guide():
    reference, record, _ = fixture()
    record['expires_at'] = NOW
    row = dict(reference, market_value_minor=1000, uk_eu_market_estimate={'estimate_minor': 900})
    result = complete(add_uk_eu_estimates(Connection([record]), [row], now=NOW))
    assert 'uk_eu_market_estimate' not in result[0] and result[0]['market_value_minor'] == 1000


def test_non_card_graded_named_variant_and_empty_input_do_not_query_cache():
    reference, _, quote = fixture()
    connection = Connection([])
    rows = [dict(reference, product_type='COMIC'), dict(reference, grade='10'),
            dict(reference, seal_status='SEALED'), dict(reference, provider='Other'),
            dict(reference, quotes=[dict(quote, source='TCGDEX_CARDMARKET_VARIANT')])]
    complete(add_uk_eu_estimates(connection, rows, now=NOW))
    assert connection.calls == []


def test_inventory_exact_raw_reference_gets_model_without_changing_physical_money():
    from app.inventory_catalogue_reference import add_catalogue_references
    reference, record, _ = fixture()
    product = dict(id=uuid4(), product_type='CARD', game='Pokemon', name=reference['name'],
        set_name=reference['set_name'], card_number=reference['card_number'], rarity='Unknown',
        variant='Normal', language='English', blocked=False)
    reference['catalogue_id'] = str(product['id'])
    class InventoryConnection:
        async def fetch(self, query, *args):
            if query == MODEL_DISPLAY_SQL:
                return [record]
            return [reference] if 'select k.catalogue_id' in query else [product]
    item = dict(catalogue_id=product['id'], product_type='CARD', language='English',
        condition='Near Mint', market_value_minor=None, recommended_retail_minor=None, store_price_minor=1800)
    complete(add_catalogue_references(InventoryConnection(), [item], now=NOW))
    assert item['catalogue_reference']['method'] == METHOD
    assert item['catalogue_reference']['market_value_minor'] == 1050
    assert item['catalogue_reference']['physical_valuation_eligible'] is False
    assert item['market_value_minor'] is None and item['recommended_retail_minor'] is None
    assert item['store_price_minor'] == 1800


def test_existing_physical_value_and_graded_copy_skip_model_projection():
    from app.inventory_catalogue_reference import add_catalogue_references
    class NoRead:
        async def fetch(self, *args):
            raise AssertionError('A priced or graded copy must not query model evidence')
    items = [dict(catalogue_id=uuid4(), product_type='CARD', market_value_minor=3000),
             dict(catalogue_id=uuid4(), product_type='CARD', market_value_minor=None, grade='10')]
    before = deepcopy(items)
    assert complete(add_catalogue_references(NoRead(), items, now=NOW)) == before
