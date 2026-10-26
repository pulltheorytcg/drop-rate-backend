"""Bounded read-only CardTrader identity probe for Hidden Fates Shiny Vault.

Uses the existing CardTrader token; prints only public identity metadata.
Run: python backend/scripts/probe_hidden_fates_cardtrader.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.cardtrader_client import CardTraderClient
from app.cardtrader_media import _collector_number
from app.cardtrader_reference_probe import number_key
from app.pokemon_cardtrader_market import SINGLE_CATEGORIES
from app.pokemon_catalogue_market import normalized
from app.reference_sealed import normalized as game_name


async def probe(client):
    report = {'read_only': True, 'provider_calls': 0, 'price_writes': 0}
    try:
        report['provider_calls'] += 1
        games = await client.list_games()
        game_ids = {g['id'] for g in games if game_name(g.get('name')) in {'pokemon', 'pokemon tcg'}}
        if len(game_ids) != 1:
            raise ValueError('pokemon_game_not_unique')
        game_id = next(iter(game_ids))
        report['provider_calls'] += 1
        expansions = await client.list_expansions()
        matches = [e for e in expansions if e.get('game_id') == game_id
                   and normalized(e.get('name')) == normalized('Hidden Fates')]
        report['related_expansions'] = [
            {k: e.get(k) for k in ('id', 'game_id', 'name')}
            for e in expansions if e.get('game_id') == game_id
            and 'hiddenfates' in normalized(e.get('name'))][:20]
        if len(matches) != 1:
            raise ValueError('hidden_fates_expansion_not_unique')
        expansion = matches[0]
        report['provider_calls'] += 1
        categories = await client.list_categories(game_id=game_id)
        singles = {c['id'] for c in categories if c.get('game_id') == game_id
                   and game_name(c.get('name')) in SINGLE_CATEGORIES}
        if not singles:
            raise ValueError('single_categories_unavailable')
        report['provider_calls'] += 1
        blueprints = await client.list_blueprints(expansion_id=expansion['id'])
        if not blueprints or len(blueprints) > 10000:
            raise ValueError('blueprint_count_invalid')
        report['blueprints_returned'] = len(blueprints)
        report['single_categories'] = sorted(singles)
        targets = {number_key(x) for x in ('9', 'SV49', 'SV59', 'SV69')}
        selected = [b for b in blueprints if b.get('game_id') == game_id
                    and b.get('expansion_id') == expansion['id']
                    and b.get('category_id') in singles
                    and number_key(_collector_number(b)) in targets]
        report['selected_count'] = len(selected)
        report['blueprints'] = [
            {**{k: b.get(k) for k in ('id', 'game_id', 'expansion_id', 'category_id',
                                     'name', 'version', 'fixed_properties', 'card_market_ids')},
             'collector_number': _collector_number(b)} for b in selected[:40]]
        report['status'] = 'COMPLETE' if len(selected) <= 40 else 'OUTPUT_TRUNCATED'
    except Exception as exc:
        report.update(status='FAILED', error_type=type(exc).__name__)
    return report


async def main():
    token = os.getenv('TCG_CARDTRADER_API_TOKEN') or os.getenv('CARDTRADER_API_TOKEN')
    if not token:
        print(json.dumps({'status': 'TOKEN_NOT_CONFIGURED', 'read_only': True}), flush=True)
        return
    client = CardTraderClient(api_token=token, timeout_seconds=8)
    result = await asyncio.wait_for(probe(client), timeout=45)
    print(json.dumps(result, ensure_ascii=True, default=str), flush=True)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except TimeoutError:
        print(json.dumps({'status': 'runtime_limit', 'maximum_seconds': 45}), flush=True)
        raise SystemExit(2)
