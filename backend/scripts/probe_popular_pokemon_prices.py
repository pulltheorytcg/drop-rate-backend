"""Read-only diagnostics for six confirmed missing popular Pokemon prices.

Run from repository root: python backend/scripts/probe_popular_pokemon_prices.py
No database access, environment secrets, writes, or price substitutions.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.fx import EcbHistoricalFxProvider
from app.reference_market import (
    FINISHES, MAX_AGE, _number, _text, _time, ambiguous_ids,
    tcgdex_quotes, variant_details,
)

CASES = [
    ('sma-SV49', 'Charizard-GX', 'SV49/94', 'sma', 'Hidden Fates Shiny Vault'),
    ('sma-SV59', 'Mewtwo-GX', 'SV59/94', 'sma', 'Hidden Fates Shiny Vault'),
    ('sma-SV69', 'Umbreon-GX', 'SV69/94', 'sma', 'Hidden Fates Shiny Vault'),
    ('sm9-14', 'Charizard', '14/181', 'sm9', 'Team Up'),
    ('swshp-SWSH129', 'Umbreon', 'SWSH129/307', 'swshp', 'SWSH Black Star Promos'),
    ('g1-RC29', 'Pikachu', 'RC29/83', 'g1', 'Generations'),
]


def market_summary(market):
    if not isinstance(market, dict):
        return {'invalid_type': type(market).__name__}
    fields = ('idProduct', 'unit', 'updated', 'trend', 'trend-holo',
              'avg1', 'avg7', 'avg30', 'low', 'normal', 'holofoil', 'reverse-holofoil')
    return {key: market[key] for key in fields if key in market}


def describe(payload, reference, now):
    card_set = payload.get('set') or {}
    mismatches = []
    for field, actual, expected in (
        ('id', payload.get('id'), reference['provider_id']),
        ('set.id', card_set.get('id'), reference['set_id']),
        ('name', _text(payload.get('name')), _text(reference['name'])),
        ('set.name', _text(card_set.get('name')), _text(reference['set_name'])),
        ('localId', _number(payload.get('localId')), _number(reference['card_number'].split('/')[0])),
    ):
        if actual != expected:
            mismatches.append({'field': field, 'actual': actual, 'expected': expected})
    variants = payload.get('variants_detailed')
    rows = []
    detailed = variants if isinstance(variants, list) else []
    ambiguity = ambiguous_ids(detailed, 'cardmarket')
    availability = payload.get('variants') or {}
    for variant in detailed[:40]:
        if not isinstance(variant, dict):
            rows.append({'rejection': 'variant_not_object'})
            continue
        market = (variant.get('pricing') or {}).get('cardmarket') or {}
        product_id = (variant.get('thirdParty') or {}).get('cardmarket')
        kind = variant.get('type')
        flags = []
        field = 'trend'
        if variant.get('size') != 'standard': flags.append('not_standard_size')
        if kind not in FINISHES: flags.append('unsupported_finish')
        if variant_details(variant) is None: flags.append('invalid_treatment')
        if not variant.get('variantId'): flags.append('missing_variant_id')
        if not str(product_id).isdigit() or int(product_id) <= 0: flags.append('missing_cardmarket_id')
        if kind in FINISHES and (str(product_id), FINISHES[kind][0]) in ambiguity:
            flags.append('ambiguous_marketplace_id')
        if availability.get(kind) is not True: flags.append('finish_not_declared')
        if kind == 'reverse':
            field = 'trend-holo'
            if availability.get('normal') is True and availability.get('holo') is True:
                flags.append('ambiguous_reverse_aggregate')
        elif kind == 'holo':
            if availability.get('normal') is True:
                field = 'trend-holo'
                if availability.get('reverse') is not False: flags.append('ambiguous_holo_aggregate')
            elif availability.get('normal') is not False:
                flags.append('normal_availability_unknown')
        if str(market.get('idProduct')) != str(product_id): flags.append('marketplace_id_mismatch')
        if market.get('unit') != 'EUR': flags.append('currency_missing_or_not_eur')
        try:
            observed = _time(market.get('updated'))
            if not now - MAX_AGE <= observed <= now + timedelta(hours=1): flags.append('observation_not_current')
        except (ValueError, TypeError): flags.append('invalid_observed_at')
        if not market.get(field): flags.append('selected_price_missing')
        rows.append({
            'variant_id': variant.get('variantId'), 'type': kind, 'size': variant.get('size'),
            'treatment': variant_details(variant), 'third_party': variant.get('thirdParty'),
            'selected_field': field, 'rejection_flags': flags,
            'cardmarket': market_summary(market),
            'tcgplayer': market_summary((variant.get('pricing') or {}).get('tcgplayer')),
        })
    return {
        'identity_mismatches': mismatches, 'availability': availability,
        'detailed_type': type(variants).__name__, 'detailed_count': len(detailed),
        'root_third_party': payload.get('thirdParty'),
        'root_cardmarket': market_summary((payload.get('pricing') or {}).get('cardmarket')),
        'variant_diagnostics': rows,
    }


async def main():
    now = datetime.now(timezone.utc)
    fx = EcbHistoricalFxProvider(timeout_seconds=6)
    async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
        for case in CASES:
            reference = dict(zip(('provider_id', 'name', 'card_number', 'set_id', 'set_name'), case))
            reference.update(provider='TCGdex', system_code='POKEMON_TCG', language='English')
            result = {'id': case[0], 'observed_at': now.isoformat()}
            try:
                async with client.stream('GET', 'https://api.tcgdex.net/v2/en/cards/' + case[0]) as response:
                    result['http_status'] = response.status_code
                    response.raise_for_status()
                    body = bytearray()
                    async for part in response.aiter_bytes():
                        body.extend(part)
                        if len(body) > 1_000_000: raise ValueError('response_too_large')
                payload = json.loads(body)
                if not isinstance(payload, dict): raise ValueError('response_not_object')
                result.update(describe(payload, reference, now))
                quotes = await asyncio.wait_for(tcgdex_quotes(payload, reference, fx, now=now), timeout=12)
                result['accepted_quotes'] = quotes
            except Exception as exc:
                result['error_type'] = type(exc).__name__
            print(json.dumps(result, ensure_ascii=True, default=str), flush=True)


if __name__ == '__main__':
    try:
        asyncio.run(asyncio.wait_for(main(), timeout=90))
    except TimeoutError:
        print(json.dumps({'status': 'runtime_limit', 'maximum_seconds': 90}), flush=True)
        raise SystemExit(2)
