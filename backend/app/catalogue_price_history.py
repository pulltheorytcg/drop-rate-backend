"""Dated catalogue guides remain visible when a refresh is unavailable.

Only the existing exact provider key is read. Historical guides never fill a
current value, change value sorting, price inventory, or make provider requests.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .reference_market import _time


HISTORY_SQL = """select k.key,r.provider,r.system_code,r.language,r.provider_id,
 r.name,r.set_id,r.card_number,r.rarity,s.name as set_name,
 prices.kind,prices.market_value_minor,prices.market_value_high_minor,
 prices.pricing_updated_at,prices.quotes
 from jsonb_to_recordset($1::jsonb) k(
   key text,provider text,system_code text,language text,provider_id text)
 join tcg.reference_cards r using(provider,system_code,language,provider_id)
 join tcg.reference_sets s using(provider,system_code,language,set_id)
 cross join lateral (
   select 'detailed' as kind,m.market_value_minor,m.market_value_high_minor,m.pricing_updated_at,m.quotes
   from tcg.reference_market_prices m
   where (m.provider,m.system_code,m.language,m.provider_id)=(r.provider,r.system_code,r.language,r.provider_id)
   union all
   select 'catalogue',b.market_value_minor,b.market_value_high_minor,b.pricing_updated_at,b.quotes
   from tcg.reference_catalogue_prices b
   where (b.provider,b.system_code,b.language,b.provider_id)=(r.provider,r.system_code,r.language,r.provider_id)
 ) prices
 where (s.release_date is null or s.release_date<=current_date)
   and prices.market_value_minor>0 and prices.pricing_updated_at<$2::timestamptz-interval '7 days'
"""


def historical_guide(record, *, now):
    """Keep the original quote range/date and its existing source constraints."""
    sources = {'TCGDEX_CARDMARKET', 'TCGDEX_CARDMARKET_VARIANT', 'CARDMARKET_BULK_SINGLES'}
    if record.get('kind') == 'catalogue':
        sources = {'CARDMARKET_CATALOGUE'}
    quotes = record.get('quotes') or []
    if isinstance(quotes, str):
        try:
            quotes = json.loads(quotes)
        except ValueError:
            return None
    if not isinstance(quotes, list) or not quotes:
        return None
    quotes = [q for q in quotes if isinstance(q, dict) and q.get('source') in sources]
    if not quotes:
        return None
    identity = {key: record.get(key) for key in ('name', 'set_id', 'card_number', 'set_name')}
    checked, amounts, timestamps = record.get('pricing_updated_at'), [], []
    try:
        checked = _time(checked)
        if not checked < now - timedelta(days=7):
            return None
        for quote in quotes:
            source = quote['source']
            if source.startswith('TCGDEX_') and (record['provider'], record['system_code']) != ('TCGdex', 'POKEMON_TCG'):
                return None
            if quote.get('reference_language', record['language']) != record['language']:
                return None
            if source in {'CARDMARKET_CATALOGUE', 'CARDMARKET_BULK_SINGLES'}:
                if quote.get('reference_identity') != identity:
                    return None
            if source == 'CARDMARKET_BULK_SINGLES':
                if (quote.get('reference_printing_id') != record['provider_id']
                        or quote.get('reference_rarity') != record.get('rarity')):
                    return None
                if record['language'] == 'Japanese' and quote.get('valuation_role') != 'MIXED_NON_ENGLISH_REFERENCE':
                    return None
            amount, original = quote['price_gbp_minor'], quote['original_minor']
            rate = Decimal(str(quote['fx_rate_to_gbp']))
            observed = _time(quote['observed_at'])
            if (type(amount) is not int or amount <= 0 or type(original) is not int or original <= 0
                    or quote.get('original_currency') != 'EUR' or quote.get('fx_source') != 'ECB_EURO_REFERENCE_RATES'
                    or not rate.is_finite() or rate <= 0 or observed > now
                    or int((Decimal(original) * rate).quantize(Decimal('1'), rounding=ROUND_HALF_UP)) != amount):
                return None
            amounts.append(amount)
            timestamps.append(observed)
    except (KeyError, ValueError, TypeError, InvalidOperation):
        return None
    low, high = record.get('market_value_minor'), record.get('market_value_high_minor')
    if (type(low) is not int or type(high) is not int or low != min(amounts) or high != max(amounts)
            or checked != min(timestamps)):
        return None
    regional = any(q.get('valuation_role') == 'MIXED_NON_ENGLISH_REFERENCE' for q in quotes)
    broad = any(q['source'] in {'CARDMARKET_CATALOGUE', 'CARDMARKET_BULK_SINGLES'} for q in quotes)
    reason = ('Last recorded Cardmarket non-English regional guide; Japanese language was not verified.' if regional else
              'Last recorded Cardmarket guide across conditions and languages.' if broad else
              'Last recorded Cardmarket catalogue guide.')
    return {'status': 'STALE', 'currency': 'GBP', 'market_value_minor': None,
            'market_value_high_minor': None, 'last_known_minor': low, 'last_known_high_minor': high,
            'checked_at': checked, 'source': 'Cardmarket', 'label': 'Historical catalogue guide',
            'basis': record['language'] + ' · Raw catalogue reference',
            'reason': reason + ' Refresh unavailable; this is not a current value or an exact-copy sale.',
            'physical_valuation_eligible': False, 'recommended_retail_minor': None}


async def add_reference_history(connection, rows, *, now=None):
    """One page-bounded query after sorting; current prices always take precedence."""
    now = now or datetime.now(timezone.utc)
    items = [dict(row) for row in rows]
    pending = [row for row in items if row.get('source_kind') == 'REFERENCE'
               and row.get('market_value_minor') is None and not row.get('shared_price')]
    if not pending:
        return items
    keys = [{key: row[key] for key in ('key', 'provider', 'system_code', 'language', 'provider_id')}
            for row in pending]
    history = {}
    for record in await connection.fetch(HISTORY_SQL, json.dumps(keys), now):
        value = historical_guide(dict(record), now=now)
        if value and (record['key'] not in history or value['checked_at'] > history[record['key']]['checked_at']):
            history[record['key']] = value
    for row in pending:
        if row['key'] in history:
            row['shared_price'] = history[row['key']]
            # Preserve the existing refresh flag. The browser retains this dated
            # display if a refresh is empty and replaces it when current data arrives.
    return items
