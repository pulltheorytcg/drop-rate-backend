"""Read-only CardTrader packaging references; never verified stock or prices."""
from __future__ import annotations

import asyncio
import json
import unicodedata
from collections import defaultdict
from datetime import date

from .cardtrader_recognition import _cardtrader_image_url, _property_value
from .reference_library import save_reference_set


GAME_NAMES = {
    'pokemon': 'POKEMON_TCG', 'pokemon tcg': 'POKEMON_TCG',
    'one piece': 'ONE_PIECE_CARD_GAME', 'one piece card game': 'ONE_PIECE_CARD_GAME',
    'dragon ball super': 'DRAGON_BALL_SUPER_MASTERS',
    'dragon ball super masters': 'DRAGON_BALL_SUPER_MASTERS',
    'dragon ball super fusion world': 'DRAGON_BALL_SUPER_FUSION_WORLD',
}
LANGUAGES = {'en':'English','ja':'Japanese','jp':'Japanese','zh':'Chinese','ko':'Korean',
             'fr':'French','de':'German','it':'Italian','es':'Spanish'}
TYPES = {'booster boxes':'BOOSTER_BOX','booster box':'BOOSTER_BOX','boosters':'BOOSTER_PACK',
         'booster packs':'BOOSTER_PACK','booster pack':'BOOSTER_PACK','elite trainer boxes':'ELITE_TRAINER_BOX',
         'elite trainer box':'ELITE_TRAINER_BOX','starter decks':'STARTER_DECK','decks':'STARTER_DECK',
         'theme decks':'STARTER_DECK','tins':'TIN','collection boxes':'COLLECTION','collections':'COLLECTION',
         'bundles':'BUNDLE','booster bundles':'BUNDLE','blisters':'BLISTER','sealed products':'SEALED_PRODUCT'}


def normalized(value):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD',str(value or '')) if not unicodedata.combining(c)).casefold().split())


def sealed_reference(blueprint, expansion, system, categories):
    category=categories.get(str(blueprint.get('category_id')))
    if not category or str(blueprint.get('expansion_id',expansion['id']))!=str(expansion['id']):
        return None
    provider_id=str(blueprint.get('id') or '')
    name=str(blueprint.get('name') or '').strip()
    if not provider_id.isdecimal() or not name or len(name)>300:
        return None
    # An option/default language is not proof of a physical package's language.
    fixed=_property_value(blueprint,'language','pokemon_language','one_piece_language','dbs_language')
    language=LANGUAGES.get(str(fixed or '').lower(),'Unknown')
    version=str(blueprint.get('version') or '').strip()
    if version and version.casefold() not in name.casefold():
        name=f'{name} · {version}'
    if len(name)>300:
        return None
    return {'provider':'CardTrader','system_code':system,'language':language,'provider_id':provider_id,
            'set_id':str(expansion['id']),'name':name,'product_type':category,
            'image_url':_cardtrader_image_url(blueprint.get('image_url')),
            'source_url':f'https://api.cardtrader.com/api/v2/blueprints/export?expansion_id={expansion["id"]}',
            'evidence':{'category_id':blueprint['category_id'],'expansion_id':expansion['id'],
                        'provider_version':version,'physical_language_unresolved':language=='Unknown',
                        'exact_product_verified':False,'retrieval_only':True}}


async def sealed_feed(client):
    games=await client.list_games()
    systems={str(g['id']):GAME_NAMES[normalized(g.get('name'))] for g in games
             if normalized(g.get('name')) in GAME_NAMES and str(g.get('id','')).isdecimal()}
    expansions=await client.list_expansions()
    selected=[e for e in expansions if str(e.get('game_id')) in systems and str(e.get('id','')).isdecimal()]
    if not selected:
        raise ValueError('No supported sealed expansions returned')
    if len(selected)>2000:
        raise ValueError('Sealed expansion feed exceeds limit')
    categories={}
    for game_id in systems:
        rows=await client.list_categories(game_id=int(game_id))
        categories[game_id]={str(r['id']):TYPES[normalized(r.get('name'))] for r in rows
                            if str(r.get('game_id'))==game_id and normalized(r.get('name')) in TYPES}
    for expansion in sorted(selected,key=lambda e:int(e['id']),reverse=True):
        game_id=str(expansion['game_id'])
        if not categories[game_id]:
            continue
        await asyncio.sleep(.25)
        blueprints=await client.list_blueprints(expansion_id=int(expansion['id']))
        if len(blueprints)>10000:
            raise ValueError('Sealed blueprint feed exceeds limit')
        groups=defaultdict(list)
        for blueprint in blueprints:
            row=sealed_reference(blueprint,expansion,systems[game_id],categories[game_id])
            if row:groups[row['language']].append(row)
        for language,rows in groups.items():
            released=expansion.get('released_at') or expansion.get('release_date')
            try:released=date.fromisoformat(str(released)[:10]).isoformat() if released else None
            except ValueError:released=None
            yield {'provider':'CardTrader','system_code':systems[game_id],'language':language,
                   'set_id':str(expansion['id']),'name':str(expansion['name']),
                   'release_date':released,'source_url':rows[0]['source_url']},rows


async def save_sealed_set(connection,record,rows):
    async with connection.transaction():
        await save_reference_set(connection,record,[])
        await connection.executemany('''insert into tcg.reference_sealed_products
          (provider,system_code,language,provider_id,set_id,name,product_type,image_url,source_url,evidence)
          values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb)
          on conflict(provider,system_code,language,provider_id) do update set
            set_id=excluded.set_id,name=excluded.name,product_type=excluded.product_type,
            image_url=case when tcg.reference_sealed_products.name=excluded.name and tcg.reference_sealed_products.product_type=excluded.product_type
              then coalesce(excluded.image_url,tcg.reference_sealed_products.image_url) else excluded.image_url end,
            source_url=excluded.source_url,evidence=excluded.evidence,
            refreshed_at=clock_timestamp()''',
          [(r['provider'],r['system_code'],r['language'],r['provider_id'],r['set_id'],r['name'],
            r['product_type'],r['image_url'],r['source_url'],json.dumps(r['evidence'])) for r in rows])
