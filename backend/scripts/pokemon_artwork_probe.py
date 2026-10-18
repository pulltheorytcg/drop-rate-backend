"""Opt-in, bounded read-only inspection of an already-connected artwork source.

No database, market requests, approval, upload or secret output. This is evidence
for a reviewed repair, not a scheduled job or permission to substitute artwork.
"""
import asyncio
import json
import os
from app.cardtrader_client import CardTraderClient
from app.cardtrader_media import _collector_number
from app.pokemon_catalogue_market import normalized
from app.settings import get_settings
from app.reference_sealed import normalized as game_name

REVIEW_RELEASES = (
    'Shining Fates', 'Crown Zenith', 'Brilliant Stars', 'Astral Radiance',
    'Lost Origin', 'Silver Tempest', 'Dragon Majesty', 'Shining Legends',
    'Aquapolis', 'Skyridge', 'Sun & Moon Promos', 'Sword & Shield Promos',
)


async def review_records():
    """Bounded public source export for visual review; no database or writes."""
    client = CardTraderClient(api_token=get_settings().cardtrader_api_token)
    games = await client.list_games()
    game_ids = {g['id'] for g in games if game_name(g.get('name')) in {'pokemon', 'pokemon tcg'}}
    if len(game_ids) != 1:
        return {'status': 'GAME_UNRESOLVED', 'persisted': False}
    game = next(iter(game_ids))
    expansions = await client.list_expansions()
    report = {'status': 'READ_ONLY_REVIEW', 'persisted': False, 'provider_calls': 2, 'sets': []}
    for title in REVIEW_RELEASES:
        candidates = [e for e in expansions if e.get('game_id') == game
                      and normalized(e.get('name')) == normalized(title)]
        if len(candidates) != 1:
            report['sets'].append({'title': title, 'status': 'EXPANSION_UNRESOLVED'})
            continue
        expansion = candidates[0]
        blueprints = await client.list_blueprints(expansion_id=expansion['id'])
        report['provider_calls'] += 1
        if len(blueprints) > 2000:
            raise ValueError('Artwork review bound exceeded')
        count = 0
        for b in blueprints:
            if b.get('game_id') != game or b.get('expansion_id') != expansion['id']:
                continue
            language = next((p for p in b.get('editable_properties', [])
                             if p.get('name') == 'pokemon_language'), {})
            row = {k: b.get(k) for k in ('id', 'name', 'version', 'game_id', 'category_id', 'expansion_id', 'image_url', 'card_market_ids')}
            row.update(collector_number=_collector_number(b), expansion_name=expansion['name'],
                       expansion_code=expansion.get('code'),
                       language_default=language.get('default_value'),
                       language_options=language.get('possible_values'))
            # One public record per log line avoids truncating an entire export.
            print('POKEMON_ARTWORK_RECORD ' + json.dumps(row, ensure_ascii=False), flush=True)
            # Railway drops bursts above its log-ingestion limit. Keep a complete
            # review export well below that ceiling, including shared log traffic.
            await asyncio.sleep(0.025)
            count += 1
        report['sets'].append({'title': title, 'expansion_id': expansion['id'], 'records': count})
    return report


async def run():
    client = CardTraderClient(api_token=get_settings().cardtrader_api_token)
    games = await client.list_games()
    game_ids = {g['id'] for g in games if game_name(g.get('name')) in {'pokemon','pokemon tcg'}}
    if len(game_ids) != 1:
        return {'status':'GAME_UNRESOLVED','persisted':False}
    game = next(iter(game_ids))
    expansions = await client.list_expansions()
    candidates = [e for e in expansions if e.get('game_id') == game and
                  'shiningfates' in normalized(e.get('name'))]
    report = {'status':'READ_ONLY','persisted':False,'expansions':[
        {k:e.get(k) for k in ('id','game_id','name','code')} for e in candidates[:8]],'samples':[]}
    # At most two exact release exports. The probe deliberately does no matching/write.
    for expansion in candidates[:2]:
        blueprints = await client.list_blueprints(expansion_id=expansion['id'])
        samples = [b for b in blueprints if 'sv001' in str(_collector_number(b)).casefold()
                   or normalized(b.get('name')) in {'rowlet','dartrix','decidueye'}][:8]
        report['samples'].append({'expansion_id':expansion['id'],'blueprints':len(blueprints),'records':[
            {**{k:b.get(k) for k in ('id','name','version','game_id','category_id','expansion_id','image_url')},
             'collector_number':_collector_number(b),'properties':b.get('fixed_properties',b.get('properties')),
             'editable_properties':b.get('editable_properties')} for b in samples]})
    return report


async def main():
    if os.getenv('DROP_RATE_POKEMON_ART_PROBE') != '1':
        return
    try:
        expanded = os.getenv('DROP_RATE_POKEMON_ART_REVIEW') == '1'
        report = await asyncio.wait_for(review_records() if expanded else run(), 90 if expanded else 45)
    except Exception as exc:
        report = {'status':'UNAVAILABLE','error_type':type(exc).__name__,'status_code':getattr(exc,'status_code',None),'persisted':False}
    print('POKEMON_ARTWORK_PROBE '+json.dumps(report,default=str),flush=True)


if __name__ == '__main__':
    asyncio.run(main())
