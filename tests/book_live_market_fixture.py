"""Real SQL persistence/readback for books using synthetic sold responses only."""
from datetime import datetime,timedelta,timezone
from uuid import uuid4

from app import live_market_refresh as market
from app.book_market import attach_book_printings
from app.catalogue_valuations import refresh_catalogue_values
from app.catalogue_display_prices import read_book_prices
from app.db import user_connection
from app.inventory_reference_values import add_shared_reference_values


async def exercise(db,pool,actor,other):
    await db.execute('''alter table tcg.catalogue_product_profiles add column system_code text,add column collectible_type text;
        alter table tcg.inventory_items add column notes text;
        alter table tcg.market_observations add column ingested_at timestamptz default now();
        create table tcg.comic_printing_details(catalogue_id uuid primary key,system_code text,series_title text,
          issue_number text,volume_identifier text,printing_number int,release_year int,cover_code text,
          cover_artist text,barcode_gtin text,identity_status text,attributes jsonb);
        grant select,update on tcg.comic_printing_details to tcg_api;''')
    cat,a,b,special=[uuid4() for _ in range(4)]
    await db.execute("insert into tcg.catalogue_products values($1,'COMIC','Marvel Comics','Fixture Hero #1','Fixture Hero (2022)','1','Cover A Printing 1','','English')",cat)
    await db.execute("insert into tcg.catalogue_product_profiles(catalogue_id,identity_status,system_code,collectible_type) values($1,'VERIFIED','MARVEL_COMICS','COMIC')",cat)
    await db.execute("""insert into tcg.comic_printing_details(catalogue_id,system_code,series_title,issue_number,printing_number,release_year,cover_code,identity_status,attributes)
        values($1,'MARVEL_COMICS','Fixture Hero','1',1,2022,'Cover A','VERIFIED','{"publisher":"Marvel","book_format":"SINGLE_ISSUE"}')""",cat)
    for ident,owner,notes in ((a,actor,None),(b,other,None),(special,actor,'Signed by artist')):
        await db.execute("""insert into tcg.inventory_items(id,owner_id,catalogue_id,inventory_code,version,status,identity_confirmed,condition,language,store_price_minor,notes)
            values($1,$2,$3,$1::text,1,'APPROVED',true,'Near Mint','English',9000,$4)""",ident,owner,cat,notes)
    async def targets():
        async with user_connection(pool,actor,'book-market-targets') as conn:
            rows=[dict(r) for r in await conn.fetch(market.TARGET_SQL+' where i.catalogue_id=$1',cat)]
            return await attach_book_printings(conn,rows)
    class Client:
        change=False
        async def sold(self,**kwargs):
            assert kwargs['max_pages']==1
            if self.change:await db.execute('update tcg.comic_printing_details set printing_number=2 where catalogue_id=$1',cat)
            now=datetime.now(timezone.utc)
            return dict(site='EBAY_GB',currency='GBP',results=[dict(item_id=str(8000+n),
                title='Fixture Hero #1 Marvel 2022 English first printing Cover A Near Mint',sale_price=10+n,
                shipping_price=2,currency='GBP',condition_raw='Near Mint',date_sold=(now-timedelta(days=n)).isoformat()) for n in range(1,6)])
    client=Client();rows=await targets();raw=[r for r in rows if not r['notes']]
    client.change=True
    changed=await market.refresh_group(pool,actor,actor,raw,client)
    assert changed['updated']==0
    assert await db.fetchval('select count(*) from tcg.market_observations where catalogue_id=$1',cat)==0
    await db.execute('update tcg.comic_printing_details set printing_number=1 where catalogue_id=$1',cat);client.change=False
    result=await market.refresh_group(pool,actor,actor,raw,client)
    assert result['updated']==2,result
    assert await db.fetchval('select count(*) from tcg.market_observations where catalogue_id=$1',cat)==5
    assert await db.fetchval("select bool_and(metadata->>'selection_rule'='FIVE_NEWEST_EXACT_BOOK_SALES' and length(metadata->>'book_identity_digest')=64) from tcg.market_observations where catalogue_id=$1",cat)
    assert await db.fetchval('select market_value_minor from tcg.inventory_items where id=$1',special) is None
    result=await refresh_catalogue_values(pool,actor)
    assert await db.fetchval('select count(*) from tcg.catalogue_market_snapshots where catalogue_id=$1',cat)==1,result
    values=[]
    for owner,ident in ((actor,a),(other,b)):
        async with user_connection(pool,owner,'book-market-readback') as conn:
            item=dict(await conn.fetchrow(market.TARGET_SQL+' where i.id=$1',ident))
            await add_shared_reference_values(conn,[item]);values.append(item['reference_value'])
    assert values[0]==values[1] and values[0]['status']=='AVAILABLE'
    async with user_connection(pool,actor,'book-signed-readback') as conn:
        item=dict(await conn.fetchrow(market.TARGET_SQL+' where i.id=$1',special))
        await add_shared_reference_values(conn,[item])
        assert item['market_value_minor'] is None
        display=await read_book_prices(conn,[{'catalogue_id':cat,'product_type':'COMIC'}],now=datetime.now(timezone.utc))
        assert display['c:'+str(cat)]['market_value_minor']==values[0]['market_value_minor']
        assert display['c:'+str(cat)]['shared_price']['physical_valuation_eligible'] is False
    await db.execute('update tcg.comic_printing_details set printing_number=2 where catalogue_id=$1',cat)
    async with user_connection(pool,actor,'book-changed-printing') as conn:
        item=dict(await conn.fetchrow(market.TARGET_SQL+' where i.id=$1',a))
        await add_shared_reference_values(conn,[item])
        assert item['market_value_minor'] is None
        assert not await read_book_prices(conn,[{'catalogue_id':cat,'product_type':'COMIC'}],now=datetime.now(timezone.utc))
    assert await db.fetchval('select count(*) from tcg.market_observations where catalogue_id=$1',cat)==5
    assert await db.fetchval('select count(*) from tcg.catalogue_market_snapshots where catalogue_id=$1',cat)==1
    assert await db.fetchval('select bool_and(store_price_minor=9000) from tcg.inventory_items where catalogue_id=$1',cat)
    print('PASS: exact-book persistence, changed-printing race, full edition digest, immutable evidence, shared owner-independent values, special-copy exclusion, catalogue basis and unchanged selling prices.')
