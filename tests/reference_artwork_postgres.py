"""Exercise artwork writes against disposable PostgreSQL, never production."""
import asyncio
import json
import os
from urllib.parse import urlsplit

import asyncpg

from app.reference_artwork import REPAIR_SQL
from app.reference_library import save_reference_set


async def main():
    dsn=os.environ['ARTWORK_TEST_DSN'];url=urlsplit(dsn)
    assert url.hostname in {'localhost','127.0.0.1'} and url.path=='/artwork_test'
    db=await asyncpg.connect(dsn)
    try:
        assert not await db.fetchval("select exists(select 1 from pg_namespace where nspname='tcg')")
        await db.execute('''create schema tcg;
          create table tcg.reference_sets(provider text,system_code text,language text,set_id text,name text,
           release_date date,declared_card_count int,source_url text,refreshed_at timestamptz,
           primary key(provider,system_code,language,set_id));
          create table tcg.reference_cards(provider text,system_code text,language text,provider_id text,set_id text,
           name text,card_number text,number_key text,finish text,rarity text,image_url text,source_url text,
           evidence jsonb default '{}'::jsonb,refreshed_at timestamptz,
           primary key(provider,system_code,language,provider_id));''')
        record=dict(provider='Punk Records',system_code='ONE_PIECE_CARD_GAME',language='Japanese',set_id='550112',name='Pack',source_url='source')
        cards=[dict(provider_id=ident,name='Exact card',card_number='OP12-058',source_url='source',evidence={'original':True})
               for ident in ('OP12-058','OP12-058_p1')]
        await save_reference_set(db,record,cards)
        await save_reference_set(db,dict(record,language='English'),cards)
        art='https://www.onepiece-cardgame.com/images/cardlist/card/OP12-058_p1.png'
        candidates=json.dumps([dict(provider_id='OP12-058_p1',name='Exact card',image_url=art)])
        before=await db.fetchval("select md5(string_agg(concat_ws('|',provider,system_code,language,provider_id,set_id,name,card_number,source_url),'|'order by language,provider_id))from tcg.reference_cards")
        changed=await db.fetch(REPAIR_SQL,'Japanese','550112',candidates,json.dumps({'source':'fixture'}))
        assert len(changed)==1
        assert await db.fetchval("select image_url from tcg.reference_cards where language='Japanese'and provider_id='OP12-058_p1'")==art
        assert await db.fetchval("select evidence->>'original' from tcg.reference_cards where language='Japanese'and provider_id='OP12-058_p1'")=='true'
        assert await db.fetchval("select count(*)from tcg.reference_cards where image_url is not null")==1
        assert not await db.fetch(REPAIR_SQL,'Japanese','550112',candidates,'{}'), 'Replay overwrote existing artwork'
        assert not await db.fetch(REPAIR_SQL,'Japanese','550111',candidates,'{}'), 'Wrong pack matched'
        wrong=json.dumps([dict(provider_id='OP12-058',name='Other card',image_url=art)])
        assert not await db.fetch(REPAIR_SQL,'Japanese','550112',wrong,'{}'), 'Changed identity matched'
        after=await db.fetchval("select md5(string_agg(concat_ws('|',provider,system_code,language,provider_id,set_id,name,card_number,source_url),'|'order by language,provider_id))from tcg.reference_cards")
        assert before==after
        # A sparse later checklist cannot erase known artwork for the same printing.
        await save_reference_set(db,record,cards)
        assert await db.fetchval("select image_url from tcg.reference_cards where language='Japanese'and provider_id='OP12-058_p1'")==art
        assert await db.fetchval("select evidence->'image_reference'->>'source' from tcg.reference_cards where language='Japanese'and provider_id='OP12-058_p1'")=='fixture'
        # Reassigned identities do not retain artwork from the previous card.
        changed_card=dict(cards[1],name='Different card')
        await save_reference_set(db,record,[changed_card])
        assert await db.fetchval("select image_url from tcg.reference_cards where language='Japanese'and provider_id='OP12-058_p1'")is None
        assert not await db.fetchval("select evidence ? 'image_reference' from tcg.reference_cards where language='Japanese'and provider_id='OP12-058_p1'")
    finally:await db.close()
    print('PASS: exact artwork, unchanged identities, replay/race protection, language/parallel isolation and sparse sync')


asyncio.run(main())
