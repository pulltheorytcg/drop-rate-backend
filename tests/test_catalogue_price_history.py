from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from app.catalogue_price_history import add_reference_history, historical_guide, HISTORY_SQL

NOW = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
CHECKED = NOW - timedelta(days=8)


def record(**changes):
    value = dict(key='r:'+'a'*32, provider='TCGdex', system_code='POKEMON_TCG',
                 language='English', provider_id='base1-1', name='Alakazam', set_id='base1',
                 card_number='1', rarity='Rare', set_name='Base Set', kind='detailed',
                 market_value_minor=800, market_value_high_minor=1200, pricing_updated_at=CHECKED,
                 quotes=[dict(source='TCGDEX_CARDMARKET', price_gbp_minor=amount,
                              original_minor=amount, original_currency='EUR', fx_rate_to_gbp='1',
                              fx_source='ECB_EURO_REFERENCE_RATES', observed_at=CHECKED.isoformat(),
                              reference_language='English') for amount in (800,1200)])
    value.update(changes)
    return value


def test_original_range_date_and_source_remain_history_without_current_or_retail_value():
    row = record(); before = deepcopy(row)
    result = historical_guide(row, now=NOW)
    assert result['status'] == 'STALE'
    assert result['market_value_minor'] is None and result['market_value_high_minor'] is None
    assert result['last_known_minor'] == 800 and result['last_known_high_minor'] == 1200
    assert result['checked_at'] == CHECKED and result['source'] == 'Cardmarket'
    assert result['recommended_retail_minor'] is None and result['physical_valuation_eligible'] is False
    assert 'not a current value or an exact-copy sale' in result['reason']
    assert row == before


@pytest.mark.parametrize('changes', [
    {'pricing_updated_at': NOW}, {'pricing_updated_at': CHECKED-timedelta(hours=1)},
    {'market_value_minor': 900}, {'market_value_high_minor': 1300}, {'language': 'Japanese'},
    {'provider': 'Unrelated'}, {'quotes': []}, {'quotes': '{bad'},
])
def test_changed_or_current_evidence_is_not_used_as_history(changes):
    assert historical_guide(record(**changes), now=NOW) is None


@pytest.mark.parametrize('changes', [
    {'source': 'TCGDEX_TCGPLAYER'}, {'source': 'UNAPPROVED'}, {'original_currency': 'USD'},
    {'fx_rate_to_gbp': '0.8'}, {'fx_rate_to_gbp': 'NaN'}, {'price_gbp_minor': True},
    {'observed_at': (NOW+timedelta(hours=1)).isoformat()}, {'reference_language': 'Japanese'},
])
def test_unsupported_quote_never_becomes_gbp_history(changes):
    row = record(); row['quotes'] = [dict(row['quotes'][0], **changes)]
    assert historical_guide(row, now=NOW) is None


@pytest.mark.parametrize('kind,source', [('catalogue','CARDMARKET_CATALOGUE'), ('detailed','CARDMARKET_BULK_SINGLES')])
def test_broad_guides_still_require_exact_reference_identity(kind, source):
    row = record(kind=kind)
    for quote in row['quotes']:
        quote.update(source=source, reference_identity={k:row[k] for k in ('name','set_id','card_number','set_name')},
                     reference_printing_id=row['provider_id'], reference_rarity=row['rarity'])
    assert historical_guide(row, now=NOW)
    row['set_name'] = 'Another printing'
    assert historical_guide(row, now=NOW) is None


def test_japanese_regional_history_cannot_claim_english_price_or_verified_japanese_value():
    row = record(language='Japanese')
    for quote in row['quotes']:
        quote.update(source='CARDMARKET_BULK_SINGLES', reference_language='Japanese',
                     reference_identity={k:row[k] for k in ('name','set_id','card_number','set_name')},
                     reference_printing_id=row['provider_id'], reference_rarity=row['rarity'])
    assert historical_guide(row, now=NOW) is None
    for quote in row['quotes']: quote['valuation_role'] = 'MIXED_NON_ENGLISH_REFERENCE'
    result = historical_guide(row, now=NOW)
    assert 'Japanese language was not verified' in result['reason']
    row['rarity'] = 'Parallel'
    assert historical_guide(row, now=NOW) is None


@pytest.mark.asyncio
async def test_page_scoped_history_is_returned_without_reordering_or_price_overwrite():
    row = record()
    fields = ('key','provider','system_code','language','provider_id')
    missing = {k:row[k] for k in fields}
    missing.update(source_kind='REFERENCE', market_value_minor=None, market_refresh_needed=True)
    current = dict(missing, key='r:'+'b'*32, market_value_minor=999)
    canonical = dict(missing, key='c:canonical', source_kind='CATALOGUE')
    known = dict(missing, key='r:'+'c'*32, shared_price={'status':'STALE','last_known_minor':100})
    before = deepcopy([current,missing,canonical,known])
    class Connection:
        async def fetch(self, sql, payload, now):
            assert sql == HISTORY_SQL and now == NOW
            assert json.loads(payload) == [{k:missing[k] for k in fields}]
            return [row]
    result = await add_reference_history(Connection(), [current,missing,canonical,known], now=NOW)
    assert [r['key'] for r in result] == [r['key'] for r in before]
    assert result[0] == current and result[2:] == [canonical,known]
    assert result[1]['market_value_minor'] is None
    assert result[1]['shared_price']['last_known_minor'] == 800
    assert result[1]['market_refresh_needed'] is True
    assert [current,missing,canonical,known] == before
