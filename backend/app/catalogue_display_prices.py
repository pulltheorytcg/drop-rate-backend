"""Read-only shared prices for catalogue aliases, before cards are rendered.

Legacy imports and provider checklists can describe the same base printing with
different IDs. Reuse the inventory resolver's exact identity rules and evidence;
never choose an identity because it has a price, or turn this into an ownership
or intake mapping. No provider calls or price writes happen on this path.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone

from .inventory_catalogue_reference import PRODUCTS_SQL, CACHE_SQL, catalogue_guide, reference_candidates
from .inventory_reference_values import REFERENCE_VALUES_SQL, resolve_reference_value
from .language import clean_language
from .recognition_games import SYSTEM_BY_GAME, collector_key

PRODUCTS = PRODUCTS_SQL.replace('where p.id=any($1::uuid[])', "where p.product_type='CARD'")


def reference_key(row):
    identity = '\x1f'.join(row[k] for k in ('provider', 'system_code', 'language', 'provider_id'))
    return 'r:' + hashlib.md5(identity.encode()).hexdigest()


def shared_prices(products, references, snapshots, *, now):
    """Price-independent singleton matches; unchanged global source timestamps."""
    by_product, by_snapshot = defaultdict(list), defaultdict(list)
    for row in references:
        by_product[str(row['catalogue_id'])].append(row)
    for row in snapshots:
        by_snapshot[str(row['catalogue_id'])].append(row)
    candidates = defaultdict(list)
    for product in products:
        product_id = str(product['id'])
        refs = by_product[product_id]
        language = clean_language(product.get('language'))
        languages = {language} if language else {r['language'] for r in refs}
        for language in sorted(languages):
            matches = reference_candidates(product, refs, language)
            if len({reference_key(r) for r in matches}) != 1:
                continue
            basis = dict(catalogue_id=product_id, product_type='CARD', condition='Near Mint',
                         language=language, catalogue_language=product.get('language'))
            value = resolve_reference_value(basis, by_snapshot[product_id], now=now)
            if value['status'] not in {'AVAILABLE', 'REFERENCE_ESTIMATE'}:
                value = catalogue_guide(product, refs, language, now=now) or value
            if value['status'] == 'AVAILABLE':
                value = dict(value, status='CONDITION_REFERENCE', label='Near-mint reference',
                             reason='Shared near-mint market reference for this exact printing.')
            # Include unpriced candidates too. Duplicate identities must not be
            # resolved by selecting whichever catalogue record happens to sell.
            value = dict(value, physical_valuation_eligible=False, recommended_retail_minor=None)
            candidates[reference_key(matches[0])].append((product_id, value))
            candidates['c:' + product_id].append((product_id, value))
    result = {}
    for key, choices in candidates.items():
        if len(choices) != 1:
            continue
        _, value = choices[0]
        if value.get('market_value_minor') is None and value.get('last_known_minor') is None:
            continue
        result[key] = {
            'key': key, 'market_value_minor': value.get('market_value_minor'),
            'market_value_high_minor': value.get('market_value_high_minor'),
            'pricing_updated_at': value.get('checked_at'), 'basis_condition': value.get('basis'),
            'market_value_source': 'SHARED_CATALOGUE_REFERENCE', 'shared_price': value,
        }
    return result


async def read_shared_prices(connection, rows=None, *, now=None):
    """Page-bounded for normal browsing; all canonical aliases for value sorts.

The canonical directory is small compared with the provider catalogue. Reference
lookups use its number-key index in batches, retaining every parallel candidate.
"""
    if rows is not None and not any(row.get('card_number') for row in rows):
        return {}
    now = now or datetime.now(timezone.utc)
    products = [dict(p) for p in await connection.fetch(PRODUCTS)]
    if rows is not None:
        keys = {collector_key(r.get('card_number')) for r in rows}
        products = [p for p in products if collector_key(p.get('card_number')) in keys]
    products = [p for p in products if not p.get('blocked') and p.get('game') in SYSTEM_BY_GAME
                and collector_key(p.get('card_number'))]
    references, snapshots = [], []
    for start in range(0, len(products), 100):
        batch = products[start:start+100]
        lookups = [dict(catalogue_id=str(p['id']), system_code=SYSTEM_BY_GAME[p['game']],
                        number_key=collector_key(p['card_number'])) for p in batch]
        references.extend(dict(r) for r in await connection.fetch(CACHE_SQL, json.dumps(lookups)))
        snapshots.extend(dict(r) for r in await connection.fetch(REFERENCE_VALUES_SQL, [p['id'] for p in batch], now))
    return shared_prices(products, references, snapshots, now=now)


def with_shared_price(row, prices):
    result = dict(row)
    fallback = prices.get(result.get('key'))
    if result.get('market_value_minor') is None and fallback:
        result.update(fallback)
        # Background catalogue jobs maintain the source. A second browser call
        # cannot replace this shared fallback with an empty provider response.
        if fallback['market_value_minor'] is not None:
            result['market_refresh_needed'] = False
    return result
