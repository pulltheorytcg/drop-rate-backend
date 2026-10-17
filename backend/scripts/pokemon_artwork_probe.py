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
        report = await asyncio.wait_for(run(), 45)
    except Exception as exc:
        report = {'status':'UNAVAILABLE','error_type':type(exc).__name__,'status_code':getattr(exc,'status_code',None),'persisted':False}
    print('POKEMON_ARTWORK_PROBE '+json.dumps(report,default=str),flush=True)


if __name__ == '__main__':
    asyncio.run(main())
