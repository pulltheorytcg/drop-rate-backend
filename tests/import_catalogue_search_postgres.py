"""Real PostgreSQL query regression; synthetic temporary table, no provider writes."""
import asyncio
import os
from urllib.parse import urlparse
from uuid import UUID

import asyncpg
from app.import_catalogue_search import CATALOGUE_SEARCH_SQL, search_tokens

async def main():
    dsn=os.environ['INVENTORY_TEST_DSN']
    target=urlparse(dsn)
    if target.hostname not in {'127.0.0.1','localhost'} or target.path!='/inventory_test':
        raise RuntimeError('This integration test only runs on disposable local inventory_test')
    conn=await asyncpg.connect(dsn)
    try:
        await conn.execute('''create temporary table import_search_catalogue(
          id uuid primary key, game text, name text, set_name text, card_number text,
          variant text, language text, product_type text)''')
        rows=[
          (UUID(int=1),'One Piece','Fixture Pirate','Ocean Set','OP14-041','Foil','Japanese','CARD'),
          (UUID(int=2),'One Piece','Fixture Pirate','Ocean Set','OP14-041','Foil','English','CARD'),
          (UUID(int=3),'Pokemon','Fixture Gem','Phantasmal Flames','041/094','Holofoil','Japanese','CARD'),
          (UUID(int=4),'Pokemon','Fixture Mouse','Pokémon TCG Classic','041','Holofoil','English','CARD'),
          (UUID(int=5),'One Piece','Fixture Pack','Ocean Set','OP14-041',None,'Japanese','SEALED'),
          (UUID(int=6),'One Piece','Other Pirate','Other Set','OP14-041','Foil','Japanese','CARD'),
        ]
        await conn.executemany('insert into import_search_catalogue values($1,$2,$3,$4,$5,$6,$7,$8)',rows)
        # Exact production query: only the source relation is replaced by the fixture table.
        sql=CATALOGUE_SEARCH_SQL.replace('from tcg.catalogue_products p','from pg_temp.import_search_catalogue p')
        async def ids(q,kind='CARD'):
            return {r['id'].int for r in await conn.fetch(sql,q,kind,search_tokens(q))}
        assert await ids('OP14-041 Ocean Set')=={1,2}
        assert await ids('OP14-041 Ocean Set Japanese')=={1}
        assert await ids('OP14–041 Ocean Set Japanese')=={1}
        assert await ids('041 Phantasmal Flames')=={3}
        assert await ids('041 Pokémon TCG: Classic')=={4}
        assert await ids('Fixture Pirate Ocean Set')=={1,2}
        assert await ids('OP14-041 Missing Set')==set(), 'Never silently ignore an explicit set'
        assert await ids('OP14-041 Ocean Set','SEALED')=={5}
        assert await ids('%_')==set()
        assert await ids("'; DROP TABLE catalogue_products; --")==set()
        assert await conn.fetchval('select count(*) from import_search_catalogue')==6
        assert await ids('OP14-041 Ocean Set')=={1,2}, 'Read replay must be stable'
        print('Real PostgreSQL: combined number/set, name/set, punctuation, Unicode, language, product type, wrong set, wildcard/injection and read replay passed.')
    finally:
        await conn.close()

if __name__=='__main__':
    asyncio.run(main())
