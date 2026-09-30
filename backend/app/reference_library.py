"""Independent, source-attributed card/set library; never physical inventory."""
from __future__ import annotations

import json
import re
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder

from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .recognition_games import SYSTEM_BY_GAME, SOURCE_COVERAGE, collector_key

router = APIRouter(prefix="/api/v1/reference-library", tags=["reference-library"])

SYNC_SOURCE_BY_SYSTEM = {
    'POKEMON_TCG':'tcgdex','ONE_PIECE_CARD_GAME':'punk',
    'DRAGON_BALL_SUPER_MASTERS':'dragon_ball_masters',
    'DRAGON_BALL_SUPER_FUSION_WORLD':'dragon_ball_fusion',
    'NARUTO_KAYOU':'naruto_kayou','NARUTO_BANDAI_LEGACY':'naruto_bandai',
}


def number_key(value):
    # Preserve identifier components, fraction boundaries and printing symbols.
    return collector_key(value)


async def save_reference_set(connection, record, cards):
    """Atomic upsert of one provider set. No deletes or canonical writes."""
    async with connection.transaction():
        await connection.execute("""
            insert into tcg.reference_sets(provider,system_code,language,set_id,name,
                release_date,declared_card_count,source_url)
            values($1,$2,$3,$4,$5,$6::text::date,$7,$8)
            on conflict(provider,system_code,language,set_id) do update set
                name=excluded.name,release_date=excluded.release_date,
                declared_card_count=excluded.declared_card_count,
                source_url=excluded.source_url,refreshed_at=clock_timestamp()
        """, record['provider'],record['system_code'],record['language'],record['set_id'],
            record['name'],record.get('release_date'),record.get('declared_card_count'),record['source_url'])
        # A provider can repeat the same record on overlapping pages.
        unique = {str(card['provider_id']): card for card in cards}
        await connection.executemany("""
            insert into tcg.reference_cards(provider,system_code,language,provider_id,
                set_id,name,card_number,number_key,finish,rarity,image_url,source_url,evidence)
            values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb)
            on conflict(provider,system_code,language,provider_id) do update set
                set_id=excluded.set_id,name=excluded.name,card_number=excluded.card_number,
                number_key=excluded.number_key,finish=excluded.finish,rarity=excluded.rarity,
                image_url=excluded.image_url,source_url=excluded.source_url,
                evidence=excluded.evidence,refreshed_at=clock_timestamp()
        """, [(record['provider'],record['system_code'],record['language'],card['provider_id'],
                record['set_id'],card['name'],str(card['card_number']),number_key(card['card_number']),
                card.get('finish'),card.get('rarity'),card.get('image_url'),card['source_url'],
                json.dumps(card.get('evidence') or {})) for card in unique.values()])


async def reference_candidates(connection, observation):
    system = SYSTEM_BY_GAME.get(observation.game)
    if not system or (not observation.card_number and not observation.name_guess):
        return []
    rows = await connection.fetch("""
        select c.*,s.name as set_name,s.release_date
        from tcg.reference_cards c
        join tcg.reference_sets s using(provider,system_code,language,set_id)
        where c.system_code=$1 and c.language in ($2,'Unknown')
          and (($3<>'' and (c.number_key=$3 or
                  ($6 and split_part(c.number_key,':/:',1)=$3)))
               or ($4<>'' and lower(c.name)=lower($4)))
          and (s.release_date is null or s.release_date<=current_date)
        order by (c.number_key=$3) desc,(lower(c.name)=lower($4)) desc,(lower(s.name)=lower($5)) desc,
                 c.provider,c.provider_id
        limit 50
    """,system,observation.language,number_key(observation.card_number),observation.name_guess,observation.set_name_guess,
        system=='POKEMON_TCG' and '/' not in observation.card_number)
    output=[]
    for row in rows:
        card=dict(row)
        evidence=card['evidence']
        if isinstance(evidence,str): evidence=json.loads(evidence)
        output.append({**evidence,"provider":card['provider'],"provider_id":card['provider_id'],
            "name":card['name'],"base_card_id":card['card_number'],"set_name":card['set_name'],
            "set_id":card['set_id'],"language":card['language'],"rarity":card['rarity'],
            "finish":card['finish'],"image_url":card['image_url'],"source_reference":card['source_url'],
            "library_reference":True,"exact_printing_verified":False,
            "system_code":system,
            "release_status":"RELEASED" if card['release_date'] else "UNKNOWN",
            "refreshed_at":card['refreshed_at'].isoformat()})
    return output


