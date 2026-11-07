"""The existing algorithm's snapshot recommendations, not guessed portfolio prices."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from app.inventory_reference_values import resolve_reference_value, add_shared_reference_values, recommended_totals, SOLD, GUIDE

NOW = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
CAT = uuid4()

def row(**changes):
    item = dict(catalogue_id=CAT, product_type='CARD', language='Japanese', catalogue_language='Japanese',
                condition='Near Mint', grading_company=None, grade=None, seal_status=None,
                market_value_minor=None, recommended_retail_minor=999999, store_price_minor=None)
    item.update(changes)
    return item

def snapshot(**changes):
    value = dict(snapshot_id=uuid4(), catalogue_id=CAT, basis_language='Japanese', basis_condition='Near Mint',
                 grading_company=None, grade=None, seal_status=None, market_value_minor=1200,
                 recommended_retail_minor=1500, method=SOLD, algorithm_version='drop-rate-market-v4',
                 input_sale_count='5', reference_current=True, evidence_checked_at=NOW-timedelta(days=1),
                 calculated_at=NOW-timedelta(hours=1), oldest_sale_at=NOW-timedelta(days=10))
    value.update(changes)
    return value

def test_market_and_recommendation_come_from_the_same_selected_snapshot():
    old = snapshot(market_value_minor=500, recommended_retail_minor=700, evidence_checked_at=NOW-timedelta(days=2))
    chosen = snapshot()
    result = resolve_reference_value(row(store_price_minor=9999), [old, chosen], now=NOW)
    assert result['market_value_minor'] == 1200 and result['recommended_retail_minor'] == 1500
    assert result['snapshot_id'] == str(chosen['snapshot_id'])

@pytest.mark.parametrize('changes', [
    {'evidence_checked_at': NOW-timedelta(days=8)}, {'oldest_sale_at': NOW-timedelta(days=91)},
    {'basis_language': 'English'}, {'grading_company': 'PSA', 'grade': '10', 'basis_condition': None},
    {'reference_current': False}, {'market_value_minor': 0}, {'calculated_at': NOW+timedelta(days=1)},
])
def test_ineligible_evidence_never_supplies_a_recommendation(changes):
    assert resolve_reference_value(row(), [snapshot(**changes)], now=NOW)['recommended_retail_minor'] is None

@pytest.mark.parametrize('value', [None, 0, -1, True, 99, '1500', 15.0])
def test_invalid_recommendation_is_not_replaced_with_a_manual_or_guessed_price(value):
    result = resolve_reference_value(row(store_price_minor=9000), [snapshot(recommended_retail_minor=value)], now=NOW)
    assert result['market_value_minor'] == 1200 and result['recommended_retail_minor'] is None

@pytest.mark.asyncio
async def test_reads_replace_legacy_cache_in_response_only_and_do_not_call_a_writer():
    class Connection:
        async def fetch(self, sql, ids, now):
            assert 's.recommended_retail_minor' in sql and ids == [CAT]
            return [snapshot(market_value_minor=3, recommended_retail_minor=100, method=GUIDE,
                             basis_condition=None, input_sale_count='0', oldest_sale_at=None)]
    items = [row(id=uuid4(), owner_id='A', store_price_minor=1000), row(id=uuid4(), owner_id='B', store_price_minor=2000)]
    result = await add_shared_reference_values(Connection(), items, now=NOW)
    assert all(i['market_value_minor'] == 3 and i['recommended_retail_minor'] == 100 for i in result)
    assert [i['store_price_minor'] for i in result] == [1000, 2000]
    assert result[0]['reference_value']['status'] == 'REFERENCE_ESTIMATE'
    totals = recommended_totals(result)
    assert totals['active_recommended_retail_minor'] == 200 and totals['recorded_asking_value_minor'] == 3000
    assert totals['recommendation_guide_count'] == 2

def test_copy_counts_partial_totals_and_saved_asking_prices_stay_separate():
    items = [row(recommended_retail_minor=1500, store_price_minor=1000,
                 reference_value={'status': 'AVAILABLE', 'recommended_retail_minor': 1500}) for _ in range(2)]
    items += [row(recommended_retail_minor=None, reference_value={'status': 'UNAVAILABLE'}) for _ in range(97)]
    before = deepcopy(items)
    result = recommended_totals(items)
    assert result == dict(active_inventory_count=99, active_recommended_count=2, active_unrecommended_count=97,
                          active_recommended_retail_minor=3000, recommendation_guide_count=0,
                          recorded_asking_count=2, recorded_asking_value_minor=2000)
    assert items == before

def test_no_recommendation_is_null_even_when_manual_prices_exist():
    result = recommended_totals([row(store_price_minor=500, reference_value={'status': 'STALE'})])
    assert result['active_recommended_retail_minor'] is None and result['recorded_asking_value_minor'] == 500
    assert recommended_totals([])['active_inventory_count'] == 0