@router.get("/coverage")
async def library_coverage(request:Request,user:Annotated[AuthenticatedUser,Depends(require_user)]):
    async with user_connection(request.app.state.db_pool,user.user_id,request.state.request_id) as connection:
        rows=await connection.fetch("""
          select s.system_code,s.provider,s.language,count(distinct s.set_id)::int as sets,
                 count(c.provider_id)::int as cards,max(s.refreshed_at) as refreshed_at,
                 count(c.provider_id) filter(where s.release_date>current_date)::int as upcoming_cards
          from tcg.reference_sets s left join tcg.reference_cards c
            using(provider,system_code,language,set_id)
          group by s.system_code,s.provider,s.language
        """)
        runs=await connection.fetch('''select distinct on (source) source,status,started_at,
            finished_at,sets_loaded,cards_loaded,report from tcg.reference_sync_runs
            order by source,started_at desc,id desc''')
    return jsonable_encoder({"games":[{"game":game,"system_code":system,
        "source":SOURCE_COVERAGE[game][0],"coverage_note":SOURCE_COVERAGE[game][1],
        "sources":[dict(r) for r in rows if r['system_code']==system],
        "latest_sync":next((dict(r) for r in runs if r['source']==SYNC_SOURCE_BY_SYSTEM.get(system)),None),
        "status":("INDEXED" if any(r['system_code']==system and r['cards']>0 for r in rows)
                  else "NOT_INDEXED") if system in SYNC_SOURCE_BY_SYSTEM else "DEFERRED"}
        for game,system in SYSTEM_BY_GAME.items()],
        "accuracy_measured":False,"note":"Reference coverage is not a measured recognition accuracy or a complete worldwide release checklist."})


@router.get("/sets")
async def library_sets(request:Request,user:Annotated[AuthenticatedUser,Depends(require_user)],
    system_code:str=Query(max_length=80),search:str=Query(default="",max_length=160),
    limit:int=Query(default=50,ge=1,le=100),offset:int=Query(default=0,ge=0)):
    async with user_connection(request.app.state.db_pool,user.user_id,request.state.request_id) as connection:
        rows=await connection.fetch("""
          select s.*, (select count(*) from tcg.reference_cards c where
             c.provider=s.provider and c.system_code=s.system_code and c.language=s.language and c.set_id=s.set_id) as indexed_cards,
             case when release_date>current_date then 'UPCOMING' when release_date is null then 'UNKNOWN' else 'RELEASED' end as release_status
          from tcg.reference_sets s where system_code=$1
             and ($2='' or name ilike '%' || $2 || '%' or set_id ilike '%' || $2 || '%')
          order by release_date desc nulls last,name,provider,language,set_id limit $3 offset $4
        """,system_code,search,limit+1,offset)
    return jsonable_encoder({"items":[dict(r) for r in rows[:limit]],"has_more":len(rows)>limit,"offset":offset})


@router.get("/cards")
async def library_cards(request:Request,user:Annotated[AuthenticatedUser,Depends(require_user)],
    system_code:str=Query(max_length=80),set_id:str=Query(default="",max_length=200),
    search:str=Query(default="",max_length=160),provider:str=Query(default="",max_length=80),
    language:str=Query(default="",max_length=40),limit:int=Query(default=50,ge=1,le=100),offset:int=Query(default=0,ge=0)):
    async with user_connection(request.app.state.db_pool,user.user_id,request.state.request_id) as connection:
        rows=await connection.fetch("""
          select provider,system_code,language,provider_id,set_id,name,card_number,finish,rarity,source_url,refreshed_at
          from tcg.reference_cards where system_code=$1 and ($2='' or set_id=$2)
           and ($3='' or name ilike '%' || $3 || '%' or number_key=$4)
           and ($5='' or provider=$5) and ($6='' or language=$6)
          order by name,provider,language,provider_id limit $7 offset $8
        """,system_code,set_id,search,number_key(search),provider,language,limit+1,offset)
    return jsonable_encoder({"items":[dict(r) for r in rows[:limit]],"has_more":len(rows)>limit,"offset":offset,
        "verification":"Provider reference records; not verified physical printing identities."})
